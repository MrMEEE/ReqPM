"""
Requirements file parser and dependency analyzer
"""
import re
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class Requirement:
    """Represents a Python package requirement"""
    name: str
    specs: List[Tuple[str, str]]  # List of (operator, version) tuples
    extras: List[str]
    markers: Optional[str] = None
    original_line: str = ""
    
    def __str__(self):
        spec_str = ','.join([f"{op}{ver}" for op, ver in self.specs])
        extras_str = f"[{','.join(self.extras)}]" if self.extras else ""
        return f"{self.name}{extras_str}{spec_str}"
    
    @property
    def version_spec(self):
        """Get version specification string"""
        if not self.specs:
            return ""
        return ','.join([f"{op}{ver}" for op, ver in self.specs])


class RequirementsParser:
    """Parser for Python requirements files"""
    
    # Regex patterns
    REQUIREMENT_PATTERN = re.compile(
        r'^([a-zA-Z0-9][a-zA-Z0-9._-]*)'  # package name
        r'(?:\[([a-zA-Z0-9,._-]+)\])?'     # optional extras
        r'((?:[<>=!~]+[0-9a-zA-Z.*+!]+(?:,[<>=!~]+[0-9a-zA-Z.*+!]+)*)?)'  # version specs
        r'(?:\s*;\s*(.*))?'                 # optional markers
    )
    
    SPEC_PATTERN = re.compile(r'([<>=!~]+)([0-9a-zA-Z.*+!]+)')
    
    def parse_file(self, file_path: str) -> List[Requirement]:
        """
        Parse a requirements file
        
        Args:
            file_path: Path to requirements.txt file
        
        Returns:
            List of Requirement objects
        """
        requirements = []
        
        try:
            with open(file_path, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    
                    # Skip empty lines and comments
                    if not line or line.startswith('#'):
                        continue
                    
                    # Skip URLs and VCS requirements for now
                    if any(line.startswith(prefix) for prefix in ['http://', 'https://', 'git+', 'hg+', 'svn+', 'bzr+']):
                        logger.warning(f"Skipping URL/VCS requirement: {line}")
                        continue
                    
                    # Skip editable installs
                    if line.startswith('-e'):
                        logger.warning(f"Skipping editable install: {line}")
                        continue
                    
                    # Parse requirement
                    req = self.parse_requirement(line)
                    if req:
                        requirements.append(req)
                    else:
                        logger.warning(f"Could not parse requirement on line {line_num}: {line}")
        
        except Exception as e:
            logger.error(f"Error parsing requirements file {file_path}: {e}")
        
        return requirements
    
    def parse_requirement(self, line: str) -> Optional[Requirement]:
        """
        Parse a single requirement line
        
        Args:
            line: Requirement specification line
        
        Returns:
            Requirement object or None
        """
        try:
            # Remove inline comments
            if '#' in line:
                line = line.split('#')[0].strip()
            
            match = self.REQUIREMENT_PATTERN.match(line)
            if not match:
                return None
            
            name = match.group(1)
            extras_str = match.group(2) or ""
            specs_str = match.group(3) or ""
            markers = match.group(4)
            
            # Parse extras
            extras = [e.strip() for e in extras_str.split(',')] if extras_str else []
            
            # Parse version specs
            specs = []
            if specs_str:
                for spec_match in self.SPEC_PATTERN.finditer(specs_str):
                    operator = spec_match.group(1)
                    version = spec_match.group(2)
                    specs.append((operator, version))
            
            return Requirement(
                name=name,
                specs=specs,
                extras=extras,
                markers=markers,
                original_line=line
            )
        
        except Exception as e:
            logger.error(f"Error parsing requirement '{line}': {e}")
            return None
    
    def parse_string(self, requirements_str: str) -> List[Requirement]:
        """
        Parse requirements from a string
        
        Args:
            requirements_str: String containing requirements
        
        Returns:
            List of Requirement objects
        """
        requirements = []
        
        for line in requirements_str.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            req = self.parse_requirement(line)
            if req:
                requirements.append(req)
        
        return requirements


class DependencyResolver:
    """Resolves Python package dependencies"""
    
    def __init__(self):
        self.parser = RequirementsParser()
    
    def build_dependency_tree(
        self,
        requirements: List[Requirement]
    ) -> Dict[str, List[str]]:
        """
        Build a dependency tree from requirements
        
        Note: This is a simplified version. In production, you would
        query PyPI or use pip's resolver to get actual dependencies.
        
        Args:
            requirements: List of requirements
        
        Returns:
            Dictionary mapping package names to their dependencies
        """
        # This is a placeholder. In a real implementation, you would:
        # 1. Query PyPI API for each package
        # 2. Get its dependencies
        # 3. Recursively resolve all dependencies
        # 4. Build the complete dependency tree
        
        tree = {}
        for req in requirements:
            tree[req.name] = []  # Placeholder
        
        return tree
    
    def calculate_build_order(
        self,
        dependency_tree: Dict[str, List[str]]
    ) -> List[List[str]]:
        """
        Calculate build order based on dependency tree
        Uses topological sorting to determine the correct build order
        
        Args:
            dependency_tree: Dictionary mapping packages to their dependencies
        
        Returns:
            List of lists, where each inner list contains packages
            that can be built in parallel (same dependency level)
        """
        # Calculate in-degree for each package
        in_degree = {pkg: 0 for pkg in dependency_tree}
        
        for pkg, deps in dependency_tree.items():
            for dep in deps:
                if dep in in_degree:
                    in_degree[dep] += 1
        
        # Build levels
        levels = []
        remaining = set(dependency_tree.keys())
        
        while remaining:
            # Find packages with no dependencies in current level
            current_level = [
                pkg for pkg in remaining
                if in_degree[pkg] == 0
            ]
            
            if not current_level:
                # Circular dependency detected
                logger.error("Circular dependency detected!")
                levels.append(list(remaining))
                break
            
            levels.append(current_level)
            
            # Remove current level packages and update in-degrees
            for pkg in current_level:
                remaining.remove(pkg)
                for dep_pkg, deps in dependency_tree.items():
                    if pkg in deps:
                        in_degree[dep_pkg] -= 1
        
        return levels
    
    def normalize_package_name(self, name: str) -> str:
        """
        Normalize package name to RPM format
        
        Args:
            name: Python package name
        
        Returns:
            RPM package name
        """
        # Convert to lowercase and replace underscores/dots with hyphens
        normalized = name.lower().replace('_', '-').replace('.', '-')
        return f"python3-{normalized}"
