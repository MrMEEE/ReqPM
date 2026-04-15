"""
Spec file auto-fixer.

Implements the same fixes as awx-rpm-v2 scripts:
  adddepend        → add BuildRequires / Requires lines
  fixpythonshebangs → add pathfix.py calls
  removedebuginfo  → add %global debug_package %{nil}
  (custom)         → remove BuildArch: noarch for arch-mismatch failures
"""
import re
import logging

logger = logging.getLogger(__name__)

# Error categories that this module can auto-fix
AUTO_FIXABLE_CATEGORIES = {
    'Missing Packages',
    'Missing Dependencies',
    'Missing Python Modules',
    'Missing Python Wheel',
    'Missing GCC',
    'Missing G++ Compiler',
    'Missing Header Files',
    'Ambiguous Python Shebang',
    'Empty Debug Info',
    'Architecture Mismatch',
    'Invalid Pyproject License',
    'Missing Setup.py',
    'Unpackaged Files',
    'Wrong Module Glob',
}

# Maps header filenames and pkg-config names → their RPM -devel package.
# Keys are bare filenames (e.g. 'ffi.h'), full include paths ('openssl/ssl.h'),
# or pkg-config module names ('libffi').
HEADER_TO_DEVEL = {
    # libffi
    'ffi.h': 'libffi-devel',
    'ffitarget.h': 'libffi-devel',
    'libffi': 'libffi-devel',
    # zlib
    'zlib.h': 'zlib-devel',
    'zlib': 'zlib-devel',
    # OpenSSL
    'openssl/ssl.h': 'openssl-devel',
    'openssl/evp.h': 'openssl-devel',
    'openssl/crypto.h': 'openssl-devel',
    'openssl/err.h': 'openssl-devel',
    'openssl/rsa.h': 'openssl-devel',
    'openssl/x509.h': 'openssl-devel',
    'openssl': 'openssl-devel',
    'libssl': 'openssl-devel',
    'libcrypto': 'openssl-devel',
    # libcurl
    'curl/curl.h': 'libcurl-devel',
    'libcurl': 'libcurl-devel',
    # libxml2
    'libxml/xmlversion.h': 'libxml2-devel',
    'libxml/xpath.h': 'libxml2-devel',
    'libxml/parser.h': 'libxml2-devel',
    'libxml2': 'libxml2-devel',
    'libxml-2.0': 'libxml2-devel',
    # libxslt
    'libxslt/xslt.h': 'libxslt-devel',
    'libxslt': 'libxslt-devel',
    # libyaml
    'yaml.h': 'libyaml-devel',
    'yaml-0.1': 'libyaml-devel',
    'libyaml-0': 'libyaml-devel',
    # lz4
    'lz4.h': 'lz4-devel',
    'lz4frame.h': 'lz4-devel',
    'liblz4': 'lz4-devel',
    # xz / lzma
    'lzma.h': 'xz-devel',
    'lzma/lzma.h': 'xz-devel',
    'liblzma': 'xz-devel',
    # bzip2
    'bzlib.h': 'bzip2-devel',
    'bzip2': 'bzip2-devel',
    # zstd
    'zstd.h': 'libzstd-devel',
    'libzstd': 'libzstd-devel',
    'zstd': 'libzstd-devel',
    # libsodium
    'sodium.h': 'libsodium-devel',
    'sodium': 'libsodium-devel',
    'libsodium': 'libsodium-devel',
    # libevent
    'event.h': 'libevent-devel',
    'event2/event.h': 'libevent-devel',
    'libevent': 'libevent-devel',
    # snappy
    'snappy.h': 'snappy-devel',
    'snappy-c.h': 'snappy-devel',
    'snappy': 'snappy-devel',
    # readline
    'readline/readline.h': 'readline-devel',
    'readline': 'readline-devel',
    # openldap
    'ldap.h': 'openldap-devel',
    'ldap': 'openldap-devel',
    # cyrus-sasl
    'sasl/sasl.h': 'cyrus-sasl-devel',
    # libuuid
    'uuid/uuid.h': 'libuuid-devel',
    'uuid': 'libuuid-devel',
    # glib2
    'glib.h': 'glib2-devel',
    'glib/glib.h': 'glib2-devel',
    'gio/gio.h': 'glib2-devel',
    'glib-2.0': 'glib2-devel',
    'gio-2.0': 'glib2-devel',
    'gmodule-2.0': 'glib2-devel',
    'gobject-2.0': 'glib2-devel',
    # dbus
    'dbus/dbus.h': 'dbus-devel',
    'dbus-1': 'dbus-devel',
    # expat
    'expat.h': 'expat-devel',
    'expat': 'expat-devel',
    # libjpeg
    'jpeglib.h': 'libjpeg-turbo-devel',
    'libjpeg': 'libjpeg-turbo-devel',
    # libpng
    'png.h': 'libpng-devel',
    'libpng': 'libpng-devel',
    'libpng16': 'libpng-devel',
    # libtiff
    'tiff.h': 'libtiff-devel',
    'libtiff-4': 'libtiff-devel',
    # freetype
    'ft2build.h': 'freetype-devel',
    'freetype/freetype.h': 'freetype-devel',
    'freetype2': 'freetype-devel',
    # sqlite
    'sqlite3.h': 'sqlite-devel',
    'sqlite3': 'sqlite-devel',
    # postgresql
    'libpq-fe.h': 'postgresql-devel',
    'libpq': 'postgresql-devel',
    'postgres.h': 'postgresql-devel',
    # mysql
    'mysql/mysql.h': 'mysql-devel',
    'mysql.h': 'mysql-devel',
    'mysqlclient': 'mysql-devel',
    # pcre
    'pcre.h': 'pcre-devel',
    'pcre': 'pcre-devel',
    'pcre2.h': 'pcre2-devel',
    'pcre2': 'pcre2-devel',
    # nettle
    'nettle/nettle-types.h': 'nettle-devel',
    'nettle': 'nettle-devel',
    'hogweed': 'nettle-devel',
    # brotli
    'brotli/decode.h': 'brotli-devel',
    'libbrotlicommon': 'brotli-devel',
    'libbrotlienc': 'brotli-devel',
    'libbrotlidec': 'brotli-devel',
    # cairo
    'cairo.h': 'cairo-devel',
    'cairo': 'cairo-devel',
    # pango
    'pango/pango.h': 'pango-devel',
    'pango': 'pango-devel',
    # gtk3
    'gtk/gtk.h': 'gtk3-devel',
    'gdk/gdk.h': 'gtk3-devel',
    'gtk+-3.0': 'gtk3-devel',
    # python3
    'Python.h': 'python3-devel',
    'python3': 'python3-devel',
}


def has_auto_fix(analyzed_errors: list) -> bool:
    """Return True if any error in the list can be auto-fixed."""
    return any(e.get('category') in AUTO_FIXABLE_CATEGORIES for e in analyzed_errors)


class SpecFixer:
    """Apply automated spec fixes derived from awx-rpm-v2 fix scripts."""

    def apply_fixes(self, spec_content: str, analyzed_errors: list) -> tuple:
        """
        Apply all applicable fixes and return (new_spec, fixes_applied).

        fixes_applied is a list of human-readable strings describing each fix.
        """
        fixes = []
        content = spec_content

        for error in analyzed_errors:
            category = error.get('category', '')
            items = error.get('items', [])

            if category in ('Missing Packages', 'Missing Dependencies'):
                content, applied = self._add_buildrequires_items(content, items)
                fixes.extend(applied)

            elif category == 'Missing Python Modules':
                # Convert module names to python3-<module> package names
                packages = []
                for item in items:
                    # Strip quotes, spaces
                    mod = item.strip().strip("'\"")
                    # Skip 'packaging' — usually already present
                    if mod == 'packaging':
                        continue
                    # e.g. numpy → python3-numpy
                    pkg = f'python3-{mod.replace(".", "-").lower()}'
                    packages.append(pkg)
                if packages:
                    content, applied = self._add_buildrequires_items(content, packages)
                    fixes.extend(applied)

            elif category == 'Missing Python Wheel':
                content, applied = self._add_buildrequires_items(content, ['python3-wheel'])
                fixes.extend(applied)

            elif category == 'Missing GCC':
                content, applied = self._add_buildrequires_items(content, ['gcc'])
                fixes.extend(applied)

            elif category == 'Missing Header Files':
                content, applied = self._fix_missing_headers(content, items)
                fixes.extend(applied)

            elif category == 'Ambiguous Python Shebang':
                content, applied = self._fix_shebang(content)
                fixes.extend(applied)

            elif category == 'Empty Debug Info':
                content, applied = self._fix_debuginfo(content)
                fixes.extend(applied)

            elif category == 'Architecture Mismatch':
                content, applied = self._fix_arch_mismatch(content)
                fixes.extend(applied)

            elif category == 'Invalid Pyproject License':
                content, applied = self._fix_pyproject_license(content)
                fixes.extend(applied)

            elif category == 'Missing G++ Compiler':
                content, applied = self._add_buildrequires_items(content, ['gcc-c++'])
                fixes.extend(applied)

            elif category == 'Missing Setup.py':
                content, applied = self._fix_legacy_macros(content)
                fixes.extend(applied)

            elif category == 'Unpackaged Files':
                # Extract file list from error items or log
                # This will be filled in by extracting from build log
                content, applied = self._fix_unpackaged_files(content, error)
                fixes.extend(applied)

            elif category == 'Wrong Module Glob':
                content, applied = self._fix_wrong_module_glob(content, items)
                fixes.extend(applied)

        return content, fixes

    # ------------------------------------------------------------------
    # Individual fixers (mirror the awx-rpm-v2 sed operations)
    # ------------------------------------------------------------------

    def _add_buildrequires_items(self, spec: str, items: list) -> tuple:
        """
        Add each item as a BuildRequires line before the first existing
        BuildRequires line (same as adddepend in awx-rpm-v2).

        Strips out already-present entries and cleans quoted RPM dep strings.
        """
        applied = []
        content = spec

        # Words that can appear in dnf error messages but are never package names
        _NOISE = {
            'not', 'all', 'some', 'be', 'could', 'dependencies', 'found',
            'found.', 'packages', 'satisfied', 'no', 'is', 'the', 'and',
            'or', 'of', 'to', 'in', 'for', 'are', 'was', 'error', 'warning',
        }

        for raw_item in items:
            item = raw_item.strip().strip("'\"")
            if not item:
                continue
            # Reject obvious noise: plain English words or items containing spaces
            if item.lower() in _NOISE or item.endswith('.') or ' ' in item:
                logger.debug(f'SpecFixer: skipping noise item: {item!r}')
                continue

            # Skip if already present as a BuildRequires
            if re.search(
                r'^\s*BuildRequires\s*:\s*' + re.escape(item),
                content,
                re.MULTILINE | re.IGNORECASE,
            ):
                continue

            new_line = f'BuildRequires:  {item}'
            # Insert before first BuildRequires (like sed "0,/BuildRequires/s//new\n&/")
            content = re.sub(
                r'(BuildRequires\s*:)',
                new_line + r'\n\1',
                content,
                count=1,
            )
            applied.append(f'Added BuildRequires: {item}')
            logger.debug(f'SpecFixer: added BuildRequires: {item}')

        return content, applied

    def _fix_missing_headers(self, spec: str, items: list) -> tuple:
        """
        Map missing header files / pkg-config names to their -devel packages
        and add them as BuildRequires.
        """
        packages = []
        for item in items:
            item = item.strip()
            if not item:
                continue
            pkg = HEADER_TO_DEVEL.get(item)
            if pkg:
                packages.append(pkg)
            else:
                logger.debug(f'SpecFixer: no devel mapping for header/pc: {item!r}')
        if packages:
            # De-duplicate while preserving order
            seen = set()
            unique = [p for p in packages if not (p in seen or seen.add(p))]
            return self._add_buildrequires_items(spec, unique)
        return spec, []

    def _fix_shebang(self, spec: str) -> tuple:
        """
        Fix ambiguous Python shebangs (awx-rpm-v2 fixpythonshebangs):
          1. Add `BuildRequires: /usr/bin/pathfix.py` before first BuildRequires
          2. After %autosetup, add pathfix call for source tree
          3. After %pyproject_save_files / end of %install, add pathfix for buildroot
        """
        applied = []
        content = spec

        # 1. Add BuildRequires: /usr/bin/pathfix.py
        if '/usr/bin/pathfix.py' not in content:
            content, a = self._add_buildrequires_items(content, ['/usr/bin/pathfix.py'])
            applied.extend(a)

        # 2. After %autosetup line, add pathfix for source tree
        if 'pathfix.py' not in content or '%autosetup' in content:
            content = re.sub(
                r'(%autosetup\b[^\n]*)',
                r'\1\npathfix.py -pni "%{__python3} %{py3_shbang_opts}" .',
                content,
                count=1,
            )
            applied.append('Added pathfix.py call after %autosetup')

        # 3. After %pyproject_save_files (or last line of %install if no pyproject_save_files)
        pathfix_buildroot = 'pathfix.py -pni "%{__python3} %{py3_shbang_opts}" %{buildroot} %{buildroot}%{_bindir}/*'
        if pathfix_buildroot not in content:
            if '%pyproject_save_files' in content:
                content = re.sub(
                    r'(%pyproject_save_files\b[^\n]*)',
                    r'\1\n' + pathfix_buildroot,
                    content,
                    count=1,
                )
            else:
                # Append at end of %install section (before next % section)
                content = re.sub(
                    r'(%install\b[^\n]*\n(?:(?!^%).)*)',
                    r'\g<0>' + pathfix_buildroot + '\n',
                    content,
                    flags=re.MULTILINE | re.DOTALL,
                    count=1,
                )
            applied.append('Added pathfix.py calls for buildroot')

        return content, applied

    def _fix_debuginfo(self, spec: str) -> tuple:
        """
        Add %global debug_package %{nil} at the very top of the spec
        (awx-rpm-v2 removedebuginfo).
        """
        marker = '%global debug_package %{nil}'
        if marker in spec:
            return spec, []
        fixed = marker + '\n' + spec
        return fixed, ['Added %global debug_package %{nil} (suppress empty debuginfo)']

    def _fix_arch_mismatch(self, spec: str) -> tuple:
        """
        Remove BuildArch: noarch when the package contains architecture-dependent
        binaries (awx-rpm-v2 has no script for this, but the fix is clear).
        """
        if not re.search(r'^\s*BuildArch\s*:\s*noarch', spec, re.MULTILINE | re.IGNORECASE):
            return spec, []
        fixed = re.sub(
            r'^\s*BuildArch\s*:\s*noarch\s*\n?',
            '',
            spec,
            flags=re.MULTILINE | re.IGNORECASE,
        )
        return fixed, ['Removed BuildArch: noarch (package contains arch-dependent binaries)']

    def _fix_pyproject_license(self, spec: str) -> tuple:
        """
        Inject a sed patch after %autosetup to convert a bare SPDX license string
        in pyproject.toml to the PEP 621-compliant table form.

        Transforms:  license = "MIT"
        Into:        license = {text = "MIT"}

        This is needed for packages whose pyproject.toml pre-dates PEP 639.
        """
        # sed_cmd is also the idempotency marker -- if it's already in the spec
        # then a previous fix_and_rebuild already applied this patch.
        sed_cmd = r"""sed -i 's/^license = "\(.*\)"/license = {text = "\1"}/' pyproject.toml 2>/dev/null || true"""
        if sed_cmd in spec:
            return spec, []

        fix_msg = 'Patched pyproject.toml: converted bare license string to {text = "..."} (PEP 621)'

        # Inject after %autosetup (use lambda to prevent re.sub from interpreting
        # backslashes in sed_cmd as regex backreferences)
        if '%autosetup' in spec:
            new_spec = re.sub(
                r'(%autosetup\b[^\n]*)',
                lambda m: m.group(1) + '\n' + sed_cmd,
                spec,
                count=1,
            )
            if new_spec != spec:
                return new_spec, [fix_msg]

        # Fallback: inject after %setup
        if '%setup' in spec:
            new_spec = re.sub(
                r'(%setup\b[^\n]*)',
                lambda m: m.group(1) + '\n' + sed_cmd,
                spec,
                count=1,
            )
            if new_spec != spec:
                return new_spec, [fix_msg]

        return spec, []

    def _fix_legacy_macros(self, spec: str) -> tuple:
        """
        Replace legacy %py3_build and %py3_install macros with modern pyproject macros.
        
        This fixes packages that use pyproject.toml but have specs generated with
        old-style macros that expand to 'python3 setup.py build/install'.
        
        Conversions:
        - %py3_build -> %pyproject_wheel
        - %py3_install -> %pyproject_install
        - Also adds necessary BuildRequires and %generate_buildrequires section
        """
        applied = []
        content = spec
        
        # Replace macros
        if '%py3_build' in content:
            content = re.sub(r'%py3_build\b', '%pyproject_wheel', content)
            applied.append('Replaced %py3_build with %pyproject_wheel')
        
        if '%py3_install' in content:
            content = re.sub(r'%py3_install\b', '%pyproject_install', content)
            applied.append('Replaced %py3_install with %pyproject_install')
        
        # Also handle variants
        if '%python_build' in content:
            content = re.sub(r'%python_build\b', '%pyproject_wheel', content)
            applied.append('Replaced %python_build with %pyproject_wheel')
        
        if '%python_install' in content:
            content = re.sub(r'%python_install\b', '%pyproject_install', content)
            applied.append('Replaced %python_install with %pyproject_install')
        
        # Replace literal python3 setup.py commands
        if 'python3 setup.py build' in content:
            content = re.sub(r'/usr/bin/python3\s+setup\.py\s+build[^\n]*', '%pyproject_wheel', content)
            applied.append('Replaced literal "python3 setup.py build" with %pyproject_wheel')
        
        if 'python3 setup.py install' in content:
            content = re.sub(r'/usr/bin/python3\s+setup\.py\s+install[^\n]*', '%pyproject_install', content)
            applied.append('Replaced literal "python3 setup.py install" with %pyproject_install')
        
        # If we made any changes, ensure pyproject-rpm-macros is present
        if applied:
            if 'pyproject-rpm-macros' not in content:
                # Add pyproject-rpm-macros as BuildRequires
                if 'BuildRequires' in content:
                    content = re.sub(
                        r'(BuildRequires\s*:)',
                        'BuildRequires:  pyproject-rpm-macros\n\\1',
                        content,
                        count=1,
                    )
                    applied.append('Added BuildRequires: pyproject-rpm-macros')
            
            # Ensure %generate_buildrequires section exists
            if '%generate_buildrequires' not in content:
                # Insert before %build section
                content = re.sub(
                    r'^(%build)',
                    '%generate_buildrequires\n%pyproject_buildrequires\n\n\\1',
                    content,
                    flags=re.MULTILINE,
                    count=1,
                )
                applied.append('Added %generate_buildrequires section with %pyproject_buildrequires')
            elif '%pyproject_buildrequires' not in content:
                # %generate_buildrequires exists but no %pyproject_buildrequires
                content = re.sub(
                    r'^(%generate_buildrequires)',
                    '\\1\n%pyproject_buildrequires',
                    content,
                    flags=re.MULTILINE,
                    count=1,
                )
                applied.append('Added %pyproject_buildrequires to %generate_buildrequires section')
        
        return content, applied

    def _fix_wrong_module_glob(self, spec: str, items: list) -> tuple:
        """
        Replace a bad %pyproject_save_files <module> glob with +auto when the
        generated module name doesn't match the actual installed directory.

        Example: poetry-core installs as poetry/core/ (namespace pkg),
        not poetry_core/. Using +auto reads the dist-info RECORD directly
        without glob matching, which handles namespace packages correctly.

        NOTE: do NOT use bare * here — in the %install shell scriptlet, *
        is shell-expanded to the CWD's file listing before pyproject_save_files
        receives it (e.g. "README.md" gets passed and triggers a separate error).
        +auto is the officially supported way to skip glob-based detection.
        """
        applied = []
        content = spec

        for bad_name in items:
            # Replace the specific bad name (but not if already set to +auto)
            pattern = r'(%pyproject_save_files\s+)' + re.escape(bad_name) + r'(\b[^\n]*)'
            if re.search(pattern, content):
                content = re.sub(pattern, r'\1+auto', content, count=1)
                applied.append(
                    f'Replaced %pyproject_save_files {bad_name} with +auto '
                    f'(namespace package — module dir name differs from dist-info name)'
                )

        # Fallback: if items were empty but category matched, replace any non-+auto glob
        # This also catches the previous bad fix of bare * (shell-expanded by bash)
        if not applied:
            pattern_any = r'(%pyproject_save_files\s+)(?!\+auto)([^\s\n]+)'
            if re.search(pattern_any, content):
                content = re.sub(pattern_any, r'\1+auto', content, count=1)
                applied.append(
                    'Replaced %pyproject_save_files <module> with +auto '
                    '(module dir name differs from dist-info name)'
                )

        # When +auto is now in effect, strip any hardcoded /usr/lib/python*/site-packages/
        # paths that a previous unpackaged-files fix may have appended to %files.
        # +auto already generates those entries via %{pyproject_files}; keeping them causes
        # "File listed twice" RPM warnings.
        if applied:
            content = re.sub(
                r'\n/usr/lib/python[^\n]+(?:\n/usr/lib/python[^\n]+)*',
                '',
                content,
            )

        return content, applied

    def _fix_unpackaged_files(self, spec: str, error: dict) -> tuple:
        """
        Handle unpackaged files by making the %files section more comprehensive.
        
        For now, we use a simple approach: replace overly specific %files patterns
        with more inclusive ones. A more sophisticated approach would parse the
        actual list from the build log.
        """
        applied = []
        content = spec
        
        # Check if %files section only has %{python3_sitelib}/* or similar
        # If so, add common additional patterns
        if '%files' in content:
            # Check if we have a very minimal %files section
            files_section_match = re.search(
                r'(%files[^\n]*\n)(.*?)(?=\n%|\Z)', 
                content, 
                re.MULTILINE | re.DOTALL
            )
            
            if files_section_match:
                files_header = files_section_match.group(1)
                files_content = files_section_match.group(2).strip()
                
                # If %files only has sitelib entries, add common extras
                if '%{python3_sitelib}' in files_content and '%{_bindir}' not in files_content:
                    # Add %{_bindir}/* for scripts (with wildcard so it doesn't fail if empty)
                    new_files = files_header + '%{_bindir}/*\n' + files_content
                    
                    # Replace the old %files section with the new one
                    content = content.replace(
                        files_section_match.group(0),
                        new_files
                    )
                    applied.append('Added %{_bindir}/* to %files section for executable scripts')
        
        return content, applied
