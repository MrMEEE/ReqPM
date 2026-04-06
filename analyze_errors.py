#!/usr/bin/env python3
"""
Analyze build errors for project 10 to identify patterns for fixing engine
"""
import sqlite3
import sys
from collections import Counter, defaultdict
import re

def analyze_project_errors(project_id=10):
    conn = sqlite3.connect('db.sqlite3')
    cursor = conn.cursor()
    
    # Get all failed packages
    cursor.execute("""
        SELECT id, name, version, build_log, build_error_message, analyzed_errors
        FROM packages 
        WHERE project_id = ? AND build_status = 'failed'
    """, (project_id,))
    
    failed_packages = cursor.fetchall()
    
    print(f"Total failed packages: {len(failed_packages)}\n")
    
    # Error pattern analysis
    error_patterns = defaultdict(list)
    
    for pkg_id, name, version, log, error_msg, analyzed_errors in failed_packages:
        if not log:
            error_patterns['NO_LOG'].append(name)
            continue
            
        # Check for various error patterns
        if 'Bad file:' in log and 'No such file or directory' in log:
            # Extract the missing file
            match = re.search(r'Bad file: (.+?): (No such file|Ingen sådan fil)', log)
            if match:
                error_patterns['MISSING_SOURCE_FILE'].append(name)
        
        if 'Bad exit status from' in log:
            # Extract which scriptlet failed
            match = re.search(r'Bad exit status from .+\((%\w+)\)', log)
            if match:
                scriptlet = match.group(1)
                error_patterns[f'SCRIPLET_{scriptlet.upper()}'].append(name)
            else:
                error_patterns['SCRIPLET_UNKNOWN'].append(name)
        
        if 'nothing provides requested' in log.lower():
            error_patterns['MISSING_PROVIDES'].append(name)
        
        if 'No matching package to install' in log:
            error_patterns['MISSING_PACKAGE'].append(name)
        
        if "No module named" in log:
            error_patterns['MISSING_PYTHON_MODULE'].append(name)
        
        if 'ambiguous python shebang' in log.lower():
            error_patterns['AMBIGUOUS_SHEBANG'].append(name)
        
        if 'Empty %files file' in log and 'debugsourcefiles.list' in log:
            error_patterns['EMPTY_DEBUGINFO'].append(name)
        
        if 'Arch dependent binaries in noarch package' in log:
            error_patterns['ARCH_MISMATCH'].append(name)
        
        if 'fatal error:' in log and 'No such file or directory' in log:
            error_patterns['MISSING_HEADER'].append(name)
        
        if 'gcc' in log.lower() and ('command not found' in log.lower() or 'No such file' in log):
            error_patterns['MISSING_GCC'].append(name)
        
        if 'Installed (but unpackaged)' in log:
            error_patterns['UNPACKAGED_FILES'].append(name)
        
        if 'invalid pyproject.toml config' in log.lower() and 'license' in log.lower():
            error_patterns['INVALID_PYPROJECT_LICENSE'].append(name)
        
        if 'file' in log.lower() and 'conflicts between attempted installs' in log.lower():
            error_patterns['FILE_CONFLICT'].append(name)
        
        if 'Test' in log and ('FAILED' in log or 'ERROR' in log):
            if '%check' in log or 'pytest' in log or 'unittest' in log:
                error_patterns['TEST_FAILURE'].append(name)
        
        # Check for mock exit codes
        if 'Mock build failed with code 10' in error_msg:
            error_patterns['MOCK_EXIT_10'].append(name)
        elif 'Mock build failed with code' in error_msg:
            match = re.search(r'code (\d+)', error_msg)
            if match:
                code = match.group(1)
                error_patterns[f'MOCK_EXIT_{code}'].append(name)
    
    # Print summary
    print("=" * 80)
    print("ERROR PATTERN ANALYSIS")
    print("=" * 80)
    print()
    
    # Sort by frequency
    sorted_patterns = sorted(error_patterns.items(), key=lambda x: len(x[1]), reverse=True)
    
    for pattern, packages in sorted_patterns:
        print(f"{pattern}: {len(packages)} packages")
        if len(packages) <= 10:
            print(f"  Examples: {', '.join(packages)}")
        else:
            print(f"  Examples: {', '.join(packages[:10])} ... (+{len(packages)-10} more)")
        print()
    
    # Recommendations
    print("=" * 80)
    print("RECOMMENDATIONS FOR FIXING ENGINE")
    print("=" * 80)
    print()
    
    for pattern, packages in sorted_patterns:
        count = len(packages)
        if count < 5:
            continue
            
        if pattern == 'MISSING_SOURCE_FILE':
            print(f"✓ {count} packages: Missing source files")
            print("  → Add automatic source download/fetch logic")
            print("  → Implement: Check if source exists, if not, fetch from PyPI")
            print()
        
        elif pattern.startswith('SCRIPLET_'):
            scriptlet = pattern.replace('SCRIPLET_', '')
            print(f"✓ {count} packages: {scriptlet} scriptlet failures")
            print("  → Add error log parsing for specific %build/%install failures")
            print("  → Implement deeper error analysis to find root cause")
            print()
        
        elif pattern == 'MISSING_PROVIDES':
            print(f"✓ {count} packages: Missing dependencies (provides)")
            print("  → Already handled by error_analyzer.py 'missing_dependencies' pattern")
            print("  → Verify this pattern is being caught and applied")
            print()
        
        elif pattern == 'MISSING_PACKAGE':
            print(f"✓ {count} packages: Missing packages")
            print("  → Already handled by error_analyzer.py 'missing_packages' pattern")
            print("  → May need dependency build ordering")
            print()
        
        elif pattern == 'UNPACKAGED_FILES':
            print(f"✓ {count} packages: Unpackaged files")
            print("  → Add fixer to extract file list and add to %files section")
            print("  → Pattern: Extract paths from 'Installed (but unpackaged)' lines")
            print()
        
        elif pattern == 'TEST_FAILURE':
            print(f"✓ {count} packages: Test failures")
            print("  → Add option to disable tests (%global __pytest_args --nocheck)")
            print("  → Or add: %{pyproject_buildrequires -t} to skip tests")
            print()
        
        elif pattern == 'MOCK_EXIT_10':
            print(f"✓ {count} packages: Mock exit code 10")
            print("  → Exit code 10 = build dependencies not satisfied")
            print("  → Need to parse and add missing BuildRequires")
            print()
    
    conn.close()

if __name__ == '__main__':
    analyze_project_errors(10)
