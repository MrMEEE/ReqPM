"""
Mock builder plugin - Uses Mock for building RPMs

Key design for concurrent builds:
1. Build SRPMs with rpmbuild (not Mock) - fast, no chroot needed
2. Use Mock only for RPM builds from SRPM
3. Use --no-clean to reuse bootstrap chroot (shared, one per target)
4. Use --uniqueext for build chroot (one per package build) to prevent lock conflicts
5. Bootstrap chroot: /var/lib/mock/rhel-10-x86_64/ (shared)
6. Build chroot: /var/lib/mock/rhel-10-x86_64-build{N}/ (unique per build)

This allows multiple concurrent builds of the same target without conflicts.
Based on patterns from https://github.com/MrMEEE/awx-rpm-v2
"""
import os
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional
from .base import BaseBuilder, BuildResult
from backend.core.gpg_key_manager import get_gpg_key_manager
import logging

logger = logging.getLogger(__name__)


class MockBuilder(BaseBuilder):
    """
    Mock-based RPM builder
    
    Uses the Mock build system to create RPMs in clean chroot environments
    """
    
    def __init__(self, config: Dict):
        super().__init__(config)
        self.mock_bin = self._find_mock_binary()
        reqpm_config = getattr(config, 'REQPM', {})
        self.mock_config_dir = reqpm_config.get('MOCK_CONFIG_DIR', '/etc/mock')
        self.cache_dir = reqpm_config.get('MOCK_CACHE_DIR', '/var/cache/mock')
        self.gpg_keys_cache_dir = reqpm_config.get('GPG_KEYS_CACHE_DIR', '/var/cache/reqpm/distribution-gpg-keys')
        self.auto_update_gpg_keys = reqpm_config.get('AUTO_UPDATE_GPG_KEYS', True)
        self._gpg_keys_checked = False  # Track if we've checked keys in this session
    
    @property
    def name(self) -> str:
        return "Mock"
    
    @property
    def version(self) -> str:
        """Get Mock version"""
        try:
            result = subprocess.run(
                [self.mock_bin, '--version'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return "unknown"
    
    def _find_mock_binary(self) -> str:
        """Find mock binary path"""
        for path in ['/usr/bin/mock', '/usr/local/bin/mock']:
            if os.path.exists(path) and os.access(path, os.X_OK):
                return path
        return 'mock'
    
    def is_available(self) -> bool:
        """Check if Mock is installed and accessible"""
        try:
            result = subprocess.run(
                [self.mock_bin, '--version'],
                capture_output=True,
                timeout=10
            )
            if result.returncode == 0:
                return True
            else:
                logger.error(f"Mock installed but not accessible. Check permissions and group membership.")
                return False
        except FileNotFoundError:
            logger.error(
                "Mock is not installed on this system. "
                "Install it with: sudo dnf install mock\n"
                "See docs/MOCK_SETUP.md for complete setup instructions."
            )
            return False
        except Exception as e:
            logger.error(f"Mock not available: {e}")
            return False
    
    def _ensure_gpg_keys_updated(self) -> bool:
        """
        Ensure GPG keys are up to date before building
        
        This prevents build failures due to outdated or missing GPG keys.
        Updates are performed automatically if enabled and keys are stale.
        
        Returns:
            True if keys are ready, False if update failed
        """
        # Only check once per builder instance to avoid redundant updates
        if self._gpg_keys_checked:
            return True
        
        if not self.auto_update_gpg_keys:
            logger.debug("Automatic GPG key updates are disabled")
            self._gpg_keys_checked = True
            return True
        
        try:
            logger.info("Checking GPG keys status...")
            manager = get_gpg_key_manager(cache_dir=self.gpg_keys_cache_dir)
            
            # Check if update is needed (max age: 7 days)
            if manager.is_update_needed(max_age_days=7):
                logger.info("GPG keys are stale or missing, updating...")
                success, message = manager.update_keys(force=False)
                
                if success:
                    logger.info(f"GPG keys updated successfully: {message}")
                else:
                    logger.warning(f"Failed to update GPG keys: {message}")
                    # Don't fail the build, just warn
                    # Existing keys might still work
            else:
                logger.debug("GPG keys are up to date")
            
            # Mark as checked
            self._gpg_keys_checked = True
            return True
            
        except Exception as e:
            logger.warning(f"Error checking GPG keys: {e}")
            # Don't fail the build
            self._gpg_keys_checked = True
            return True
    
    def get_available_targets(self) -> List[str]:
        """Get list of available Mock configurations"""
        configs = []
        try:
            config_dir = Path(self.mock_config_dir)
            if config_dir.exists():
                for cfg_file in config_dir.glob('*.cfg'):
                    # Extract config name (without .cfg extension)
                    config_name = cfg_file.stem
                    configs.append(config_name)
        except Exception as e:
            logger.error(f"Error listing Mock configs: {e}")
        
        return sorted(configs)
    
    def validate_target(self, target: str, arch: str = 'x86_64') -> bool:
        """Validate if Mock configuration exists"""
        # Mock config format: usually <dist>-<version>-<arch>.cfg
        # e.g., rhel-9-x86_64.cfg
        config_file = Path(self.mock_config_dir) / f"{target}.cfg"
        return config_file.exists()
    
    def _run_mock_command(
        self,
        args: List[str],
        timeout: int = 3600
    ) -> tuple[int, str, str]:
        """
        Run a mock command with proper privileges
        
        Args:
            args: Command arguments
            timeout: Command timeout in seconds
        
        Returns:
            Tuple of (returncode, stdout, stderr)
        """
        # On Ubuntu/Debian, Mock needs to be run with sudo
        # Check if we're running as root, if not, prepend sudo
        if os.geteuid() != 0:
            cmd = ['sudo', '-n', self.mock_bin] + args
        else:
            cmd = [self.mock_bin] + args
            
        logger.debug(f"Running mock command: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            logger.error(f"Mock command timed out after {timeout}s")
            return -1, "", "Command timed out"
        except Exception as e:
            logger.error(f"Error running mock command: {e}")
            return -1, "", str(e)
    
    def fetch_sources(
        self,
        spec_file: str,
        sources_dir: str,
        **kwargs
    ) -> BuildResult:
        """
        Fetch source files from URLs defined in spec file
        
        Parses the spec file for Source/Patch directives and downloads them.
        Based on awx-rpm-v2 getsources script but using Python instead of spectool.
        
        Args:
            spec_file: Path to the spec file
            sources_dir: Directory where sources should be downloaded
        
        Returns:
            BuildResult with success status and log output
        """
        import re
        import requests
        from urllib.parse import urlparse
        
        start_time = time.time()
        log_lines = []
        
        # Ensure sources directory exists
        Path(sources_dir).mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Parsing spec file for sources: {spec_file}")
        log_lines.append(f"Parsing spec file: {spec_file}")
        
        try:
            # Read spec file and extract Source/Patch URLs
            with open(spec_file, 'r') as f:
                spec_content = f.read()
            
            # Extract package name and version from spec
            name_match = re.search(r'^Name:\s+(.+)$', spec_content, re.MULTILINE)
            version_match = re.search(r'^Version:\s+(.+)$', spec_content, re.MULTILINE)
            
            package_name = name_match.group(1).strip() if name_match else None
            package_version = version_match.group(1).strip() if version_match else None
            
            # Remove python3- prefix for PyPI lookups
            pypi_name = package_name.replace('python3-', '').replace('python-', '') if package_name else None
            
            log_lines.append(f"Package: {package_name}, Version: {package_version}, PyPI name: {pypi_name}")
            
            # Find all Source and Patch directives
            # Format: Source0: https://example.com/file.tar.gz
            # or: Source0: %{pypi_source package}
            # or: Patch0: some-patch.patch
            source_pattern = re.compile(r'^(Source|Patch)(\d+):\s+(.+)$', re.MULTILINE | re.IGNORECASE)
            sources = source_pattern.findall(spec_content)
            
            if not sources:
                log_lines.append("No Source/Patch directives found in spec file")
                logger.info("No sources to download")
                return BuildResult(
                    success=True,
                    log_output="\n".join(log_lines),
                    build_duration=int(time.time() - start_time)
                )
            
            log_lines.append(f"Found {len(sources)} source/patch directive(s)")
            
            # Download each source
            downloaded = 0
            for source_type, source_num, source_url in sources:
                source_url = source_url.strip()
                original_url = source_url
                
                # Expand %{pypi_source} macro
                # Format: %{pypi_source package} or %{pypi_source package version}
                if '%{pypi_source' in source_url and pypi_name and package_version:
                    # Extract package name from macro if specified
                    macro_match = re.match(r'%\{pypi_source\s+(\w+)(?:\s+[\d.]+)?\}', source_url)
                    if macro_match:
                        macro_package = macro_match.group(1)
                    else:
                        macro_package = pypi_name
                    
                    # Construct PyPI download URL
                    # Format: https://pypi.io/packages/source/{first_letter}/{package}/{package}-{version}.tar.gz
                    first_letter = macro_package[0].lower()
                    source_url = f"https://pypi.io/packages/source/{first_letter}/{macro_package}/{macro_package}-{package_version}.tar.gz"
                    log_lines.append(f"Expanded macro: {original_url} -> {source_url}")
                
                # Skip if it's a local file (doesn't start with http/https/ftp)
                if not source_url.startswith(('http://', 'https://', 'ftp://')):
                    log_lines.append(f"Skipping {source_type}{source_num}: {source_url} (local file or unexpanded macro)")
                    continue
                
                # Extract filename from URL
                parsed_url = urlparse(source_url)
                filename = Path(parsed_url.path).name
                
                if not filename:
                    log_lines.append(f"Warning: Could not extract filename from {source_url}")
                    continue
                
                output_path = Path(sources_dir) / filename
                
                # Skip if already downloaded
                if output_path.exists():
                    log_lines.append(f"Already exists: {filename}")
                    downloaded += 1
                    continue
                
                log_lines.append(f"Downloading {source_type}{source_num}: {source_url}")
                logger.info(f"Downloading {source_url} -> {output_path}")
                
                try:
                    # Download with requests
                    response = requests.get(source_url, timeout=300, stream=True)
                    response.raise_for_status()
                    
                    # Write to file
                    with open(output_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)
                    
                    file_size = output_path.stat().st_size
                    log_lines.append(f"Downloaded: {filename} ({file_size} bytes)")
                    downloaded += 1
                    
                except requests.RequestException as e:
                    error_msg = f"Failed to download {source_url}: {str(e)}"
                    log_lines.append(f"ERROR: {error_msg}")
                    logger.error(error_msg)
                    return BuildResult(
                        success=False,
                        error_message=error_msg,
                        log_output="\n".join(log_lines),
                        build_duration=int(time.time() - start_time)
                    )
            
            log_lines.append(f"Successfully processed {downloaded} source(s)")
            logger.info(f"Source fetching complete: {downloaded} files")
            
            return BuildResult(
                success=True,
                log_output="\n".join(log_lines),
                build_duration=int(time.time() - start_time)
            )
            
        except Exception as e:
            error_msg = f"Source fetch exception: {str(e)}"
            log_lines.append(f"ERROR: {error_msg}")
            logger.error(error_msg)
            return BuildResult(
                success=False,
                error_message=error_msg,
                log_output="\n".join(log_lines),
                build_duration=int(time.time() - start_time)
            )
    
    def build_srpm(
        self,
        spec_file: str,
        sources_dir: str,
        output_dir: str,
        target: str = None,
        **kwargs
    ) -> BuildResult:
        """
        Build SRPM using rpmbuild directly (not Mock)
        
        AWX-RPM builds SRPMs with rpmbuild -bs, then uses Mock for RPM builds
        """
        start_time = time.time()
        
        # Prepare output directory
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        # Build SRPM with rpmbuild (like AWX-RPM does)
        cmd = [
            'rpmbuild',
            '-bs',
            '--define', f'_topdir {output_dir}',
            '--define', f'_sourcedir {sources_dir}',
            '--define', f'_srcrpmdir {output_dir}',
            spec_file
        ]
        
        logger.info(f"Building SRPM: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600
            )
            
            build_duration = int(time.time() - start_time)
            log_output = f"{result.stdout}\n{result.stderr}"
            
            if result.returncode == 0:
                # Find the built SRPM
                srpm_files = list(Path(output_dir).glob('*.src.rpm'))
                if srpm_files:
                    return BuildResult(
                        success=True,
                        srpm_path=str(srpm_files[0]),
                        log_output=log_output,
                        build_duration=build_duration
                    )
                else:
                    return BuildResult(
                        success=False,
                        error_message="SRPM file not found after build",
                        log_output=log_output,
                        build_duration=build_duration
                    )
            else:
                return BuildResult(
                    success=False,
                    error_message=f"rpmbuild failed with code {result.returncode}",
                    log_output=log_output,
                    build_duration=build_duration
                )
        except Exception as e:
            return BuildResult(
                success=False,
                error_message=f"Build exception: {str(e)}",
                log_output="",
                build_duration=int(time.time() - start_time)
            )
    
    def build_rpm(
        self,
        srpm_path: str,
        target: str,
        arch: str,
        output_dir: str,
        **kwargs
    ) -> BuildResult:
        """
        Build RPM using mock --rebuild
        
        Uses --uniqueext to allow concurrent builds without conflicts.
        The uniqueext only affects the build chroot, not the bootstrap chroot.
        Uses --no-clean to reuse the bootstrap chroot (which is shared).
        """
        start_time = time.time()
        
        # Ensure GPG keys are up to date before building
        # This prevents GPG key mismatch errors in RHEL builds
        self._ensure_gpg_keys_updated()
        
        # Prepare output directory
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        # Get unique extension for this build
        unique_ext = kwargs.get('unique_ext', f"build{int(time.time())}")
        
        # Mock rebuild command
        # --no-clean: Reuse bootstrap chroot (shared, no uniqueext)
        # --uniqueext: Make build chroot unique (prevents lock conflicts)
        args = [
            '-r', target,
            '--arch', arch,
            '--uniqueext', unique_ext,  # Unique build chroot for concurrent builds
            '--enable-network',
            '--resultdir', output_dir,
            '--no-clean',  # Reuse bootstrap chroot
            '--no-cleanup-after',  # Keep for debugging
            '--rpmbuild-opts=--nocheck',  # Skip tests
            '--rebuild', srpm_path,
        ]
        
        logger.info(f"Building RPM with Mock: {target} {arch} (uniqueext={unique_ext})")
        
        returncode, stdout, stderr = self._run_mock_command(args, timeout=7200)  # 2 hours
        
        build_duration = int(time.time() - start_time)
        
        # Read detailed logs from Mock's result directory
        # Mock writes detailed logs to build.log and root.log files
        detailed_log = ""
        build_log_path = Path(output_dir) / "build.log"
        root_log_path = Path(output_dir) / "root.log"
        
        logger.info(f"Checking for Mock logs in: {output_dir}")
        logger.info(f"build.log exists: {build_log_path.exists()}")
        logger.info(f"root.log exists: {root_log_path.exists()}")
        
        # List all files in the output directory for debugging
        try:
            output_path = Path(output_dir)
            if output_path.exists():
                files = list(output_path.iterdir())
                logger.info(f"Files in output dir: {[f.name for f in files]}")
        except Exception as e:
            logger.warning(f"Could not list output directory: {e}")
        
        if build_log_path.exists():
            try:
                with open(build_log_path, 'r', encoding='utf-8', errors='replace') as f:
                    build_log_content = f.read()
                    detailed_log += f"=== Mock Build Log ({len(build_log_content)} bytes) ===\n{build_log_content}\n\n"
                    logger.info(f"Read build.log: {len(build_log_content)} bytes")
            except Exception as e:
                logger.warning(f"Could not read build.log: {e}")
        else:
            logger.warning(f"build.log not found at {build_log_path}")
        
        if root_log_path.exists():
            try:
                with open(root_log_path, 'r', encoding='utf-8', errors='replace') as f:
                    root_log_content = f.read()
                    detailed_log += f"=== Mock Root Log ({len(root_log_content)} bytes) ===\n{root_log_content}\n\n"
                    logger.info(f"Read root.log: {len(root_log_content)} bytes")
            except Exception as e:
                logger.warning(f"Could not read root.log: {e}")
        else:
            logger.warning(f"root.log not found at {root_log_path}")
        
        # Combine stdout/stderr with detailed logs
        log_output = f"=== Mock Command Output ===\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}\n\n{detailed_log}"
        
        if returncode == 0:
            # Find built RPMs (exclude SRPM)
            rpm_files = [
                str(f) for f in Path(output_dir).glob('*.rpm')
                if not f.name.endswith('.src.rpm')
            ]
            
            return BuildResult(
                success=True,
                rpm_paths=rpm_files,
                log_output=log_output,
                build_duration=build_duration
            )
        else:
            return BuildResult(
                success=False,
                error_message=f"Mock build failed with code {returncode}",
                log_output=log_output,
                build_duration=build_duration
            )
    
    def clean_buildroot(self, target: str, arch: str) -> bool:
        """Clean mock buildroot"""
        args = [
            '-r', target,
            '--arch', arch,
            '--clean',
        ]
        
        returncode, _, _ = self._run_mock_command(args, timeout=300)
        return returncode == 0
    
    def get_mock_config_path(self, target: str) -> Optional[str]:
        """Get path to mock configuration file"""
        config_file = Path(self.mock_config_dir) / f"{target}.cfg"
        if config_file.exists():
            return str(config_file)
        return None
