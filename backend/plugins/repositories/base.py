"""
Base classes for repository manager plugins
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class RepositoryInfo:
    """Information about a repository"""
    name: str
    path: str
    package_count: int
    last_updated: Optional[str] = None
    size_bytes: Optional[int] = None


class BaseRepositoryManager(ABC):
    """
    Base class for all repository manager plugins
    
    Implement this class to create new repository manager plugins
    """
    
    def __init__(self, config: Dict):
        """
        Initialize the repository manager with configuration
        
        Args:
            config: Configuration dictionary from Django settings
        """
        self.config = config
        self.logger = logger
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Return the repository manager name"""
        pass
    
    @property
    @abstractmethod
    def version(self) -> str:
        """Return the repository manager version"""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if the repository manager is available on the system
        
        Returns:
            True if manager can be used, False otherwise
        """
        pass
    
    @abstractmethod
    def create_repository(
        self,
        repo_path: str,
        **kwargs
    ) -> bool:
        """
        Create a new repository
        
        Args:
            repo_path: Path where repository should be created
            **kwargs: Additional repository-specific options
        
        Returns:
            True if repository was created successfully
        """
        pass
    
    @abstractmethod
    def update_repository(
        self,
        repo_path: str,
        **kwargs
    ) -> bool:
        """
        Update repository metadata
        
        Args:
            repo_path: Path to the repository
            **kwargs: Additional options
        
        Returns:
            True if update was successful
        """
        pass
    
    @abstractmethod
    def add_package(
        self,
        repo_path: str,
        package_path: str,
        **kwargs
    ) -> bool:
        """
        Add a package to the repository
        
        Args:
            repo_path: Path to the repository
            package_path: Path to the RPM package file
            **kwargs: Additional options
        
        Returns:
            True if package was added successfully
        """
        pass
    
    @abstractmethod
    def remove_package(
        self,
        repo_path: str,
        package_name: str,
        **kwargs
    ) -> bool:
        """
        Remove a package from the repository
        
        Args:
            repo_path: Path to the repository
            package_name: Name of the package to remove
            **kwargs: Additional options
        
        Returns:
            True if package was removed successfully
        """
        pass
    
    @abstractmethod
    def get_repository_info(
        self,
        repo_path: str
    ) -> Optional[RepositoryInfo]:
        """
        Get information about a repository
        
        Args:
            repo_path: Path to the repository
        
        Returns:
            RepositoryInfo object or None if repository doesn't exist
        """
        pass
    
    @abstractmethod
    def list_packages(
        self,
        repo_path: str
    ) -> List[Dict[str, str]]:
        """
        List all packages in the repository
        
        Args:
            repo_path: Path to the repository
        
        Returns:
            List of dictionaries with package information
        """
        pass
    
    @abstractmethod
    def sign_repository(
        self,
        repo_path: str,
        gpg_key: str,
        **kwargs
    ) -> bool:
        """
        Sign the repository with a GPG key
        
        Args:
            repo_path: Path to the repository
            gpg_key: GPG key ID or path
            **kwargs: Additional signing options
        
        Returns:
            True if signing was successful
        """
        pass
    
    def validate_repository(self, repo_path: str) -> bool:
        """
        Validate repository structure and metadata
        
        Args:
            repo_path: Path to the repository
        
        Returns:
            True if repository is valid
        """
        import os
        from pathlib import Path
        
        repo = Path(repo_path)
        if not repo.exists() or not repo.is_dir():
            return False
        
        # Check for repodata directory
        repodata = repo / 'repodata'
        return repodata.exists() and repodata.is_dir()
