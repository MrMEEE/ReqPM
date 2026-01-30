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
            'ambiguous_shebang': {
                'pattern': r'ambiguous python shebang',
                'category': 'Ambiguous Python Shebang',
                'suggestion': 'Run fixpythonshebangs to correct Python shebangs'
            },
            'empty_debuginfo': {
                'pattern': r'Empty %files file.*debugsourcefiles\.list',
                'category': 'Empty Debug Info',
                'suggestion': 'Remove debug package generation (add %global debug_package %{nil})'
            },
            'rust_missing': {
                'pattern': r'Cargo, the Rust package manager, is not installed',
                'category': 'Missing Rust/Cargo',
                'suggestion': 'Add rust and cargo as BuildRequires'
            },
            'wheel_missing': {
                'pattern': r"error: invalid command 'bdist_wheel'",
                'category': 'Missing Python Wheel',
                'suggestion': 'Add python3-wheel as BuildRequires'
            },
            'gcc_missing': {
                'pattern': r"error: command 'gcc' failed: No such file or directory",
                'category': 'Missing GCC',
                'suggestion': 'Add gcc as BuildRequires'
            },
            'noarch_binaries': {
                'pattern': r'Arch dependent binaries in noarch package',
                'category': 'Architecture Mismatch',
                'suggestion': 'Remove BuildArch: noarch from spec file (package contains binaries)'
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
                'suggestion': 'Run fetch_source to download source files, or check Source0 URL in spec'
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
                'pattern': r'Installed .+ but unpackaged .+ :\s+(.+)',
                'category': 'Unpackaged Files',
                'suggestion': 'Add missing files to %files section in spec'
            },
            'scriplet_error': {
                'pattern': r'(Bad exit status from|error: %[a-z]+ scriptlet failed)',
                'category': 'Scriplet Error',
                'suggestion': 'Fix errors in %pre, %post, %preun, or %postun scripts'
            },
        }
    
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
                
                # Remove duplicates while preserving order
                seen = set()
                unique_items = []
                for item in items:
                    item_clean = item.strip()
                    if item_clean and item_clean not in seen:
                        seen.add(item_clean)
                        unique_items.append(item_clean)
                
                if unique_items:
                    # Create error with first occurrence message
                    error = BuildError(
                        category=category,
                        message=f"Found {len(unique_items)} occurrence(s)",
                        suggestion=suggestion,
                        items=unique_items[:10]  # Limit to 10 items
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
