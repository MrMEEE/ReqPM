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
