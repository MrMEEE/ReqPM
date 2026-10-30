"""
Spec helpers that make a package ignore upstream version requirements on a dependency.

The generated snippet runs at the end of %prep and strips version specifiers for one
dependency from the upstream build metadata, so both the generated BuildRequires and
the runtime Requires become unversioned for that dependency.
"""
import re

MARKER_PREFIX = '# ReqPM: ignore version requirement for '
_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
_PREP_RE = re.compile(r'^%prep\b')
_SECTION_RE = re.compile(
    r'^%(generate_buildrequires|build|install|check|files|changelog|pre|post|preun|postun|'
    r'pretrans|posttrans|package|description|conf)\b'
)


def normalize_dependency_name(name: str) -> str:
    name = (name or '').strip()
    if not _NAME_RE.match(name):
        raise ValueError(f'Invalid dependency name: {name!r}')
    return re.sub(r'[-_.]+', '-', name).lower()


def ignored_version_requirements(spec_content: str) -> list[str]:
    return [
        line.strip()[len(MARKER_PREFIX):].strip()
        for line in (spec_content or '').splitlines()
        if line.strip().startswith(MARKER_PREFIX)
    ]


def _snippet(name: str) -> list[str]:
    pattern = '[-_.]'.join(part for part in name.split('-'))
    files = (
        r"\( -name pyproject.toml -o -name setup.cfg -o -name setup.py "
        r"-o -name 'requirements*.txt' \)"
    )
    pep508 = (
        rf"s/(^|[^A-Za-z0-9._-])({pattern})(\[[^]]*\])?[[:space:]]*"
        r"""(\([^)]*\)|(<=?|>=?|[=!~]=)[^\"';#]*)/\1\2\3/gI"""
    )
    poetry = rf"""s/^([[:space:]]*[\"']?{pattern}[\"']?[[:space:]]*=[[:space:]]*)\"[^\"]*\"/\1\"*\"/I"""
    return [
        f'{MARKER_PREFIX}{name}',
        f'find %{{_builddir}} -maxdepth 4 -type f {files} '
        f'-exec sed -E -i -e "{pep508}" -e "{poetry}" {{}} + || true',
    ]


def remove_ignore_version_requirement(spec_content: str, dependency_name: str) -> tuple[str, bool]:
    """Remove the snippet added by add_ignore_version_requirement. Returns (new_spec, changed)."""
    name = normalize_dependency_name(dependency_name)
    lines = spec_content.splitlines()
    out = []
    changed = False
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if (
            stripped.startswith(MARKER_PREFIX)
            and normalize_dependency_name(stripped[len(MARKER_PREFIX):]) == name
        ):
            changed = True
            if out and not out[-1].strip():
                out.pop()
            i += 1
            if i < len(lines) and lines[i].lstrip().startswith('find %{_builddir}'):
                i += 1
            continue
        out.append(lines[i])
        i += 1
    if not changed:
        return spec_content, False
    new_content = '\n'.join(out)
    if spec_content.endswith('\n'):
        new_content += '\n'
    return new_content, True


def add_ignore_version_requirement(spec_content: str, dependency_name: str) -> tuple[str, bool]:
    """Return (new_spec, changed). Raises ValueError if the spec has no %prep section."""
    name = normalize_dependency_name(dependency_name)
    if name in {n.lower() for n in ignored_version_requirements(spec_content)}:
        return spec_content, False

    lines = spec_content.splitlines()
    prep_index = next((i for i, line in enumerate(lines) if _PREP_RE.match(line)), None)
    if prep_index is None:
        raise ValueError('Spec file has no %prep section')

    end = next(
        (i for i in range(prep_index + 1, len(lines)) if _SECTION_RE.match(lines[i])),
        len(lines),
    )
    insert_at = end
    while insert_at > prep_index + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1

    snippet = ['', *_snippet(name)]
    new_lines = lines[:insert_at] + snippet + lines[insert_at:]
    new_content = '\n'.join(new_lines)
    if spec_content.endswith('\n'):
        new_content += '\n'
    return new_content, True
