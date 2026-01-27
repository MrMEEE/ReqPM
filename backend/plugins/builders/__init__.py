"""
Builder plugins package
"""
from .base import BaseBuilder, BuildResult
from .mock import MockBuilder
from typing import Optional

__all__ = ['BaseBuilder', 'BuildResult', 'get_builder', 'list_builders']

# Registry of available builders
_BUILDERS = {
    'mock': MockBuilder,
}


def get_builder(name: str) -> Optional[BaseBuilder]:
    """
    Get a builder instance by name
    
    Args:
        name: Name of the builder (e.g., 'mock')
    
    Returns:
        Builder instance or None
    """
    from django.conf import settings
    
    builder_class = _BUILDERS.get(name.lower())
    if builder_class:
        return builder_class(settings)
    return None


def list_builders() -> list:
    """
    List all available builders
    
    Returns:
        List of builder names
    """
    return list(_BUILDERS.keys())
