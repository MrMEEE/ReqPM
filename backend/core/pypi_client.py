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


_CLASSIFIER_TO_SPDX = {
    'MIT License': 'MIT',
    'MIT': 'MIT',
    'Apache Software License': 'Apache-2.0',
    'BSD License': 'BSD-3-Clause',
    'BSD 2-Clause "Simplified" License': 'BSD-2-Clause',
    'BSD 3-Clause "New" or "Revised" License': 'BSD-3-Clause',
    'GNU General Public License v2 (GPLv2)': 'GPL-2.0-only',
    'GNU General Public License v2 or later (GPLv2+)': 'GPL-2.0-or-later',
    'GNU General Public License v3 (GPLv3)': 'GPL-3.0-only',
    'GNU General Public License v3 or later (GPLv3+)': 'GPL-3.0-or-later',
    'GNU Lesser General Public License v2 (LGPLv2)': 'LGPL-2.0-only',
    'GNU Lesser General Public License v2 or later (LGPLv2+)': 'LGPL-2.0-or-later',
    'GNU Lesser General Public License v3 (LGPLv3)': 'LGPL-3.0-only',
    'GNU Lesser General Public License v3 or later (LGPLv3+)': 'LGPL-3.0-or-later',
    'Mozilla Public License 2.0 (MPL 2.0)': 'MPL-2.0',
    'Mozilla Public License 1.1 (MPL 1.1)': 'MPL-1.1',
    'ISC License (ISCL)': 'ISC',
    'ISC': 'ISC',
    'Python Software Foundation License': 'PSF-2.0',
    'Creative Commons Attribution 4.0': 'CC-BY-4.0',
    'The Unlicense (Unlicense)': 'Unlicense',
    'Boost Software License 1.0 (BSL-1.0)': 'BSL-1.0',
    'Eclipse Public License 2.0 (EPL-2.0)': 'EPL-2.0',
    'Eclipse Public License 1.0 (EPL-1.0)': 'EPL-1.0',
    'European Union Public Licence 1.2 (EUPL 1.2)': 'EUPL-1.2',
    'Academic Free License (AFL)': 'AFL-3.0',
    'Artistic License': 'Artistic-2.0',
    'zlib/libpng License': 'Zlib',
    'OSI Approved': None,  # too vague
}

# Non-SPDX strings that appear in the `license` field of older packages.
_LICENSE_TEXT_TO_SPDX = {
    'mit': 'MIT',
    'apache-2.0': 'Apache-2.0',
    'apache 2.0': 'Apache-2.0',
    'apache software license': 'Apache-2.0',
    'bsd': 'BSD-3-Clause',
    'bsd-2-clause': 'BSD-2-Clause',
    'bsd-3-clause': 'BSD-3-Clause',
    'bsd 2-clause': 'BSD-2-Clause',
    'bsd 3-clause': 'BSD-3-Clause',
    'gpl': 'GPL-2.0-or-later',
    'gpl-2': 'GPL-2.0-only',
    'gpl-2.0': 'GPL-2.0-only',
    'gplv2': 'GPL-2.0-only',
    'gplv2+': 'GPL-2.0-or-later',
    'gpl-3': 'GPL-3.0-only',
    'gpl-3.0': 'GPL-3.0-only',
    'gplv3': 'GPL-3.0-only',
    'gplv3+': 'GPL-3.0-or-later',
    'lgpl': 'LGPL-2.1-or-later',
    'lgpl-2.1': 'LGPL-2.1-only',
    'lgpl-3.0': 'LGPL-3.0-only',
    'lgplv2': 'LGPL-2.0-only',
    'lgplv2+': 'LGPL-2.0-or-later',
    'lgplv3': 'LGPL-3.0-only',
    'lgplv3+': 'LGPL-3.0-or-laterly',
    'lgplv2': 'LGPL-2.0-only',
    'lgplv2+': 'LGPL-2.0-or-later',
    'lgplv3': 'LGPL-3.0-only',
    'lgplv3+': 'LGPL-3.0-or-laterly',
    'lgplv2': 'LGPL-2.0-only',
    'lgplv2+': 'LGPL-2.0-or-later',
    'lgplv3': 'LGPL-3.0-only',
    'lgplv3+': 'LGPL-3.0-or-later',
    'mpl-2.0': 'MPL-2.0',
    'mpl2': 'MPL-2.0',
    'isc': 'ISC',
    'psf': 'PSF-2.0',
    'psf-2.0': 'PSF-2.0',
    'python software foundation': 'PSF-2.0',
    'unlicense': 'Unlicense',
    'cc0': 'CC0-1.0',
    'cc0-1.0': 'CC0-1.0',
    'zlib': 'Zlib',
    'bsl-1.0': 'BSL-1.0',
    'epl-2.0': 'EPL-2.0',
    'epl-1.0': 'EPL-1.0',
    'eupl-1.2': 'EUPL-1.2',
    'artistic': 'Artistic-2.0',
    'artistic-2.0': 'Artistic-2.0',
    '2-clause bsd': 'BSD-2-Clause',
    '3-clause bsd': 'BSD-3-Clause',
    'new bsd': 'BSD-3-Clause',
    'modified bsd': 'BSD-3-Clause',
    'simplified bsd': 'BSD-2-Clause',
    'dual mit/bsd': 'MIT AND BSD-3-Clause',
    'mit/x11': 'MIT',
    'mit license': 'MIT',
    'the mit license': 'MIT',
    'mozilla public license 2.0': 'MPL-2.0',
    'mozilla public license 1.1': 'MPL-1.1',
    'gnu gpl': 'GPL-2.0-or-later',
    'gnu lgpl': 'LGPL-2.1-or-later',
}

# SPDX identifier regex: short token, no newlines, typical punctuation
_SPDX_RE = re.compile(
    r'^[A-Za-z][A-Za-z0-9.+\-]+(?:\s+(?:AND|OR|WITH)\s+[A-Za-z][A-Za-z0-9.+\-]+)*$'
)


def resolve_license_spdx(license_str: Optional[str],
                         license_expression: Optional[str],
                         classifiers: List[str]) -> str:
    """
    Return the best available SPDX license expression for a PyPI package.

    Resolution order:
    1. ``license_expression``  — already SPDX (PEP 639 compliant, new packages)
    2. ``license``             — may be SPDX-like or a freeform string
    3. ``classifiers``         — ``License :: OSI Approved :: X`` entries
    4. ``'Unknown'``           — fallback when nothing else works
    """
    # 1. license_expression — trust it immediately
    if license_expression and license_expression.strip():
        return license_expression.strip()

    # 2. license field normalization
    if license_str and license_str.strip():
        raw = license_str.strip()
        # Reject full-text license bodies (multi-line or very long)
        if '\n' not in raw and len(raw) <= 120:
            lower = raw.lower()
            # Direct map hit
            mapped = _LICENSE_TEXT_TO_SPDX.get(lower)
            if mapped:
                return mapped
            # Already looks like a valid SPDX expression
            if _SPDX_RE.match(raw):
                return raw

    # 3. Classifiers
    for c in classifiers:
        parts = [p.strip() for p in c.split('::')]
        if 'License' in parts and 'OSI Approved' in parts:
            leaf = parts[-1] if len(parts) > 2 else None
            if leaf:
                spdx = _CLASSIFIER_TO_SPDX.get(leaf)
                if spdx:
                    return spdx

    return 'Unknown'


@dataclass
class PackageInfo:
    """Information about a Python package"""
    name: str
    version: str
    summary: str
    description: str
    license: str
    license_expression: Optional[str]
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
        """Get mandatory runtime dependencies (no optional extras)."""
        deps = []
        for req in self.requires_dist:
            # Skip anything that is conditional on an extra being requested.
            # A bare `extra ==` anywhere in the marker means the dep is optional
            # and should not be included unless the caller explicitly installs
            # that extra (e.g. pip install pkg[speedups]).
            req_lower = req.lower()
            if 'extra ==' in req_lower or 'extra==' in req_lower:
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
            
            classifiers = info.get('classifiers', []) or []
            return PackageInfo(
                name=info.get('name', package_name),
                version=info.get('version', version or 'unknown'),
                summary=info.get('summary', ''),
                description=info.get('description', ''),
                license=resolve_license_spdx(
                    info.get('license'),
                    info.get('license_expression'),
                    classifiers,
                ),
                license_expression=info.get('license_expression'),
                home_page=info.get('home_page', ''),
                author=info.get('author', ''),
                author_email=info.get('author_email', ''),
                requires_python=info.get('requires_python'),
                requires_dist=info.get('requires_dist', []) or [],
                classifiers=classifiers,
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
