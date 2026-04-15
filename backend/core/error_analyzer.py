"""
RPM Build Error Analyzer

Analyzes build logs to detect common errors and suggest fixes.
Based on awx-rpm-v2 geterrors script patterns.
"""
import re
from typing import List, Dict, Optional
from dataclasses import dataclass


@dataclass
class BuildError:
    """Represents a detected build error"""
    category: str
    message: str
    suggestion: Optional[str] = None
    items: List[str] = None
    
    def __post_init__(self):
        if self.items is None:
            self.items = []


class BuildErrorAnalyzer:
    """Analyzes RPM build logs to detect and categorize errors"""
    
    def __init__(self):
        self.patterns = self._initialize_patterns()
    
    def _initialize_patterns(self) -> Dict:
        """Initialize error detection patterns from awx-rpm-v2 geterrors"""
        return {
            'missing_dependencies': {
                'pattern': r'nothing provides requested (.+)',
                'category': 'Missing Dependencies',
                'suggestion': 'Add missing dependencies to spec file Requires/BuildRequires'
            },
            'missing_packages': {
                'pattern': r'No matching package to install: (.+)',
                'category': 'Missing Packages',
                'suggestion': 'Package not available in repositories, may need to be built first'
            },
            'missing_modules': {
                'pattern': r"No module named ['\"](.+)['\"]",
                'category': 'Missing Python Modules',
                'suggestion': 'Add Python module as BuildRequires (python3-{module})'
            },
            'missing_files': {
                'pattern': r'fatal error: (.+): No such file or directory',
                'category': 'Missing Header Files',
                'suggestion': 'Install development packages for required libraries'
            },
            'missing_pkgconfig': {
                # e.g.: Package 'libffi', required by 'virtual:world', not found
                'pattern': r"Package '([^']+)'.*not found",
                'category': 'Missing Header Files',
                'suggestion': 'Install development packages for required libraries',
            },
            'missing_pkgconfig_meson': {
                # e.g.: Dependency "ffi" not found, tried pkgconfig
                'pattern': r'Dependency "([^"]+)" not found, tried pkgconfig',
                'category': 'Missing Header Files',
                'suggestion': 'Install development packages for required libraries',
            },
            'ambiguous_shebang': {
                'pattern': r'ambiguous python shebang',
                'category': 'Ambiguous Python Shebang',
                'suggestion': 'Run fixpythonshebangs to correct Python shebangs',
                'capture_items': False,
            },
            'empty_debuginfo': {
                'pattern': r'Empty %files file.*debugsourcefiles\.list',
                'category': 'Empty Debug Info',
                'suggestion': 'Remove debug package generation (add %global debug_package %{nil})',
                'capture_items': False,
            },
            'rust_missing': {
                'pattern': r'Cargo, the Rust package manager, is not installed',
                'category': 'Missing Rust/Cargo',
                'suggestion': 'Add rust and cargo as BuildRequires',
                'capture_items': False,
            },
            'wheel_missing': {
                'pattern': r"error: invalid command 'bdist_wheel'",
                'category': 'Missing Python Wheel',
                'suggestion': 'Add python3-wheel as BuildRequires',
                'capture_items': False,
            },
            'gcc_missing': {
                'pattern': r"error: command 'gcc' failed: No such file or directory",
                'category': 'Missing GCC',
                'suggestion': 'Add gcc as BuildRequires',
                'capture_items': False,
            },
            'noarch_binaries': {
                'pattern': r'Arch dependent binaries in noarch package',
                'category': 'Architecture Mismatch',
                'suggestion': 'Remove BuildArch: noarch from spec file (package contains binaries)',
                'capture_items': False,
            },
            'bad_interpreter': {
                'pattern': r'bad interpreter: No such file or directory',
                'category': 'Bad Interpreter',
                'suggestion': 'Fix shebang lines in scripts'
            },
            'permission_denied': {
                'pattern': r'Permission denied',
                'category': 'Permission Denied',
                'suggestion': 'Check file permissions and build directory access'
            },
            'disk_space': {
                'pattern': r'No space left on device',
                'category': 'Disk Space',
                'suggestion': 'Free up disk space on build server'
            },
            'network_error': {
                'pattern': r'(Connection refused|Connection timed out|Network is unreachable)',
                'category': 'Network Error',
                'suggestion': 'Check network connectivity and repository availability'
            },
            'source_not_found': {
                'pattern': r'Bad file: .+: No such file or directory',
                'category': 'Source File Missing',
                'suggestion': 'Run fetch_source to download source files, or check Source0 URL in spec',
                'capture_items': False,
            },
            'macro_error': {
                'pattern': r'Macro .+ has illegal name',
                'category': 'RPM Macro Error',
                'suggestion': 'Fix macro syntax in spec file'
            },
            'syntax_error': {
                'pattern': r'(SyntaxError|IndentationError): .+',
                'category': 'Python Syntax Error',
                'suggestion': 'Fix Python code syntax errors in package'
            },
            'import_error': {
                'pattern': r'ImportError: .+',
                'category': 'Python Import Error',
                'suggestion': 'Ensure all required Python dependencies are installed'
            },
            'test_failed': {
                'pattern': r'(FAILED|ERROR) .+ test',
                'category': 'Test Failures',
                'suggestion': 'Fix failing tests or disable tests with --nocheck'
            },
            'file_conflict': {
                'pattern': r'file .+ conflicts between attempted installs',
                'category': 'File Conflicts',
                'suggestion': 'Resolve file conflicts between packages'
            },
            'unpackaged_files': {
                'pattern': r'Installed \(but unpackaged\) file\(s\) found:',
                'category': 'Unpackaged Files',
                'suggestion': 'Add missing files to %files section in spec',
                'capture_items': False,
            },
            'scriplet_error': {
                'pattern': r'(Bad exit status from|error: %[a-z]+ scriptlet failed)',
                'category': 'Scriplet Error',
                'suggestion': 'Fix errors in %pre, %post, %preun, or %postun scripts'
            },
            'deps_not_satisfied': {
                'pattern': r'(Not all dependencies satisfied|Some packages could not be found\.)',
                'category': 'Missing Packages',
                'suggestion': 'Some required packages are not available in the configured repositories',
                'capture_items': False,
            },
            'invalid_pyproject_license': {
                'pattern': r'invalid pyproject\.toml config: .project\.license.',
                'category': 'Invalid Pyproject License',
                'suggestion': 'Convert license = "SPDX" to license = {text = "SPDX"} in pyproject.toml (PEP 621 compliance)',
                'capture_items': False,
            },
            'setup_py_missing': {
                'pattern': r"can't open file.*setup\.py.*No such file or directory",
                'category': 'Missing Setup.py',
                'suggestion': 'Package uses pyproject.toml only - replace %py3_build/%py3_install with %pyproject_wheel/%pyproject_install',
                'capture_items': False,
            },
            'gxx_missing': {
                'pattern': r"(FileNotFoundError.*'g\+\+'|command 'g\+\+' failed: No such file)",
                'category': 'Missing G++ Compiler',
                'suggestion': 'Add gcc-c++ as BuildRequires',
                'capture_items': False,
            },
            'wrong_module_glob': {
                'pattern': r'Globs did not match any module: (\S+)',
                'category': 'Wrong Module Glob',
                'suggestion': 'Replace %pyproject_save_files module name with +auto (namespace package — reads dist-info RECORD without glob matching)',
            },
            'namespace_glob_dot': {
                'pattern': r'Attempted to use a namespaced package with \. in the glob: (\S+)',
                'category': 'Wrong Module Glob',
                'suggestion': 'Replace %pyproject_save_files module name with +auto (namespace package — reads dist-info RECORD without glob matching)',
            },
        }

    # Common English words that mock/dnf may echo back verbatim from error
    # messages — these are never valid package names.
    _NOISE_WORDS = {
        'not', 'all', 'some', 'be', 'could', 'dependencies', 'found',
        'packages', 'satisfied', 'no', 'is', 'the', 'and', 'or', 'of',
        'to', 'in', 'for', 'are', 'was', 'error', 'warning', 'note',
        'please', 'try', 'again', 'check', 'your', 'has', 'have',
    }

    def _is_package_name(self, item: str) -> bool:
        """
        Reject captured items that are clearly English noise words rather than
        real package/dep names.

        Valid RPM dep strings can contain spaces when version constraints are
        present, e.g. 'python3dist(hyperlink) >= 21' — we allow those.
        Pure prose words/sentences are rejected.
        """
        if item.endswith('.'):
            return False

        # If item contains spaces, only accept it when it looks like an RPM
        # dep with a version constraint: "<name> <op> <ver>"
        # where <op> is one of >=, <=, =, >, <, !=
        if ' ' in item:
            # Split on first space; the base name must look package-like
            base = item.split()[0]
            rest = item[len(base):].strip()
            # rest must start with a version operator
            if not re.match(r'^[><=!]', rest):
                return False
            # base must look like a package name (contains non-alpha chars or
            # is a known rpm-style dep like python3dist(...))
            if not re.search(r'[-_.()0-9:/]', base):
                return False

        if item.lower() in self._NOISE_WORDS:
            return False

        return True

    def analyze(self, log_output: str) -> List[BuildError]:
        """
        Analyze build log and extract errors
        
        Args:
            log_output: Raw build log output
            
        Returns:
            List of detected BuildError objects
        """
        errors = []
        
        # Check each pattern
        for error_type, config in self.patterns.items():
            pattern = config['pattern']
            category = config['category']
            suggestion = config.get('suggestion')
            
            matches = re.findall(pattern, log_output, re.IGNORECASE | re.MULTILINE)
            
            if matches:
                # If matches is list of tuples (from groups), flatten it
                if isinstance(matches[0], tuple):
                    items = [match[0] if isinstance(match, tuple) else match for match in matches]
                else:
                    items = matches
                
                # Remove duplicates while preserving order, dropping noise words
                # Only apply package-name filtering for patterns that capture
                # actual dependency/package names (capture_items=True, default True).
                capture_items = config.get('capture_items', True)
                seen = set()
                unique_items = []
                if capture_items:
                    for item in items:
                        item_clean = item.strip().strip("'\"")
                        if not item_clean or item_clean in seen:
                            continue
                        if not self._is_package_name(item_clean):
                            continue
                        seen.add(item_clean)
                        unique_items.append(item_clean)

                # Always create an error if the pattern matched, even when no
                # items survived filtering (sentinel / detection-only patterns).
                if matches:
                    error = BuildError(
                        category=category,
                        message=f"Found {len(unique_items)} occurrence(s)" if unique_items else "Detected",
                        suggestion=suggestion,
                        items=unique_items[:10]
                    )
                    errors.append(error)
        
        return errors
    
    def format_errors(self, errors: List[BuildError], format_type: str = 'text') -> str:
        """
        Format errors for display
        
        Args:
            errors: List of BuildError objects
            format_type: 'text', 'html', or 'json'
            
        Returns:
            Formatted error string
        """
        if not errors:
            return "No specific errors detected in build log."
        
        if format_type == 'html':
            return self._format_html(errors)
        elif format_type == 'json':
            import json
            return json.dumps([{
                'category': e.category,
                'message': e.message,
                'suggestion': e.suggestion,
                'items': e.items
            } for e in errors], indent=2)
        else:
            return self._format_text(errors)
    
    def _format_text(self, errors: List[BuildError]) -> str:
        """Format errors as plain text"""
        lines = ["Build Error Analysis:", "=" * 50, ""]
        
        for i, error in enumerate(errors, 1):
            lines.append(f"{i}. {error.category}")
            lines.append(f"   {error.message}")
            
            if error.items:
                lines.append("   Items:")
                for item in error.items[:5]:  # Show first 5
                    lines.append(f"     - {item}")
                if len(error.items) > 5:
                    lines.append(f"     ... and {len(error.items) - 5} more")
            
            if error.suggestion:
                lines.append(f"   Suggestion: {error.suggestion}")
            
            lines.append("")
        
        return "\n".join(lines)
    
    def _format_html(self, errors: List[BuildError]) -> str:
        """Format errors as HTML"""
        html = ['<div class="error-analysis">']
        html.append('<h4>Build Error Analysis</h4>')
        
        for error in errors:
            html.append(f'<div class="error-item">')
            html.append(f'<strong>{error.category}</strong>: {error.message}')
            
            if error.items:
                html.append('<ul>')
                for item in error.items[:5]:
                    html.append(f'<li>{item}</li>')
                if len(error.items) > 5:
                    html.append(f'<li><em>... and {len(error.items) - 5} more</em></li>')
                html.append('</ul>')
            
            if error.suggestion:
                html.append(f'<p class="suggestion"><em>💡 {error.suggestion}</em></p>')
            
            html.append('</div>')
        
        html.append('</div>')
        return ''.join(html)
    
    def get_summary(self, errors: List[BuildError]) -> str:
        """Get a one-line summary of errors"""
        if not errors:
            return "No errors detected"
        
        categories = [e.category for e in errors]
        if len(categories) == 1:
            return categories[0]
        elif len(categories) == 2:
            return f"{categories[0]}, {categories[1]}"
        else:
            return f"{categories[0]}, {categories[1]}, +{len(categories)-2} more"
