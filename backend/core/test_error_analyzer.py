#!/usr/bin/env python
"""
Test script for BuildErrorAnalyzer
"""
from error_analyzer import BuildErrorAnalyzer

# Sample build log with various errors
test_log = """
ERROR: nothing provides requested python3-cryptography
ERROR: nothing provides requested gcc
No matching package to install: python3-devel
ModuleNotFoundError: No module named 'setuptools'
fatal error: Python.h: No such file or directory
error: command 'gcc' failed: No such file or directory
error: invalid command 'bdist_wheel'
Error: line 2: Arch dependent binaries in noarch package
warning: File listed twice: /usr/lib/.build-id
error: Empty %files file /builddir/build/BUILD/debugsourcefiles.list
/usr/bin/env: 'python': No such file or directory
error: Bad file: ./SOURCES/example-1.0.tar.gz: No such file or directory
"""

def main():
    analyzer = BuildErrorAnalyzer()
    errors = analyzer.analyze(test_log)
    
    print("=" * 80)
    print("Build Error Analysis Test")
    print("=" * 80)
    print(f"\nFound {len(errors)} error categories:\n")
    
    for i, error in enumerate(errors, 1):
        print(f"{i}. {error.category}")
        print(f"   Message: {error.message}")
        if error.items:
            print(f"   Items ({len(error.items)}):")
            for item in error.items[:5]:
                print(f"     - {item}")
            if len(error.items) > 5:
                print(f"     ... and {len(error.items) - 5} more")
        if error.suggestion:
            print(f"   💡 Suggestion: {error.suggestion}")
        print()
    
    print("=" * 80)
    print("\nFormatted Output (text):\n")
    print(analyzer.format_errors(errors, format_type='text'))
    
    print("\n" + "=" * 80)
    print("\nSummary:", analyzer.get_summary(errors))
    print("=" * 80)

if __name__ == '__main__':
    main()
