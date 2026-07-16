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
        build_system: str = "unknown",
        python_name: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        Generate RPM spec file for a Python package using pyp2spec
        Following awx-rpm-v2 approach: pyp2spec [-p PYTHONVERSION] --license gpl [-v VERSION] PACKAGE
        
        Args:
            package_name: Name of the RPM package (normalized with hyphens)
            version: Specific version (None for latest)
            python_version: Python version (e.g., "3.11", "3.12", or "default" to omit -p flag)
            build_system: Detected/stored build system (e.g., 'setuptools', 'poetry', 'hatchling')
            python_name: Original Python package name from PyPI (may use underscores/hyphens differently than package_name)
            **kwargs: Additional arguments (ignored for compatibility)
        
        Returns:
            Spec file content as string
        """
        logger.info(f"Generating spec for {package_name} using pyp2spec")
        
        # Use python_name for PyPI interactions if provided, otherwise use package_name
        pypi_name = python_name if python_name else package_name
        
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
            logger.info(f"Generating spec for {package_name} version {version} (PyPI name: {pypi_name})")
        else:
            logger.info(f"Generating spec for {package_name} (latest version, PyPI name: {pypi_name})")
        
        cmd.append(pypi_name)
        
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
                fallback_spec = self._generate_fallback_spec(package_name, version, python_version, python_name)
                return self._post_process_spec(fallback_spec, package_name, version, build_system, pypi_name)
            
            # pyp2spec prints the spec to stdout by default
            spec_content = result.stdout
            
            if not spec_content or len(spec_content.strip()) == 0:
                logger.error(f"pyp2spec returned empty spec for {package_name}")
                fallback_spec = self._generate_fallback_spec(package_name, version, python_version, python_name)
                return self._post_process_spec(fallback_spec, package_name, version, build_system, pypi_name)
            
            logger.info(f"Successfully generated spec for {package_name}")
            
            # Post-process the spec file
            spec_content = self._post_process_spec(spec_content, package_name, version, build_system, pypi_name)
            
            return spec_content
            
        except subprocess.TimeoutExpired:
            logger.error(f"pyp2spec timed out for {package_name}")
            fallback_spec = self._generate_fallback_spec(package_name, version, python_version, python_name)
            return self._post_process_spec(fallback_spec, package_name, version, build_system, pypi_name)
        except Exception as e:
            logger.error(f"Error generating spec for {package_name}: {e}")
            fallback_spec = self._generate_fallback_spec(package_name, version, python_version, python_name)
            return self._post_process_spec(fallback_spec, package_name, version, build_system, pypi_name)
    
    def _post_process_spec(
        self,
        spec_content: str,
        package_name: str,
        version: Optional[str],
        build_system: str = 'unknown',
        pypi_name: Optional[str] = None,
    ) -> str:
        """
        Post-process the generated spec file
        
        Args:
            spec_content: Generated spec content
            package_name: Package name
            version: Package version
            build_system: Detected/stored build system
        
        Returns:
            Post-processed spec content
        """
        # Decide whether to enforce pyproject macros.
        # Only keep legacy setup.py paths for packages explicitly identified as setuptools.
        use_pyproject = (build_system != 'setuptools')

        if use_pyproject:
            # Replace the old %py3_build / %py3_install macros (these expand to
            # "python3 setup.py build/install" at RPM build time and will fail
            # for any package that doesn't ship a setup.py).
            spec_content = re.sub(r'%py3_build\b', '%pyproject_wheel', spec_content)
            spec_content = re.sub(r'%py3_install\b', '%pyproject_install', spec_content)
            spec_content = re.sub(r'%python_build\b', '%pyproject_wheel', spec_content)
            spec_content = re.sub(r'%python_install\b', '%pyproject_install', spec_content)

        # Always replace literal python3 setup.py invocations regardless of
        # build_system — if the spec literally calls python3 setup.py build but
        # the package has no setup.py we want the safer macro.
        spec_content = re.sub(
            r'/usr/bin/python3\s+setup\.py\s+build[^\n]*',
            '%pyproject_wheel',
            spec_content
        )
        spec_content = re.sub(
            r'/usr/bin/python3\s+setup\.py\s+install[^\n]*',
            '%pyproject_install',
            spec_content
        )

        # Strip extras bracket notation from BuildRequires — RPM package names
        # cannot carry extras (e.g. python3-pyjwt[crypto], python3dist(twisted[tls])).
        # These come from PyPI metadata that pyp2spec copies verbatim.
        spec_content = re.sub(
            r'^(BuildRequires:[^\[#\n]+?)\[[^\]]+\](\)?)',
            r'\1\2',
            spec_content,
            flags=re.MULTILINE,
        )

        # Also normalize distro-style python package aliases that carry extras,
        # e.g. python3-twisted[tls] -> python3-twisted.
        spec_content = re.sub(
            r'^(\s*BuildRequires\s*:\s*python3?-[A-Za-z0-9._+-]+)\[[^\]]+\](\s*)$',
            r'\1\2',
            spec_content,
            flags=re.MULTILINE,
        )

        # Normalize distro-style python BuildRequires names to lowercase so
        # tokens like "python3-PyJWT" resolve as "python3-pyjwt" in dnf.
        spec_content = re.sub(
            r'^(\s*BuildRequires\s*:\s*python3?-)([A-Za-z0-9._+-]+)\s*$',
            lambda m: f"{m.group(1)}{m.group(2).lower()}",
            spec_content,
            flags=re.MULTILINE,
        )

        # pyp2spec metadata can emit invalid python package devel aliases like
        # python3-poetry-core-devel. For Python deps this should be the runtime
        # package/provide name (python3-poetry-core or python3dist(poetry-core)).
        spec_content = re.sub(
            r'^\s*BuildRequires\s*:\s*(python3?-[A-Za-z0-9._+-]+)-devel\b[^\n]*$',
            lambda m: f'BuildRequires: {m.group(1).lower()}',
            spec_content,
            flags=re.MULTILINE,
        )
        spec_content = re.sub(
            r'^\s*BuildRequires\s*:\s*(python3?dist\([A-Za-z0-9._+-]+)-devel(\))\b[^\n]*$',
            lambda m: f'BuildRequires: {m.group(1).lower()}{m.group(2)}',
            spec_content,
            flags=re.MULTILINE,
        )

        # Normalize known extras-derived alias tokens that are not valid RPM
        # package names in this build environment.
        spec_content = re.sub(
            r'^\s*BuildRequires\s*:\s*python3-pyjwt-crypto\b[^\n]*$',
            'BuildRequires: python3-pyjwt',
            spec_content,
            flags=re.MULTILINE | re.IGNORECASE,
        )

        # python3-openssl is a bad alias in RHEL repos; use the distro
        # development package required for OpenSSL-backed builds.
        spec_content = re.sub(
            r'^\s*BuildRequires\s*:\s*python3-openssl\b[^\n]*$',
            'BuildRequires: openssl-devel',
            spec_content,
            flags=re.MULTILINE | re.IGNORECASE,
        )

        # Drop malformed/no-op BuildRequires aliases observed from noisy
        # metadata parsing. They are not valid RHEL package names and break
        # dnf builddep resolution inside mock.
        spec_content = re.sub(
            r'^\s*BuildRequires\s*:\s*(?:python3-python3dist|python3-venv|python3dist)\b[^\n]*\n?',
            '',
            spec_content,
            flags=re.MULTILINE | re.IGNORECASE,
        )

        # Detect hatch-vcs usage and patch pyproject.toml in %prep to use
        # environment-variable-based versioning instead (hatch-vcs requires
        # git history, which is not available inside the mock chroot).
        if re.search(r'BuildRequires:.*hatch.vcs', spec_content, re.IGNORECASE):
            # Drop the hatch-vcs BuildRequires — the %prep patch removes it from
            # pyproject.toml so it is no longer needed at build time.
            spec_content = re.sub(
                r'^BuildRequires:\s*(?:python3?dist\()?hatch.vcs[^)\n]*\)?\s*\n',
                '',
                spec_content,
                flags=re.MULTILINE | re.IGNORECASE,
            )
            # Inject a %prep shell snippet (after %setup / %autosetup) that
            # rewrites pyproject.toml to switch from VCS-based to env-based versioning.
            _hatchvcs_patch = r"""
# Remove hatch-vcs (requires git, not available in mock) and use env-based versioning
python3 - << 'REQPM_HV_PYEOF'
import re
c = open('pyproject.toml').read()
c = re.sub(r'[ \t]*"hatch-vcs[^"]*",?\n?', '', c)
c = re.sub(r"[ \t]*'hatch-vcs[^']*',?\n?", '', c)
c = re.sub(r'\[tool\.hatch\.build\.hooks\.vcs\][^\[]*', '', c, flags=re.DOTALL)
c = re.sub(r'source\s*=\s*"vcs"', 'source = "env"', c)
c = re.sub(r"source\s*=\s*'vcs'", "source = 'env'", c)
if 'variable' not in c:
    c = re.sub(r'''(source = "env"|source = 'env')''',
               lambda m: m.group(0) + '\nvariable = "SETUPTOOLS_SCM_PRETEND_VERSION"', c, count=1)
if 'ignore-vcs' not in c:
    c += '\n[tool.hatch.build.targets.wheel]\nignore-vcs = true\n'
open('pyproject.toml', 'w').write(c)
REQPM_HV_PYEOF
"""
            # Insert the patch after the first %setup or %autosetup line in %prep
            spec_content = re.sub(
                r'^(%(?:auto)?setup[^\n]*)\n',
                lambda m: m.group(1) + '\n' + _hatchvcs_patch,
                spec_content,
                flags=re.MULTILINE,
                count=1,
            )

        # Ensure pyproject macros BuildRequires are present if using pyproject macros
        if '%pyproject_wheel' in spec_content or '%pyproject_install' in spec_content:
            if 'BuildRequires:  pyproject-rpm-macros' not in spec_content and 'BuildRequires: pyproject-rpm-macros' not in spec_content:
                # Add after other BuildRequires
                spec_content = re.sub(
                    r'(BuildRequires:.*python.*-devel)',
                    r'\1\nBuildRequires:  pyproject-rpm-macros',
                    spec_content,
                    count=1
                )

            # Ensure %generate_buildrequires section with %pyproject_buildrequires exists
            if '%generate_buildrequires' not in spec_content:
                spec_content = re.sub(
                    r'^(%build)',
                    '%generate_buildrequires\n%pyproject_buildrequires\n\n\\1',
                    spec_content,
                    flags=re.MULTILINE,
                    count=1
                )
            elif '%pyproject_buildrequires' not in spec_content:
                spec_content = re.sub(
                    r'^(%generate_buildrequires)',
                    '\\1\n%pyproject_buildrequires',
                    spec_content,
                    flags=re.MULTILINE,
                    count=1
                )

        # Prefix %pyproject_wheel AND %pyproject_buildrequires with
        # SETUPTOOLS_SCM_PRETEND_VERSION so that packages using hatch-vcs /
        # setuptools-scm get a sensible version even when git is not available
        # inside the mock chroot.  This env var is a no-op for other packages.
        if '%pyproject_wheel' in spec_content:
            spec_content = re.sub(
                r'^(%pyproject_wheel\b)',
                r'SETUPTOOLS_SCM_PRETEND_VERSION=%{version} \1',
                spec_content,
                flags=re.MULTILINE,
                count=1,
            )
        if '%pyproject_buildrequires' in spec_content:
            spec_content = re.sub(
                r'^(%pyproject_buildrequires\b)',
                r'SETUPTOOLS_SCM_PRETEND_VERSION=%{version} \1',
                spec_content,
                flags=re.MULTILINE,
                count=1,
            )

        # Fix rich boolean dependencies from pyp2rpm
        # Convert: (python3dist(pkg) >= 1 with python3dist(pkg) < 3~~)
        # To: python3dist(pkg) >= 1
        spec_content = re.sub(
            r'\(python3dist\(([^)]+)\)\s+([><=!]+\s+[^\s)]+)(?:\s+with\s+[^)]+)?\)',
            r'python3dist(\1) \2',
            spec_content
        )

        # Remove self-referential BuildRequires — a package must not require itself.
        # pyp2spec sometimes emits this when PyPI metadata lists the package as its
        # own dependency (common in packages that vendor their own dist-info).
        # Normalize: awx-plugins-interfaces  ->  awx_plugins_interfaces
        _norm_name = re.sub(r'[-.]', '_', package_name).lower()
        # Also strip leading python3- / python- prefix that the RPM name may carry
        _dist_name = re.sub(r'^python3?_', '', _norm_name)
        spec_content = re.sub(
            rf'^BuildRequires:\s+python3?dist\({re.escape(_dist_name)}\)[^\n]*\n',
            '',
            spec_content,
            flags=re.MULTILINE | re.IGNORECASE,
        )
        spec_content = re.sub(
            rf'^BuildRequires:\s+python3?-{re.escape(_dist_name.replace("_", "-"))}\b[^\n]*\n',
            '',
            spec_content,
            flags=re.MULTILINE | re.IGNORECASE,
        )
        
        # Normalize Source0 to use the pypi_source macro. Some pyp2spec outputs
        # emit literal tarball names (e.g. backports_zoneinfo-%{version}.tar.gz),
        # which can break source fetching in mock workflows.
        src_pypi_name = (pypi_name or package_name or '').strip()
        if src_pypi_name:
            if re.search(r'^Source0:\s+%\{pypi_source\s+[^}]+\}', spec_content, flags=re.MULTILINE):
                spec_content = re.sub(
                    r'^Source0:\s+%\{pypi_source\s+[^}]+\}',
                    f'Source0:        %{{pypi_source {src_pypi_name}}}',
                    spec_content,
                    flags=re.MULTILINE,
                    count=1,
                )
            elif re.search(r'^Source0:\s+[^\s]+-%\{version\}\.tar\.gz\s*$', spec_content, flags=re.MULTILINE):
                spec_content = re.sub(
                    r'^Source0:\s+[^\s]+-%\{version\}\.tar\.gz\s*$',
                    f'Source0:        %{{pypi_source {src_pypi_name}}}',
                    spec_content,
                    flags=re.MULTILINE,
                    count=1,
                )

        # Fix %autosetup -n to use PyPI normalized directory names
        # PyPI tarballs unpack to directories with underscores
        # PyPI normalization: replace hyphens AND dots with underscores
        # Examples: flit-core -> flit_core, awx-plugins.interfaces -> awx_plugins_interfaces
        spec_content = re.sub(
            r'(%autosetup[^\n]*\s-n\s+)([a-zA-Z0-9.-]+)(-%{\s*version\s*})',
            lambda m: f"{m.group(1)}{m.group(2).replace('-', '_').replace('.', '_').lower()}{m.group(3)}",
            spec_content
        )
        spec_content = re.sub(
            r'(%setup[^\n]*\s-n\s+)([a-zA-Z0-9.-]+)(-%{\s*version\s*})',
            lambda m: f"{m.group(1)}{m.group(2).replace('-', '_').replace('.', '_').lower()}{m.group(3)}",
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
    
    def _generate_fallback_spec(self, package_name: str, version: Optional[str] = None, python_version: str = "3.11", python_name: Optional[str] = None) -> str:
        """
        Generate a basic fallback spec file if pyp2spec fails
        Uses modern pyproject.toml build system
        
        Args:
            package_name: RPM package name (normalized with hyphens)
            version: Package version
            python_version: Python version for spec (or "default" to use system default)
            python_name: Original Python package name from PyPI (may differ from package_name)
        
        Returns:
            Basic spec file content
        """
        logger.warning(f"Using fallback spec generation for {package_name}")
        
        rpm_name = self._normalize_package_name(package_name)
        pypi_name = python_name if python_name else package_name
        # For Source0, use PyPI-normalized name (underscores) to match actual tarball filename
        pypi_source_name = pypi_name.replace('-', '_').replace('.', '_')
        
        # Keep Source0 as pypi_source so fetch_sources can consistently resolve
        # and download the source archive from PyPI.
        has_special_chars = '.' in pypi_name or '-' in pypi_name
        source_line = f"Source0:        %{{pypi_source {pypi_name}}}"
        
        version = version or "0.0.1"
        date = datetime.now().strftime("%a %b %d %Y")

        # Resolve the correct SPDX license from PyPI metadata
        license_str = "Unknown"
        try:
            from backend.core.pypi_client import PyPIClient
            _pypi = PyPIClient()
            _pkg_info = _pypi.get_package_info(pypi_name, version)
            if _pkg_info and _pkg_info.license and _pkg_info.license != 'Unknown':
                license_str = _pkg_info.license
        except Exception as _e:
            logger.debug(f"Could not resolve license for {pypi_name}: {_e}")

        # Determine Python version suffix (empty for "default")
        py_suffix = "" if python_version == "default" else python_version
        py_macro = "3" if python_version == "default" else python_version.replace(".", "")
        
        # Create appropriate %prep section based on package naming
        if has_special_chars:
            # For packages with dots/hyphens, use manual extraction with fallback logic
            prep_section = f"""# Extract and cd into correct directory (with fallback for naming variations)
cd %{{_builddir}}
rm -rf *-%{{version}} 2>/dev/null || true
tar -xzf %{{SOURCE0}}
# Try underscored directory first (PyPI normalized), then hyphenated, then any match
if [ -d \"{pypi_source_name}-%{{version}}\" ]; then
    cd \"{pypi_source_name}-%{{version}}\"
elif [ -d \"{pypi_name}-%{{version}}\" ]; then
    cd \"{pypi_name}-%{{version}}\"
else
    EXTRACTED_DIR=$(find . -maxdepth 1 -type d -name \"*-%{{version}}\" -printf \"%f\\n\" | head -1)
    if [ -n \"$EXTRACTED_DIR\" ]; then
        cd \"$EXTRACTED_DIR\"
    else
        echo \"ERROR: Could not find extracted directory matching *-%{{version}}\"
        exit 1
    fi
fi

# Handle packages where pyproject.toml/setup.py might be in a subdirectory
if [ ! -f pyproject.toml ] && [ ! -f setup.py ]; then
    # Look for build files in subdirectories
    BUILD_SUBDIR=$(find . -maxdepth 2 -name pyproject.toml -o -name setup.py | head -1 | xargs dirname 2>/dev/null)
    if [ -n \"$BUILD_SUBDIR\" ] && [ \"$BUILD_SUBDIR\" != \".\" ]; then
        echo \"Found build files in subdirectory: $BUILD_SUBDIR\"
        cd \"$BUILD_SUBDIR\"
    fi
fi"""
        else:
            # For normal packages, use standard %setup
            prep_section = f"%setup -q -n {pypi_source_name}-%{{version}}"
        
        # Create appropriate %generate_buildrequires section
        if has_special_chars:
            # For packages with special chars, ensure we're in the package directory
            generate_buildrequires = f"""cd %{{_builddir}}
# Find the extracted package directory
PKG_DIR=$(find . -maxdepth 1 -type d -name "*-%{{version}}" -printf \"%f\" | head -1)
if [ -n \"$PKG_DIR\" ]; then
    cd \"$PKG_DIR\"
    # Check for build files in subdirectories
    if [ ! -f pyproject.toml ] && [ ! -f setup.py ]; then
        BUILD_SUBDIR=$(find . -maxdepth 2 -name pyproject.toml -o -name setup.py | head -1 | xargs dirname 2>/dev/null)
        if [ -n \"$BUILD_SUBDIR\" ] && [ \"$BUILD_SUBDIR\" != \".\" ]; then
            cd \"$BUILD_SUBDIR\"
        fi
    fi
fi
%pyproject_buildrequires"""
        else:
            generate_buildrequires = "%pyproject_buildrequires"
        
        # Create appropriate %build and %install sections
        if has_special_chars:
            # For packages with special chars, navigate to package directory first
            build_section = f"""cd %{{_builddir}}
PKG_DIR=$(find . -maxdepth 1 -type d -name "*-%{{version}}" -printf \"%f\" | head -1)
if [ -n \"$PKG_DIR\" ]; then
    cd \"$PKG_DIR\"
    if [ ! -f pyproject.toml ] && [ ! -f setup.py ]; then
        BUILD_SUBDIR=$(find . -maxdepth 2 -name pyproject.toml -o -name setup.py | head -1 | xargs dirname 2>/dev/null)
        if [ -n \"$BUILD_SUBDIR\" ] && [ \"$BUILD_SUBDIR\" != \".\" ]; then
            cd \"$BUILD_SUBDIR\"
        fi
    fi
fi
%pyproject_wheel"""
            
            install_section = f"""cd %{{_builddir}}
PKG_DIR=$(find . -maxdepth 1 -type d -name "*-%{{version}}" -printf \"%f\" | head -1)
if [ -n \"$PKG_DIR\" ]; then
    cd \"$PKG_DIR\"
    if [ ! -f pyproject.toml ] && [ ! -f setup.py ]; then
        BUILD_SUBDIR=$(find . -maxdepth 2 -name pyproject.toml -o -name setup.py | head -1 | xargs dirname 2>/dev/null)
        if [ -n \"$BUILD_SUBDIR\" ] && [ \"$BUILD_SUBDIR\" != \".\" ]; then
            cd \"$BUILD_SUBDIR\"
        fi
    fi
fi
%pyproject_install
%pyproject_save_files {pypi_name.replace('-', '_')}"""
        else:
            build_section = "%pyproject_wheel"
            install_section = f"""%pyproject_install
%pyproject_save_files {pypi_name.replace('-', '_')}"""
        
        spec_content = f"""Name:           {rpm_name}
Version:        {version}
Release:        1%{{?dist}}
Summary:        Python package {pypi_name}

License:        {license_str}
URL:            https://pypi.org/project/{pypi_name}
{source_line}

BuildArch:      noarch
BuildRequires:  python{py_suffix}-devel
BuildRequires:  pyproject-rpm-macros

%description
Python package {pypi_name}

%prep
{prep_section}

%generate_buildrequires
{generate_buildrequires}

%build
{build_section}

%install
{install_section}

%files -f %{{pyproject_files}}

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
