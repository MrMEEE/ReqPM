"""
Base classes for builder plugins
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class BuildResult:
    """Result of a package build"""
    success: bool
    srpm_path: Optional[str] = None
    rpm_paths: List[str] = None
    log_output: str = ""
    error_message: str = ""
    build_duration: int = 0  # seconds
    
    def __post_init__(self):
        if self.rpm_paths is None:
            self.rpm_paths = []


class BaseBuilder(ABC):
    """
    Base class for all builder plugins
    
    Implement this class to create new build system plugins
    """
    
    def __init__(self, config: Dict):
        """
        Initialize the builder with configuration
        
        Args:
            config: Configuration dictionary from Django settings
        """
        self.config = config
        self.logger = logger
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Return the builder name"""
        pass
    
    @property
    @abstractmethod
    def version(self) -> str:
        """Return the builder version"""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if the builder is available on the system
        
        Returns:
            True if builder can be used, False otherwise
        """
        pass
    
    @abstractmethod
    def get_available_targets(self) -> List[str]:
        """
        Get list of available build targets (e.g., RHEL versions)
        
        Returns:
            List of available target identifiers
        """
        pass
    
    @abstractmethod
    def validate_target(self, target: str, arch: str = 'x86_64') -> bool:
        """
        Validate if a specific target and architecture is available
        
        Args:
            target: Build target (e.g., 'rhel-9')
            arch: Architecture (e.g., 'x86_64')
        
        Returns:
            True if target is valid and available
        """
        pass
    
    @abstractmethod
    def build_srpm(
        self,
        spec_file: str,
        sources_dir: str,
        output_dir: str,
        **kwargs
    ) -> BuildResult:
        """
        Build source RPM from spec file
        
        Args:
            spec_file: Path to the spec file
            sources_dir: Directory containing source files
            output_dir: Directory where SRPM should be saved
            **kwargs: Additional builder-specific options
        
        Returns:
            BuildResult object with build outcome
        """
        pass
    
    @abstractmethod
    def build_rpm(
        self,
        srpm_path: str,
        target: str,
        arch: str,
        output_dir: str,
        **kwargs
    ) -> BuildResult:
        """
        Build binary RPM from source RPM
        
        Args:
            srpm_path: Path to the source RPM
            target: Build target (e.g., 'rhel-9')
            arch: Architecture (e.g., 'x86_64')
            output_dir: Directory where RPMs should be saved
            **kwargs: Additional builder-specific options
        
        Returns:
            BuildResult object with build outcome
        """
        pass
    
    @abstractmethod
    def clean_buildroot(self, target: str, arch: str) -> bool:
        """
        Clean the build environment
        
        Args:
            target: Build target
            arch: Architecture
        
        Returns:
            True if cleanup successful
        """
        pass
    
    def get_build_dependencies(
        self,
        spec_file: str
    ) -> List[str]:
        """
        Extract build dependencies from spec file
        
        Args:
            spec_file: Path to the spec file
        
        Returns:
            List of build dependency package names
        """
        dependencies = []
        try:
            with open(spec_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('BuildRequires:'):
                        dep = line.split(':', 1)[1].strip()
                        dependencies.append(dep)
        except Exception as e:
            self.logger.error(f"Error reading dependencies from {spec_file}: {e}")
        
        return dependencies
    
    def validate_spec_file(self, spec_file: str) -> Tuple[bool, str]:
        """
        Validate a spec file
        
        Args:
            spec_file: Path to the spec file
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            with open(spec_file, 'r') as f:
                content = f.read()
                
            # Basic validation
            required_fields = ['Name:', 'Version:', 'Release:', '%description']
            missing = [field for field in required_fields if field not in content]
            
            if missing:
                return False, f"Missing required fields: {', '.join(missing)}"
            
            return True, ""
        except Exception as e:
            return False, str(e)
