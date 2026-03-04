"""
PyPI metadata fetcher and analyzer
"""
import json
import re
import tarfile
import urllib.request
import urllib.error
from typing import Dict, List, Optional, Set
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class PackageInfo:
    """Information about a Python package"""
    name: str
    version: str
    summary: str
    description: str
    license: str
    home_page: str
    author: str
    author_email: str
    requires_python: Optional[str]
    requires_dist: List[str]
    classifiers: List[str]
    download_url: str
    source_url: Optional[str]
    
    @property
    def runtime_dependencies(self) -> List[str]:
        """Get runtime dependencies only"""
        deps = []
        for req in self.requires_dist:
            # Skip test/dev/docs dependencies
            if any(marker in req.lower() for marker in ['extra == "test"', 'extra == "dev"', 'extra == "docs"']):
                continue
            deps.append(req)
        return deps


class PyPIClient:
    """Client for interacting with PyPI API"""
    
    BASE_URL = "https://pypi.org/pypi"
    
    def __init__(self, timeout: int = 10):
        """
        Initialize PyPI client
        
        Args:
            timeout: Request timeout in seconds
        """
        self.timeout = timeout
    
    def get_package_info(
        self,
        package_name: str,
        version: Optional[str] = None
    ) -> Optional[PackageInfo]:
        """
        Get package information from PyPI
        
        Args:
            package_name: Name of the package
            version: Specific version (None for latest)
        
        Returns:
            PackageInfo object or None
        """
        try:
            metadata = self._fetch_metadata(package_name, version)
            if not metadata:
                return None
            
            info = metadata.get('info', {})
            urls = metadata.get('urls', [])
            
            # Find source distribution URL
            source_url = None
            for url_info in urls:
                if url_info.get('packagetype') == 'sdist':
                    source_url = url_info.get('url')
                    break
            
            # Fallback to first URL if no sdist found
            if not source_url and urls:
                source_url = urls[0].get('url')
            
            return PackageInfo(
                name=info.get('name', package_name),
                version=info.get('version', version or 'unknown'),
                summary=info.get('summary', ''),
                description=info.get('description', ''),
                license=info.get('license', 'Unknown'),
                home_page=info.get('home_page', ''),
                author=info.get('author', ''),
                author_email=info.get('author_email', ''),
                requires_python=info.get('requires_python'),
                requires_dist=info.get('requires_dist', []) or [],
                classifiers=info.get('classifiers', []),
                download_url=info.get('download_url', ''),
                source_url=source_url
            )
        
        except Exception as e:
            logger.error(f"Error getting package info for {package_name}: {e}")
            return None
    
    def get_all_versions(self, package_name: str) -> List[str]:
        """
        Get all available versions of a package
        
        Args:
            package_name: Name of the package
        
        Returns:
            List of version strings
        """
        try:
            metadata = self._fetch_metadata(package_name)
            if not metadata:
                return []
            
            releases = metadata.get('releases', {})
            return list(releases.keys())
        
        except Exception as e:
            logger.error(f"Error getting versions for {package_name}: {e}")
            return []
    
    def get_package_versions(self, package_name: str) -> List[str]:
        """
        Alias for get_all_versions for API consistency
        
        Args:
            package_name: Name of the package
        
        Returns:
            List of version strings
        """
        return self.get_all_versions(package_name)
    
    def get_latest_version(self, package_name: str) -> Optional[str]:
        """
        Get latest version of a package
        
        Args:
            package_name: Name of the package
        
        Returns:
            Version string or None
        """
        try:
            metadata = self._fetch_metadata(package_name)
            if not metadata:
                return None
            
            info = metadata.get('info', {})
            return info.get('version')
        
        except Exception as e:
            logger.error(f"Error getting latest version for {package_name}: {e}")
            return None
    
    def resolve_dependencies(
        self,
        package_name: str,
        version: Optional[str] = None,
        max_depth: int = 5,
        include_extras: bool = False
    ) -> Dict[str, Set[str]]:
        """
        Recursively resolve all dependencies of a package
        
        Args:
            package_name: Name of the package
            version: Specific version (None for latest)
            max_depth: Maximum recursion depth
            include_extras: Include extra dependencies
        
        Returns:
            Dictionary mapping package names to their direct dependencies
        """
        resolved = {}
        to_process = [(package_name, version, 0)]
        processed = set()
        
        while to_process:
            current_pkg, current_ver, depth = to_process.pop(0)
            
            # Skip if already processed
            key = f"{current_pkg}:{current_ver or 'latest'}"
            if key in processed:
                continue
            
            processed.add(key)
            
            # Skip if max depth reached
            if depth >= max_depth:
                logger.warning(f"Max depth reached for {current_pkg}")
                continue
            
            # Get package info
            pkg_info = self.get_package_info(current_pkg, current_ver)
            if not pkg_info:
                continue
            
            # Extract dependencies
            deps = set()
            for req in pkg_info.requires_dist:
                # Skip test/dev dependencies unless include_extras is True
                if not include_extras:
                    if any(marker in req.lower() for marker in ['extra ==', 'extra==']):
                        continue
                
                # Parse package name from requirement
                dep_name = self._parse_package_name(req)
                if dep_name and dep_name != current_pkg:
                    deps.add(dep_name)
                    to_process.append((dep_name, None, depth + 1))
            
            resolved[current_pkg] = deps
        
        return resolved
    
    def _fetch_metadata(
        self,
        package_name: str,
        version: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Fetch package metadata from PyPI
        
        Args:
            package_name: Name of the package
            version: Specific version (None for latest)
        
        Returns:
            Metadata dictionary or None
        """
        try:
            if version:
                url = f"{self.BASE_URL}/{package_name}/{version}/json"
            else:
                url = f"{self.BASE_URL}/{package_name}/json"
            
            with urllib.request.urlopen(url, timeout=self.timeout) as response:
                data = json.loads(response.read().decode())
                return data
        
        except urllib.error.HTTPError as e:
            if e.code == 404:
                logger.warning(f"Package not found: {package_name}")
            else:
                logger.error(f"HTTP error fetching {package_name}: {e.code} {e.reason}")
            return None
        except Exception as e:
            logger.error(f"Error fetching metadata for {package_name}: {e}")
            return None
    
    def _parse_package_name(self, requirement: str) -> Optional[str]:
        """
        Parse package name from requirement string
        
        Args:
            requirement: Requirement string (e.g., "requests>=2.0.0")
        
        Returns:
            Package name or None
        """
        import re
        match = re.match(r'^([a-zA-Z0-9][a-zA-Z0-9._-]*)', requirement)
        if match:
            return match.group(1)
        return None

    # -------------------------------------------------------------------------
    # Build system detection
    # -------------------------------------------------------------------------

    def detect_build_system(self, package_name: str, version: Optional[str] = None) -> str:
        """
        Detect the build system used by a Python package.
        Streams the sdist from PyPI and inspects pyproject.toml.

        Returns one of: 'unknown', 'setuptools', 'poetry', 'flit',
            'hatchling', 'pdm', 'meson', 'scikit-build', 'other-pyproject'
        """
        try:
            metadata = self._fetch_metadata(package_name, version)
            if not metadata:
                return 'unknown'

            # Find sdist URL from the release files
            urls = metadata.get('urls', [])
            sdist_url = None
            for url_info in urls:
                if url_info.get('packagetype') == 'sdist':
                    sdist_url = url_info.get('url')
                    break

            if not sdist_url:
                logger.warning(f"No sdist found for {package_name}, cannot detect build system")
                return 'unknown'

            return self._detect_from_sdist(sdist_url)

        except Exception as e:
            logger.error(f"Error detecting build system for {package_name}: {e}")
            return 'unknown'

    def _detect_from_sdist(self, sdist_url: str) -> str:
        """Stream partial sdist tarball to find and read pyproject.toml."""
        MAX_BYTES = 3 * 1024 * 1024  # 3 MB read limit

        class _LimitedStream:
            """Wraps a network stream and cuts off after MAX_BYTES are read."""
            def __init__(self, source):
                self.source = source
                self.total = 0

            def read(self, n=-1):
                if self.total >= MAX_BYTES:
                    return b''
                if n < 0:
                    n = MAX_BYTES - self.total
                n = min(n, MAX_BYTES - self.total)
                data = self.source.read(n)
                self.total += len(data)
                return data

        try:
            req = urllib.request.Request(
                sdist_url,
                headers={'User-Agent': 'ReqPM/1.0 build-detection'}
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                limited = _LimitedStream(response)

                if sdist_url.endswith(('.tar.gz', '.tgz')):
                    mode = 'r|gz'
                elif sdist_url.endswith('.tar.bz2'):
                    mode = 'r|bz2'
                elif sdist_url.endswith('.tar.xz'):
                    mode = 'r|xz'
                else:
                    # ZIP / wheel – not a tarball, give up
                    return 'unknown'

                found_setup_py = False
                found_setup_cfg = False

                try:
                    with tarfile.open(fileobj=limited, mode=mode) as tar:
                        for member in tar:
                            if not member.isfile():
                                continue
                            basename = member.name.split('/')[-1]

                            if basename == 'pyproject.toml':
                                f = tar.extractfile(member)
                                if f:
                                    content = f.read().decode('utf-8', errors='ignore')
                                    return self._detect_from_pyproject_content(content)
                            elif basename == 'setup.py':
                                found_setup_py = True
                            elif basename == 'setup.cfg':
                                found_setup_cfg = True

                except tarfile.ReadError:
                    # Hit the byte-read limit; use what we found so far
                    pass

                if found_setup_py or found_setup_cfg:
                    return 'setuptools'
                return 'unknown'

        except Exception as e:
            logger.warning(f"Could not detect build system from {sdist_url}: {e}")
            return 'unknown'

    def _detect_from_pyproject_content(self, content: str) -> str:
        """Parse pyproject.toml text and return the matching build-system label."""
        build_section_match = re.search(
            r'\[build-system\](.*?)(?=\n\[|\Z)',
            content,
            re.DOTALL
        )
        if not build_section_match:
            # pyproject.toml exists but has no [build-system] table
            return 'other-pyproject'

        section = build_section_match.group(1).lower()

        if 'poetry-core' in section or 'poetry.core.masonry' in section:
            return 'poetry'
        if 'flit-core' in section or 'flit_core' in section:
            return 'flit'
        if 'hatchling' in section:
            return 'hatchling'
        if 'pdm-backend' in section or 'pdm.pep517' in section or 'pdm-pep517' in section:
            return 'pdm'
        if 'meson' in section:
            return 'meson'
        if 'scikit-build-core' in section or 'scikit_build_core' in section:
            return 'scikit-build'
        if 'setuptools' in section:
            return 'setuptools'
        return 'other-pyproject'
