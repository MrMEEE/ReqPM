"""
GPG Key Manager - Manages distribution GPG keys for Mock builds

This module automatically downloads and updates GPG keys from the
distribution-gpg-keys repository to prevent build failures due to
outdated or incorrect GPG keys.

Repository: https://github.com/rpm-software-management/distribution-gpg-keys
"""
import os
import logging
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class GPGKeyManager:
    """
    Manages GPG keys for RPM distributions
    
    Automatically downloads and updates GPG keys from the official
    distribution-gpg-keys repository to ensure builds don't fail due
    to GPG key mismatches.
    """
    
    DISTRIBUTION_GPG_KEYS_REPO = "https://github.com/rpm-software-management/distribution-gpg-keys.git"
    DISTRIBUTION_GPG_KEYS_DIR = "/usr/share/distribution-gpg-keys"
    
    def __init__(self, cache_dir: Optional[str] = None):
        """
        Initialize GPG Key Manager
        
        Args:
            cache_dir: Directory to cache the distribution-gpg-keys repo
        """
        self.cache_dir = cache_dir or "/var/cache/reqpm/distribution-gpg-keys"
        self.keys_dir = Path(self.cache_dir) / "keys"
        self.repo_dir = Path(self.cache_dir) / "repo"
        
        # Ensure cache directory exists
        Path(self.cache_dir).mkdir(parents=True, exist_ok=True)
    
    def is_update_needed(self, force: bool = False, max_age_days: int = 7) -> bool:
        """
        Check if GPG keys need to be updated
        
        Args:
            force: Force update regardless of cache age
            max_age_days: Maximum age of cache in days before update
            
        Returns:
            True if update is needed
        """
        if force:
            return True
        
        # Check if keys directory exists and has content
        if not self.keys_dir.exists() or not list(self.keys_dir.glob('*')):
            logger.info("GPG keys cache is empty, update needed")
            return True
        
        # Check last update timestamp
        timestamp_file = Path(self.cache_dir) / ".last_update"
        if not timestamp_file.exists():
            logger.info("No update timestamp found, update needed")
            return True
        
        try:
            with open(timestamp_file, 'r') as f:
                last_update = datetime.fromisoformat(f.read().strip())
            
            age = datetime.now() - last_update
            if age > timedelta(days=max_age_days):
                logger.info(f"GPG keys cache is {age.days} days old, update needed")
                return True
            
            logger.debug(f"GPG keys cache is {age.days} days old, no update needed")
            return False
            
        except Exception as e:
            logger.warning(f"Error checking update timestamp: {e}")
            return True
    
    def update_keys(self, force: bool = False) -> Tuple[bool, str]:
        """
        Update GPG keys from distribution-gpg-keys repository
        
        Args:
            force: Force update even if cache is recent
            
        Returns:
            Tuple of (success, message)
        """
        if not force and not self.is_update_needed():
            return True, "GPG keys are up to date"
        
        logger.info("Updating GPG keys from distribution-gpg-keys repository")
        
        try:
            # Clone or update repository
            if not self._update_repository():
                return False, "Failed to clone/update distribution-gpg-keys repository"
            
            # Copy keys to cache
            if not self._copy_keys_to_cache():
                return False, "Failed to copy keys to cache"
            
            # Update system keys
            if not self._update_system_keys():
                return False, "Failed to update system keys"
            
            # Update timestamp
            timestamp_file = Path(self.cache_dir) / ".last_update"
            with open(timestamp_file, 'w') as f:
                f.write(datetime.now().isoformat())
            
            logger.info("Successfully updated GPG keys")
            return True, "GPG keys updated successfully"
            
        except Exception as e:
            error_msg = f"Error updating GPG keys: {e}"
            logger.error(error_msg)
            return False, error_msg
    
    def _update_repository(self) -> bool:
        """
        Clone or update the distribution-gpg-keys repository
        
        Returns:
            True if successful
        """
        try:
            if self.repo_dir.exists():
                logger.info(f"Updating existing repository at {self.repo_dir}")
                result = subprocess.run(
                    ['git', 'pull', '--ff-only'],
                    cwd=self.repo_dir,
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                
                if result.returncode != 0:
                    logger.warning(f"Git pull failed, trying fresh clone: {result.stderr}")
                    shutil.rmtree(self.repo_dir)
                    return self._clone_repository()
                
                logger.info("Repository updated successfully")
                return True
            else:
                return self._clone_repository()
                
        except Exception as e:
            logger.error(f"Error updating repository: {e}")
            return False
    
    def _clone_repository(self) -> bool:
        """
        Clone the distribution-gpg-keys repository
        
        Returns:
            True if successful
        """
        try:
            logger.info(f"Cloning distribution-gpg-keys to {self.repo_dir}")
            
            # Ensure parent directory exists
            self.repo_dir.parent.mkdir(parents=True, exist_ok=True)
            
            result = subprocess.run(
                ['git', 'clone', '--depth', '1', self.DISTRIBUTION_GPG_KEYS_REPO, str(self.repo_dir)],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if result.returncode != 0:
                logger.error(f"Git clone failed: {result.stderr}")
                return False
            
            logger.info("Repository cloned successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error cloning repository: {e}")
            return False
    
    def _copy_keys_to_cache(self) -> bool:
        """
        Copy GPG keys from repository to cache directory
        
        Returns:
            True if successful
        """
        try:
            # Find keys in the repository
            keys_source = self.repo_dir / "keys"
            
            if not keys_source.exists():
                logger.error(f"Keys directory not found in repository: {keys_source}")
                return False
            
            # Create cache keys directory
            self.keys_dir.mkdir(parents=True, exist_ok=True)
            
            # Copy all keys
            logger.info(f"Copying keys from {keys_source} to {self.keys_dir}")
            
            # Remove old keys
            if self.keys_dir.exists():
                shutil.rmtree(self.keys_dir)
            
            # Copy new keys
            shutil.copytree(keys_source, self.keys_dir)
            
            key_count = len(list(self.keys_dir.rglob('*')))
            logger.info(f"Copied {key_count} key files to cache")
            return True
            
        except Exception as e:
            logger.error(f"Error copying keys to cache: {e}")
            return False
    
    def _update_system_keys(self) -> bool:
        """
        Update system GPG keys directory
        
        Returns:
            True if successful
        """
        try:
            # Check if we need sudo privileges
            if not os.access(self.DISTRIBUTION_GPG_KEYS_DIR, os.W_OK):
                logger.info(f"Using sudo to update system keys at {self.DISTRIBUTION_GPG_KEYS_DIR}")
                
                # Create backup
                backup_dir = f"{self.DISTRIBUTION_GPG_KEYS_DIR}.backup.{datetime.now().strftime('%Y%m%d%H%M%S')}"
                if Path(self.DISTRIBUTION_GPG_KEYS_DIR).exists():
                    result = subprocess.run(
                        ['sudo', 'cp', '-a', self.DISTRIBUTION_GPG_KEYS_DIR, backup_dir],
                        capture_output=True,
                        text=True,
                        timeout=60
                    )
                    
                    if result.returncode != 0:
                        logger.warning(f"Failed to create backup: {result.stderr}")
                
                # Update system keys
                result = subprocess.run(
                    ['sudo', 'rsync', '-av', '--delete', 
                     str(self.keys_dir) + '/',
                     self.DISTRIBUTION_GPG_KEYS_DIR + '/'],
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                
                if result.returncode != 0:
                    logger.error(f"Failed to update system keys: {result.stderr}")
                    return False
                
                logger.info(f"System keys updated successfully at {self.DISTRIBUTION_GPG_KEYS_DIR}")
                return True
            else:
                # We have write access, copy directly
                logger.info(f"Updating system keys at {self.DISTRIBUTION_GPG_KEYS_DIR}")
                
                # Create backup
                if Path(self.DISTRIBUTION_GPG_KEYS_DIR).exists():
                    backup_dir = f"{self.DISTRIBUTION_GPG_KEYS_DIR}.backup.{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    shutil.copytree(self.DISTRIBUTION_GPG_KEYS_DIR, backup_dir)
                
                # Update keys
                if Path(self.DISTRIBUTION_GPG_KEYS_DIR).exists():
                    shutil.rmtree(self.DISTRIBUTION_GPG_KEYS_DIR)
                
                shutil.copytree(self.keys_dir, self.DISTRIBUTION_GPG_KEYS_DIR)
                
                logger.info("System keys updated successfully")
                return True
                
        except Exception as e:
            logger.error(f"Error updating system keys: {e}")
            return False
    
    def get_key_info(self, distribution: str = "redhat") -> Dict[str, any]:
        """
        Get information about available keys for a distribution
        
        Args:
            distribution: Distribution name (e.g., 'redhat', 'centos', 'fedora')
            
        Returns:
            Dictionary with key information
        """
        info = {
            'distribution': distribution,
            'keys': [],
            'cache_age': None,
            'cache_exists': False
        }
        
        try:
            # Check cache age
            timestamp_file = Path(self.cache_dir) / ".last_update"
            if timestamp_file.exists():
                with open(timestamp_file, 'r') as f:
                    last_update = datetime.fromisoformat(f.read().strip())
                    info['cache_age'] = (datetime.now() - last_update).days
                    info['cache_exists'] = True
            
            # List keys for distribution
            dist_keys_dir = self.keys_dir / distribution
            if dist_keys_dir.exists():
                for key_file in dist_keys_dir.glob('RPM-GPG-KEY-*'):
                    key_info = {
                        'name': key_file.name,
                        'path': str(key_file),
                        'size': key_file.stat().st_size,
                        'modified': datetime.fromtimestamp(key_file.stat().st_mtime).isoformat()
                    }
                    info['keys'].append(key_info)
            
        except Exception as e:
            logger.error(f"Error getting key info: {e}")
        
        return info
    
    def verify_keys_installed(self) -> Tuple[bool, str]:
        """
        Verify that GPG keys are properly installed
        
        Returns:
            Tuple of (success, message)
        """
        try:
            system_keys_dir = Path(self.DISTRIBUTION_GPG_KEYS_DIR)
            
            if not system_keys_dir.exists():
                return False, f"System keys directory not found: {system_keys_dir}"
            
            # Check for Red Hat keys
            redhat_keys = list(system_keys_dir.glob('redhat/RPM-GPG-KEY-*'))
            
            if not redhat_keys:
                return False, "No Red Hat GPG keys found in system directory"
            
            logger.info(f"Found {len(redhat_keys)} Red Hat GPG keys")
            return True, f"Found {len(redhat_keys)} Red Hat GPG keys"
            
        except Exception as e:
            error_msg = f"Error verifying keys: {e}"
            logger.error(error_msg)
            return False, error_msg


def get_gpg_key_manager(cache_dir: Optional[str] = None) -> GPGKeyManager:
    """
    Factory function to get a GPG Key Manager instance
    
    Args:
        cache_dir: Optional cache directory
        
    Returns:
        GPGKeyManager instance
    """
    return GPGKeyManager(cache_dir=cache_dir)
