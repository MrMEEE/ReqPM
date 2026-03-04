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
    'Ambiguous Python Shebang',
    'Empty Debug Info',
    'Architecture Mismatch',
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

            elif category == 'Ambiguous Python Shebang':
                content, applied = self._fix_shebang(content)
                fixes.extend(applied)

            elif category == 'Empty Debug Info':
                content, applied = self._fix_debuginfo(content)
                fixes.extend(applied)

            elif category == 'Architecture Mismatch':
                content, applied = self._fix_arch_mismatch(content)
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
