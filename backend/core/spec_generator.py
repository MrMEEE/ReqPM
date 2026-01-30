"""
RPM Spec file generator using pyp2spec
Following the awx-rpm-v2 approach exactly
"""
import re
import subprocess
import tempfile
import os
from typing import Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class SpecFileGenerator:
    """Generates RPM spec files for Python packages using pyp2spec"""
    
    def __init__(self, packager_name: str = "ReqPM", packager_email: str = "reqpm@localhost"):
        """
        Initialize spec file generator
        
        Args:
            packager_name: Name of the packager
            packager_email: Email of the packager
        """
        self.packager_name = packager_name
        self.packager_email = packager_email
        self._check_pyp2spec()
    
    def _check_pyp2spec(self):
        """Check if pyp2spec is installed"""
        try:
            result = subprocess.run(['pyp2spec', '--help'], 
                                   capture_output=True, 
                                   text=True, 
                                   timeout=5)
            logger.info("pyp2spec is available")
        except FileNotFoundError:
            logger.warning("pyp2spec not found. Install with: pip install pyp2spec")
        except Exception as e:
            logger.warning(f"Could not check pyp2spec: {e}")
    
    def generate_spec(
        self,
        package_name: str,
        version: Optional[str] = None,
        python_version: str = "default",
        **kwargs
    ) -> str:
        """
        Generate RPM spec file for a Python package using pyp2spec
        Following awx-rpm-v2 approach: pyp2spec [-p PYTHONVERSION] --license gpl [-v VERSION] PACKAGE
        
        Args:
            package_name: Name of the Python package
            version: Specific version (None for latest)
            python_version: Python version (e.g., "3.11", "3.12", or "default" to omit -p flag)
            **kwargs: Additional arguments (ignored for compatibility)
        
        Returns:
            Spec file content as string
        """
        logger.info(f"Generating spec for {package_name} using pyp2spec")
        
        # Build pyp2spec command like awx-rpm-v2:
        # pyp2spec [-p PYTHONVERSION] --license gpl [-v VERSION] PACKAGE
        cmd = ['pyp2spec']
        
        # Only add -p flag if python_version is not "default"
        if python_version and python_version != "default":
            cmd.extend(['-p', python_version])
            logger.info(f"Using Python version: {python_version}")
        else:
            logger.info(f"Using default Python version (no -p flag)")
        
        cmd.extend(['--license', 'gpl'])
        
        if version:
            cmd.extend(['-v', version])
            logger.info(f"Generating spec for {package_name} version {version}")
        else:
            logger.info(f"Generating spec for {package_name} (latest version)")
        
        cmd.append(package_name)
        
        try:
            # Run pyp2spec and capture stdout (it prints to stdout by default)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode != 0:
                logger.error(f"pyp2spec failed for {package_name}: {result.stderr}")
                return self._generate_fallback_spec(package_name, version, python_version)
            
            # pyp2spec prints the spec to stdout by default
            spec_content = result.stdout
            
            if not spec_content or len(spec_content.strip()) == 0:
                logger.error(f"No spec content generated for {package_name}")
                return self._generate_fallback_spec(package_name, version, python_version)
            
            logger.info(f"Successfully generated spec for {package_name}")
            
            # Post-process the spec file
            spec_content = self._post_process_spec(spec_content, package_name, version)
            
            return spec_content
            
        except subprocess.TimeoutExpired:
            logger.error(f"pyp2spec timed out for {package_name}")
            return self._generate_fallback_spec(package_name, version, python_version)
        except Exception as e:
            logger.error(f"Error generating spec for {package_name}: {e}")
            return self._generate_fallback_spec(package_name, version, python_version)
    
    def _post_process_spec(self, spec_content: str, package_name: str, version: Optional[str]) -> str:
        """
        Post-process the generated spec file
        
        Args:
            spec_content: Generated spec content
            package_name: Package name
            version: Package version
        
        Returns:
            Post-processed spec content
        """
        # Fix rich boolean dependencies from pyp2rpm
        # Convert: (python3dist(pkg) >= 1 with python3dist(pkg) < 3~~)
        # To: python3dist(pkg) >= 1
        spec_content = re.sub(
            r'\(python3dist\(([^)]+)\)\s+([><=!]+\s+[^\s)]+)(?:\s+with\s+[^)]+)?\)',
            r'python3dist(\1) \2',
            spec_content
        )
        
        # Add packager information if not present
        if '%changelog' in spec_content and 'ReqPM' not in spec_content:
            date = datetime.now().strftime("%a %b %d %Y")
            changelog_entry = f"* {date} {self.packager_name} <{self.packager_email}>\n- Generated by ReqPM\n\n"
            spec_content = re.sub(
                r'(%changelog\n)',
                f'\\1{changelog_entry}',
                spec_content
            )
        
        return spec_content
    
    def _generate_fallback_spec(self, package_name: str, version: Optional[str] = None, python_version: str = "3.11") -> str:
        """
        Generate a basic fallback spec file if pyp2spec fails
        
        Args:
            package_name: Package name
            version: Package version
            python_version: Python version for spec (or "default" to use system default)
        
        Returns:
            Basic spec file content
        """
        logger.warning(f"Using fallback spec generation for {package_name}")
        
        rpm_name = self._normalize_package_name(package_name)
        version = version or "0.0.1"
        date = datetime.now().strftime("%a %b %d %Y")
        
        # Determine Python version suffix (empty for "default")
        py_suffix = "" if python_version == "default" else python_version
        py_macro = "3" if python_version == "default" else python_version.replace(".", "")
        
        spec_content = f"""Name:           {rpm_name}
Version:        {version}
Release:        1%{{?dist}}
Summary:        Python package {package_name}

License:        Unknown
URL:            https://pypi.org/project/{package_name}
Source0:        %{{pypi_source {package_name}}}

BuildArch:      noarch
BuildRequires:  python{py_suffix}-devel
BuildRequires:  python{py_suffix}-setuptools
BuildRequires:  python{py_suffix}-pip
BuildRequires:  python{py_suffix}-wheel

%description
Python package {package_name}

%prep
%autosetup -n {package_name}-%{{version}}

%build
%py{py_macro}_build

%install
%py{py_macro}_install

%files
%{{python{py_macro}_sitelib}}/*

%changelog
* {date} {self.packager_name} <{self.packager_email}> - {version}-1
- Initial package generated by ReqPM
"""
        return spec_content
    
    def _normalize_package_name(self, name: str) -> str:
        """Normalize package name for RPM"""
        normalized = name.lower().replace('_', '-').replace('.', '-')
        return f"python3-{normalized}"
    
    def update_spec_version(
        self,
        spec_content: str,
        new_version: str,
        changelog_entry: Optional[str] = None
    ) -> str:
        """
        Update version in existing spec file
        
        Args:
            spec_content: Current spec file content
            new_version: New version number
            changelog_entry: Optional changelog entry
        
        Returns:
            Updated spec file content
        """
        # Update version
        spec_content = re.sub(
            r'^Version:\s+.*$',
            f'Version:        {new_version}',
            spec_content,
            flags=re.MULTILINE
        )
        
        # Reset release
        spec_content = re.sub(
            r'^Release:\s+.*$',
            'Release:        1%{?dist}',
            spec_content,
            flags=re.MULTILINE
        )
        
        # Add changelog entry
        if changelog_entry:
            date = datetime.now().strftime("%a %b %d %Y")
            packager = f"{self.packager_name} <{self.packager_email}>"
            entry = f"* {date} {packager} - {new_version}-1\n- {changelog_entry}\n\n"
            
            spec_content = re.sub(
                r'(%changelog\n)',
                f'\\1{entry}',
                spec_content
            )
        
        return spec_content
