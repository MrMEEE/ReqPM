"""
Repository manager plugins package
"""
from .base import BaseRepositoryManager, RepositoryInfo
from .createrepo import CreateRepoManager
from typing import Optional

__all__ = ['BaseRepositoryManager', 'RepositoryInfo', 'get_repository_manager', 'list_repository_managers']

# Registry of available repository managers
_REPO_MANAGERS = {
    'createrepo': CreateRepoManager,
    'createrepo_c': CreateRepoManager,  # Alias
}


def get_repository_manager(name: str) -> Optional[BaseRepositoryManager]:
    """
    Get a repository manager instance by name
    
    Args:
        name: Name of the repository manager (e.g., 'createrepo')
    
    Returns:
        Repository manager instance or None
    """
    manager_class = _REPO_MANAGERS.get(name.lower())
    if manager_class:
        return manager_class()
    return None


def list_repository_managers() -> list:
    """
    List all available repository managers
    
    Returns:
        List of repository manager names
    """
    return list(_REPO_MANAGERS.keys())
