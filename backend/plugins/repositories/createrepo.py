"""
createrepo_c repository manager plugin
"""
import os
import subprocess
import shutil
from pathlib import Path
from typing import Dict, List, Optional
from .base import BaseRepositoryManager, RepositoryInfo
import logging
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)


class CreateRepoManager(BaseRepositoryManager):
    """
    createrepo_c-based repository manager
    
    Uses createrepo_c to create and manage YUM/DNF repositories
    """
    
    def __init__(self, config: Dict):
        super().__init__(config)
        self.createrepo_bin = self._find_createrepo_binary()
    
    @property
    def name(self) -> str:
        return "createrepo_c"
    
    @property
    def version(self) -> str:
        """Get createrepo_c version"""
        try:
            result = subprocess.run(
                [self.createrepo_bin, '--version'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                # Parse version from output
                version_line = result.stdout.strip().split('\n')[0]
                return version_line
        except Exception:
            pass
        return "unknown"
    
    def _find_createrepo_binary(self) -> str:
        """Find createrepo_c binary path"""
        for path in ['/usr/bin/createrepo_c', '/usr/bin/createrepo', '/usr/local/bin/createrepo_c']:
            if os.path.exists(path) and os.access(path, os.X_OK):
                return path
        return 'createrepo_c'
    
    def is_available(self) -> bool:
        """Check if createrepo_c is installed"""
        try:
            result = subprocess.run(
                [self.createrepo_bin, '--version'],
                capture_output=True,
                timeout=10
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"createrepo_c not available: {e}")
            return False
    
    def create_repository(
        self,
        repo_path: str,
        **kwargs
    ) -> bool:
        """Create a new repository using createrepo_c"""
        try:
            # Create directory if it doesn't exist
            Path(repo_path).mkdir(parents=True, exist_ok=True)
            
            # Run createrepo_c
            cmd = [self.createrepo_bin, repo_path]
            
            # Add optional arguments
            if kwargs.get('checksum'):
                cmd.extend(['--checksum', kwargs['checksum']])
            
            if kwargs.get('compress_type'):
                cmd.extend(['--compress-type', kwargs['compress_type']])
            
            if kwargs.get('workers'):
                cmd.extend(['--workers', str(kwargs['workers'])])
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600
            )
            
            if result.returncode == 0:
                logger.info(f"Repository created successfully at {repo_path}")
                return True
            else:
                logger.error(f"Failed to create repository: {result.stderr}")
                return False
        
        except Exception as e:
            logger.error(f"Error creating repository: {e}")
            return False
    
    def update_repository(
        self,
        repo_path: str,
        **kwargs
    ) -> bool:
        """Update repository metadata"""
        try:
            # Run createrepo_c with --update
            cmd = [self.createrepo_bin, '--update', repo_path]
            
            # Add optional arguments
            if kwargs.get('checksum'):
                cmd.extend(['--checksum', kwargs['checksum']])
            
            if kwargs.get('workers'):
                cmd.extend(['--workers', str(kwargs['workers'])])
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600
            )
            
            if result.returncode == 0:
                logger.info(f"Repository updated successfully at {repo_path}")
                return True
            else:
                logger.error(f"Failed to update repository: {result.stderr}")
                return False
        
        except Exception as e:
            logger.error(f"Error updating repository: {e}")
            return False
    
    def add_package(
        self,
        repo_path: str,
        package_path: str,
        **kwargs
    ) -> bool:
        """Add a package to the repository"""
        try:
            # Copy package to repository
            dest_path = Path(repo_path) / Path(package_path).name
            shutil.copy2(package_path, dest_path)
            
            # Update repository metadata
            return self.update_repository(repo_path, **kwargs)
        
        except Exception as e:
            logger.error(f"Error adding package: {e}")
            return False
    
    def remove_package(
        self,
        repo_path: str,
        package_name: str,
        **kwargs
    ) -> bool:
        """Remove a package from the repository"""
        try:
            # Find and remove the package file
            repo = Path(repo_path)
            removed = False
            
            for rpm_file in repo.glob(f"{package_name}*.rpm"):
                rpm_file.unlink()
                removed = True
                logger.info(f"Removed package: {rpm_file.name}")
            
            if not removed:
                logger.warning(f"Package {package_name} not found in repository")
                return False
            
            # Update repository metadata
            return self.update_repository(repo_path, **kwargs)
        
        except Exception as e:
            logger.error(f"Error removing package: {e}")
            return False
    
    def get_repository_info(
        self,
        repo_path: str
    ) -> Optional[RepositoryInfo]:
        """Get repository information"""
        try:
            repo = Path(repo_path)
            if not repo.exists():
                return None
            
            # Count packages
            package_count = len(list(repo.glob('*.rpm')))
            
            # Get repository size
            size_bytes = sum(f.stat().st_size for f in repo.rglob('*') if f.is_file())
            
            # Get last update time from repomd.xml
            repomd_path = repo / 'repodata' / 'repomd.xml'
            last_updated = None
            
            if repomd_path.exists():
                try:
                    tree = ET.parse(repomd_path)
                    root = tree.getroot()
                    # Extract timestamp from repomd.xml
                    ns = {'repo': 'http://linux.duke.edu/metadata/repo'}
                    revision = root.find('.//repo:revision', ns)
                    if revision is not None:
                        last_updated = revision.text
                except Exception as e:
                    logger.warning(f"Could not parse repomd.xml: {e}")
            
            return RepositoryInfo(
                name=repo.name,
                path=str(repo),
                package_count=package_count,
                last_updated=last_updated,
                size_bytes=size_bytes
            )
        
        except Exception as e:
            logger.error(f"Error getting repository info: {e}")
            return None
    
    def list_packages(
        self,
        repo_path: str
    ) -> List[Dict[str, str]]:
        """List all packages in the repository"""
        packages = []
        try:
            repo = Path(repo_path)
            
            for rpm_file in repo.glob('*.rpm'):
                # Parse RPM filename (simple approach)
                # Format: name-version-release.arch.rpm
                name_parts = rpm_file.stem.rsplit('-', 2)
                
                if len(name_parts) == 3:
                    packages.append({
                        'name': name_parts[0],
                        'version': name_parts[1],
                        'release': name_parts[2].split('.')[0],
                        'arch': name_parts[2].split('.')[-1] if '.' in name_parts[2] else 'noarch',
                        'filename': rpm_file.name,
                        'path': str(rpm_file),
                        'size': rpm_file.stat().st_size
                    })
        
        except Exception as e:
            logger.error(f"Error listing packages: {e}")
        
        return packages
    
    def sign_repository(
        self,
        repo_path: str,
        gpg_key: str,
        **kwargs
    ) -> bool:
        """
        Sign repository packages with GPG
        
        Note: This requires rpmsign to be installed
        """
        try:
            repo = Path(repo_path)
            
            for rpm_file in repo.glob('*.rpm'):
                # Sign each RPM
                cmd = [
                    'rpmsign',
                    '--addsign',
                    '--key-id', gpg_key,
                    str(rpm_file)
                ]
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                
                if result.returncode != 0:
                    logger.error(f"Failed to sign {rpm_file.name}: {result.stderr}")
                    return False
            
            # Update repository metadata after signing
            return self.update_repository(repo_path, **kwargs)
        
        except Exception as e:
            logger.error(f"Error signing repository: {e}")
            return False
