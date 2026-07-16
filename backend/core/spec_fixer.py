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

        # --- Always-on cleanup: remove known-invalid BuildRequires lines ---
        # These are leftover artefacts from earlier (buggy) fixer runs and must
        # be removed unconditionally, regardless of the current error category.
        _ALWAYS_REMOVE_BR = re.compile(
            r'^\s*BuildRequires\s*:.*?'
            r'(?:/usr/bin/pathfix\.py'
            r'|python3?-pathfix'
            r'|python3?-toml(?:lib)?'   # tomllib is built-in since Python 3.11
            r'|python3?-pip'            # pip is already in the mock buildroot
            r'|libpython3\.\d+-devel'   # version-specific; use python3-devel instead
            r'|python3?-calver'         # calver not in RHEL 10; strip from pyproject.toml instead
            r'|python3?-pytest[-_]runner'  # test-only dep, not needed for building
            r'|python3?-poetry(?![-_]core)'  # full poetry not in RHEL 10 (poetry-core is handled separately)
            r')\s*\n?',
            re.MULTILINE | re.IGNORECASE,
        )
        cleaned, n_removed = _ALWAYS_REMOVE_BR.subn('', content)
        if n_removed:
            content = cleaned
            fixes.append(f'Removed {n_removed} known-invalid BuildRequires line(s)')

        # Remove bare pathfix.py calls left by old fixer
        cleaned2, n2 = re.subn(
            r'^\s*pathfix\.py\s+.*\n?',
            '',
            content,
            flags=re.MULTILINE,
        )
        if n2:
            content = cleaned2
            fixes.append(f'Removed {n2} stale pathfix.py call(s)')

        # Ensure %generate_buildrequires + %pyproject_buildrequires is present
        # whenever %pyproject_wheel is used.  pyproject-rpm-macros ≥ 1.18 calls
        # `python3 -m pip wheel` internally, so pip must be available.
        # %pyproject_buildrequires generates `python3dist(pip) >= 19` as a
        # dynamic BR which mock resolves to python3-pip from the project repo.
        if '%pyproject_wheel' in content and '%generate_buildrequires' not in content:
            content = re.sub(
                r'^(%build\b)',
                '%generate_buildrequires\n%pyproject_buildrequires\n\n\\1',
                content,
                count=1,
                flags=re.MULTILINE,
            )
            fixes.append('Added %generate_buildrequires/%pyproject_buildrequires (required for pip in mock)')
        elif '%pyproject_wheel' in content and '%pyproject_buildrequires' not in content:
            content = re.sub(
                r'^(%generate_buildrequires\b)',
                '\\1\n%pyproject_buildrequires',
                content,
                count=1,
                flags=re.MULTILINE,
            )
            fixes.append('Added %pyproject_buildrequires to existing %generate_buildrequires')

        # VCS build tools that are not available in RHEL 10 standard repos.
        # When these appear as missing packages the correct fix is to patch
        # pyproject.toml in %prep to remove them and use a static version.
        _VCS_TOOLS = {'hatch-vcs', 'hatch_vcs', 'python3-hatch-vcs',
                      'setuptools-scm', 'setuptools_scm', 'python3-setuptools-scm',
                      'flit-scm', 'flit_scm', 'python3-flit-scm',
                      'calver', 'python3-calver',
                      'versioneer'}
        # Normalised bare names (lower, dash-normalised) for matching python3dist() items
        _VCS_TOOL_BARE = {'hatch-vcs', 'hatch_vcs', 'setuptools-scm',
                          'setuptools_scm', 'flit-scm', 'flit_scm',
                          'calver', 'versioneer'}

        for error in analyzed_errors:
            category = error.get('category', '')
            items = error.get('items', [])

            if category in ('Missing Packages', 'Missing Dependencies'):
                # Convert python3dist(pkgname) virtual-provide strings to the
                # installable RPM package name (python3-pkgname).  Version
                # constraints are dropped because static BuildRequires don't
                # carry version pinning in the same way.
                converted = []
                for raw in items:
                    raw = raw.strip().strip("'\"")
                    m = re.match(r'^python3?dist\(([^)]+)\)', raw)
                    if m:
                        pkg_name = m.group(1).replace('.', '-').replace('_', '-').lower()
                        # If this is a VCS build tool, apply the VCS fix instead
                        if pkg_name in _VCS_TOOL_BARE:
                            content, applied = self._fix_vcs_build_tool(content)
                            fixes.extend(applied)
                            continue
                        converted.append(f'python3-{pkg_name}')
                    else:
                        bare = raw.replace('_', '-').lower()
                        if raw in _VCS_TOOLS or bare in _VCS_TOOL_BARE:
                            content, applied = self._fix_vcs_build_tool(content)
                            fixes.extend(applied)
                            continue
                        converted.append(raw)
                content, applied = self._add_buildrequires_items(content, converted)
                fixes.extend(applied)

            elif category == 'Missing Python Modules':
                # Convert module names to python3-<module> package names.
                # Special case: X.version items mean the installed RPM for package X
                # is missing its version.py submodule (a common hatch-vcs packaging gap).
                # Adding 'python3-X-version' as a BuildRequires doesn't help — fix the
                # installed package in-place inside %prep instead.
                packages = []
                for item in items:
                    mod = item.strip().strip("'\"")
                    if mod == 'packaging':
                        continue
                    # Detect 'X.version' (missing version submodule) pattern
                    if re.fullmatch(r'[\w]+\.version', mod):
                        parent = mod.split('.')[0]
                        content, applied = self._fix_missing_version_submodule(content, parent)
                        fixes.extend(applied)
                        continue
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
        # Known-invalid pseudo-package names that are never installable
        _INVALID = {
            '/usr/bin/pathfix.py', 'pathfix', 'python3-pathfix', 'pathfix.py',
            'python3-toml',  # replaced by tomllib built-in in Python 3.11+
        }

        for raw_item in items:
            item = raw_item.strip().strip("'\"")
            if not item:
                continue
            # Reject obvious noise: plain English words or items containing spaces
            if item.lower() in _NOISE or item.endswith('.') or ' ' in item:
                logger.debug(f'SpecFixer: skipping noise item: {item!r}')
                continue
            # Reject file paths — these are never valid RPM package names
            if item.startswith('/'):
                logger.debug(f'SpecFixer: skipping file path item: {item!r}')
                continue
            # Reject known-invalid pseudo-packages
            if item in _INVALID or item.lower() in _INVALID:
                logger.debug(f'SpecFixer: skipping known-invalid item: {item!r}')
                continue
            # Reject bare python3dist() virtual provides — they are Provides:
            # values, not installable package names.  Callers should convert
            # them to python3-<name> before calling this method.
            if re.match(r'^python3?dist\(', item):
                logger.debug(f'SpecFixer: skipping virtual provide: {item!r}')
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

    def _fix_missing_version_submodule(self, spec: str, parent_pkg: str) -> tuple:
        """
        Fix 'No module named X.version' errors that occur when an RPM is built
        without the hatch-vcs-generated version.py submodule.

        Injects a sitecustomize shim into %generate_buildrequires so the missing
        X.version module is synthesized before pyproject_buildrequires imports
        the package (where this error usually happens).

        This avoids writing into system site-packages (often read-only for the
        build user inside mock) and instead uses PYTHONPATH to preload a tiny
        compatibility shim for the current shell command.

        Uses a shell heredoc (not ``python3 -c '...'``) so that the Python code
        retains proper newlines — shell line-continuations in ``python3 -c``
        strip all newlines and produce a SyntaxError.

        This is idempotent: the snippet is a no-op if version.py already exists,
        and will not be inserted again if a correct %generate_buildrequires
        repair is already present.
        """
        marker = f'# reqpm: repair {parent_pkg}.version'
        heredoc_tag = 'REQPM_REPAIR_EOF'

        snippet = (
            f'{marker}\n'
            f"mkdir -p .reqpm_pyshim\n"
            f"cat > .reqpm_pyshim/sitecustomize.py << '{heredoc_tag}'\n"
            f'import importlib.metadata\n'
            f'import re\n'
            f'import sys\n'
            f'import types\n'
            f"_pkg = '{parent_pkg}'\n"
            f"_mod = f'{parent_pkg}.version'\n"
            f'if _mod not in sys.modules:\n'
            f'    _shim = types.ModuleType(_mod)\n'
            f'    try:\n'
            f'        _ver = importlib.metadata.version(_pkg)\n'
            f'    except Exception:\n'
            f"        _ver = '0'\n"
            f'    _parts = [int(p) for p in re.findall(r"\\d+", _ver)]\n'
            f'    _ver_tuple = tuple(_parts) if _parts else (0,)\n'
            f'    _shim.__version__ = _ver\n'
            f'    _shim.version = _ver\n'
            f'    _shim.__version_tuple__ = _ver_tuple\n'
            f'    _shim.__version_info__ = _ver_tuple\n'
            f'    sys.modules[_mod] = _shim\n'
            f'{heredoc_tag}'
            f"\nexport PYTHONPATH=\"$PWD/.reqpm_pyshim${{PYTHONPATH:+:$PYTHONPATH}}\""
        )

        generate_block_match = re.search(
            r'%generate_buildrequires\b[\s\S]*?(?=\n%[a-zA-Z]|\Z)',
            spec,
            re.DOTALL,
        )
        generate_block = generate_block_match.group(0) if generate_block_match else ''
        bad_files_present = bool(re.search(
            r'^\s*(?:%\{python3_sitelib\}|/usr/lib/python[0-9.]+/site-packages)/'
            + re.escape(parent_pkg)
            + r'/version\.py\s*$',
            spec,
            re.MULTILINE,
        ))

        # Already correctly patched in the right section — nothing to do.
        # Use '\n' suffix so we don't false-positive on REQPM_REPAIR_EOF that
        # appears mid-line (e.g. as a prefix of "REQPM_REPAIR_EOF' || true").
        if (
            marker in generate_block
            and (snippet + '\n' in generate_block or generate_block.endswith(snippet))
            and not bad_files_present
        ):
            return spec, []

        # Remove any existing marker snippet variants (old %prep placement,
        # old python3 -c style, or malformed heredoc variants), then inject a
        # clean snippet in %generate_buildrequires.
        block_pattern = re.compile(
            re.escape(marker) + r'[\s\S]*?^' + re.escape(heredoc_tag) + r'[ \t]*$\n?',
            re.DOTALL | re.MULTILINE,
        )
        inline_pattern = re.compile(
            re.escape(marker) + r'\npython3 -c "[\s\S]*?" \|\| true\n?',
            re.DOTALL,
        )

        cleaned_spec = block_pattern.sub('', spec)
        cleaned_spec = inline_pattern.sub('', cleaned_spec)

        # Remove incorrect AI-suggested %files entries that reference a
        # system site-packages version.py path for this package.  That path is
        # outside buildroot and should not be listed in packaged files.
        bad_files_pattern = re.compile(
            r'^\s*(?:%\{python3_sitelib\}|/usr/lib/python[0-9.]+/site-packages)/'
            + re.escape(parent_pkg)
            + r'/version\.py\s*$\n?',
            re.MULTILINE,
        )
        cleaned_spec = bad_files_pattern.sub('', cleaned_spec)
        cleaned_spec = re.sub(r'\n{3,}', '\n\n', cleaned_spec)

        # Insert at start of %generate_buildrequires, before
        # pyproject_buildrequires executes.
        new_spec = re.sub(
            r'(%generate_buildrequires\b[^\n]*\n)',
            lambda m: m.group(1) + snippet + '\n',
            cleaned_spec,
            count=1,
        )

        if new_spec == cleaned_spec:
            # Fallback for specs without %generate_buildrequires: inject in %prep.
            new_spec = re.sub(
                r'(%prep\b[^\n]*\n)',
                lambda m: m.group(1) + snippet + '\n',
                cleaned_spec,
                count=1,
            )

        if new_spec != spec:
            return new_spec, [f'Auto-fixed missing {parent_pkg}.version before %generate_buildrequires']
        return spec, []

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

    def _fix_vcs_build_tool(self, spec: str) -> tuple:
        """
        Fix specs that depend on VCS build tools (hatch-vcs, setuptools-scm, etc.)
        that are not available in RHEL 10.

        Strategy:
        1. Add a sed command in %prep to strip VCS build plugins from
           pyproject.toml's build-system.requires so %generate_buildrequires
           won't request them.
        2. Patch any `version.source = "vcs"` line to use `version.source = "regex"`
           with a static version file, so hatchling can still resolve the version.
        3. Add SETUPTOOLS_SCM_PRETEND_VERSION to the %pyproject_wheel call in %build
           as a belt-and-suspenders guard for other VCS tools.
        4. Remove any stale `BuildRequires: hatch-vcs` / `python3-hatch-vcs` lines.
        """
        applied = []
        content = spec

        # --- remove any existing stale VCS build tool BRs ---
        _vcs_br_pat = re.compile(
            r'^\s*BuildRequires\s*:.*?\b(hatch[-_]vcs|setuptools[-_]scm|flit[-_]scm|versioneer|calver|poetry[-_]core)\b.*\n?',
            re.MULTILINE | re.IGNORECASE,
        )
        cleaned, n = _vcs_br_pat.subn('', content)
        if n:
            content = cleaned
            applied.append('Removed invalid VCS build tool BuildRequires')

        # --- build a composite sed command we will inject into %prep ---
        VCS_PREP_MARKER = '# Remove VCS build plugins not available in RHEL 10'

        # Only inject once
        if VCS_PREP_MARKER not in content:
            prep_patch = (
                f'{VCS_PREP_MARKER}\n'
                'if [ -f pyproject.toml ]; then\n'
                '  sed -i \'/"hatch-vcs/d; /"setuptools-scm/d; /"flit-scm/d; /"versioneer/d\' pyproject.toml\n'
                '  # Switch flit_scm requires entry and build backend to flit_core\n'
                '  sed -i \'s|"flit_scm"|"flit_core"|g; s|flit_scm:buildapi|flit_core.buildapi|g; s|build-backend = "flit_scm"|build-backend = "flit_core.buildapi"|\' pyproject.toml\n'
                '  # Switch VCS version source → regex source (reads __version__ from file)\n'
                '  sed -i \'s/version\\.source = "vcs"/version.source = "regex"/g\' pyproject.toml\n'
                '  # Also handle [tool.hatch.version] section style\n'
                '  sed -i \'/^source = "vcs"$/s//source = "regex"/\' pyproject.toml\n'
                '  # Ensure the version file exists (hatchling regex source default)\n'
                '  VERSION_FILE=$(grep -r "version\\.path" pyproject.toml 2>/dev/null | head -1 | grep -oP \'(?<=path = ")[^"]+\')\n'
                '  [ -z "$VERSION_FILE" ] && VERSION_FILE=$(find src -name "_version.py" -o -name "__version__.py" -o -name "version.py" 2>/dev/null | head -1)\n'
                '  if [ -n "$VERSION_FILE" ] && [ ! -f "$VERSION_FILE" ]; then\n'
                '    mkdir -p "$(dirname $VERSION_FILE)"\n'
                '    echo "__version__ = \\"%{version}\\"" > "$VERSION_FILE"\n'
                '  fi\n'
                'fi\n'
            )

            # Insert at the end of the %prep section (before %build)
            if '%setup' in content:
                # Insert after the last line of %setup block
                content = re.sub(
                    r'(%setup[^\n]*\n(?:(?!%(?:build|install|check|files|changelog|package|description|prep))[^\n]*\n)*)',
                    r'\1' + prep_patch + '\n',
                    content,
                    count=1,
                )
                applied.append('Added pyproject.toml VCS plugin removal in %prep')
            elif '%prep' in content:
                content = re.sub(
                    r'(%prep\s*\n)',
                    r'\1' + prep_patch + '\n',
                    content,
                    count=1,
                )
                applied.append('Added pyproject.toml VCS plugin removal in %prep')

        # --- ensure SETUPTOOLS_SCM_PRETEND_VERSION in %build ---
        if '%pyproject_wheel' in content and 'SETUPTOOLS_SCM_PRETEND_VERSION' not in content:
            content = re.sub(
                r'^(%pyproject_wheel\b)',
                r'SETUPTOOLS_SCM_PRETEND_VERSION=%{version} \1',
                content,
                flags=re.MULTILINE,
                count=1,
            )
            applied.append('Added SETUPTOOLS_SCM_PRETEND_VERSION to %pyproject_wheel')

        return content, applied

    def _fix_shebang(self, spec: str) -> tuple:
        """
        Fix ambiguous Python shebangs using the modern %py3_shebang_fix macro.

        The old approach of adding `BuildRequires: /usr/bin/pathfix.py` is wrong:
        /usr/bin/pathfix.py is a file, not an installable RPM package.  Modern
        RHEL 10 pyproject-rpm-macros handle shebangs automatically via brp macros,
        but when an explicit fix is still needed the correct approach is to call
        %py3_shebang_fix (provided by python3-devel) in %install.
        """
        applied = []
        content = spec

        shebang_fix = '%py3_shebang_fix %{buildroot}%{_bindir}/* 2>/dev/null || true'

        # Only insert if not already present
        if shebang_fix not in content:
            # Insert after %pyproject_install or %py3_install, before save_files
            for anchor in ('%pyproject_install', '%py3_install'):
                if anchor in content:
                    content = re.sub(
                        rf'({re.escape(anchor)}\b[^\n]*)',
                        rf'\1\n{shebang_fix}',
                        content,
                        count=1,
                    )
                    applied.append('Added %py3_shebang_fix call in %install')
                    break

        # Remove any stale /usr/bin/pathfix.py BuildRequires lines left by
        # old versions of this fixer — they reference a file path, not a package.
        cleaned, n = re.subn(
            r'^\s*BuildRequires\s*:.*?/usr/bin/pathfix\.py.*\n?',
            '',
            content,
            flags=re.MULTILINE,
        )
        if n:
            content = cleaned
            applied.append('Removed invalid BuildRequires: /usr/bin/pathfix.py')

        # Also remove bare pathfix calls added by old fixer runs
        cleaned2, n2 = re.subn(
            r'^\s*pathfix\.py\s+-pni[^\n]*\n?',
            '',
            content,
            flags=re.MULTILINE,
        )
        if n2:
            content = cleaned2
            applied.append('Removed stale pathfix.py calls')

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

        # If a previous fix left an extra glob after +auto, normalize it away.
        # Use only horizontal whitespace after +auto so we never swallow a
        # newline and accidentally merge with the next spec directive.
        content, cleaned = re.subn(
            r'(%pyproject_save_files\s+\+auto)[ \t]+[^\n\s]+',
            r'\1',
            content,
            count=1,
        )
        if cleaned:
            applied.append('Normalized %pyproject_save_files +auto to remove trailing glob')

        # Repair malformed lines where %files arguments were accidentally
        # appended to %pyproject_save_files.
        content, repaired = re.subn(
            r'^%pyproject_save_files\s+\+auto\s+(?:-f\s+)?%\{pyproject_files\}\s*$',
            '%pyproject_save_files +auto\n\n%files -f %{pyproject_files}',
            content,
            flags=re.MULTILINE,
            count=1,
        )
        if repaired:
            applied.append('Repaired malformed %pyproject_save_files/%files line split')

        # If %files -f %{pyproject_files} disappeared entirely, restore it.
        if '%pyproject_save_files +auto' in content and '%files -f %{pyproject_files}' not in content:
            content = re.sub(
                r'(^%pyproject_save_files\s+\+auto\s*$)',
                r'\1\n\n%files -f %{pyproject_files}',
                content,
                flags=re.MULTILINE,
                count=1,
            )
            applied.append('Restored missing %files -f %{pyproject_files} section')

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
