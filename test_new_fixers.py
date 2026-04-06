#!/usr/bin/env python3
"""
Test the new error patterns and fixers
"""
import sys
sys.path.insert(0, '/home/mj/Downloads/ReqPM')

from backend.core.error_analyzer import BuildErrorAnalyzer
from backend.core.spec_fixer import SpecFixer

print("=" * 80)
print("TESTING NEW ERROR PATTERNS")
print("=" * 80)

analyzer = BuildErrorAnalyzer()
fixer = SpecFixer()

# Test 1: Missing setup.py detection
print("\n1. Testing Missing Setup.py Detection")
log1 = """
/usr/bin/python3: can't open file '/builddir/build/BUILD/click-8.1.8/setup.py': [Errno 2] No such file or directory
error: Bad exit status from /var/tmp/rpm-tmp.s5qdk0 (%build)
"""
errors1 = analyzer.analyze(log1)
print(f"   Detected {len(errors1)} errors:")
for e in errors1:
    print(f"   - {e.category}: {e.suggestion}")

# Test 2: Missing g++ detection
print("\n2. Testing Missing G++ Detection")
log2 = """
FileNotFoundError: [Errno 2] No such file or directory: 'g++'
error: Bad exit status from /var/tmp/rpm-tmp.qorZBn (%build)
"""
errors2 = analyzer.analyze(log2)
print(f"   Detected {len(errors2)} errors:")
for e in errors2:
    print(f"   - {e.category}: {e.suggestion}")

# Test 3: Invalid pyproject license detection (existing)
print("\n3. Testing Invalid Pyproject License Detection")
log3 = """
ValueError: invalid pyproject.toml config: `project.license`.
configuration error: `project.license` must be valid exactly by one definition (2 matches found)
error: Bad exit status from /var/tmp/rpm-tmp.kQEBVr (%build)
"""
errors3 = analyzer.analyze(log3)
print(f"   Detected {len(errors3)} errors:")
for e in errors3:
    print(f"   - {e.category}: {e.suggestion}")

print("\n" + "=" * 80)
print("TESTING SPEC FIXERS")
print("=" * 80)

# Test 4: Legacy macro fixer
print("\n4. Testing Legacy Macro Fixer")
spec_old = """Name:           python3-click
Version:        8.1.8
BuildRequires:  python-devel

%prep
%autosetup -n click-%{version}

%build
%py3_build

%install
%py3_install

%files
%{python3_sitelib}/*
"""

error_setup_py = [{'category': 'Missing Setup.py', 'items': []}]
new_spec, fixes_applied = fixer.apply_fixes(spec_old, error_setup_py)
print(f"   Fixes applied: {len(fixes_applied)}")
for fix in fixes_applied:
    print(f"   - {fix}")

if '%pyproject_wheel' in new_spec and '%pyproject_install' in new_spec:
    print("   ✓ Macros successfully replaced!")
else:
    print("   ✗ Macro replacement failed!")

# Test 5: G++ fixer
print("\n5. Testing G++ Fixer")
spec_base = """Name:           python3-grpcio
BuildRequires:  python-devel
BuildRequires:  gcc
"""

error_gxx = [{'category': 'Missing G++ Compiler', 'items': []}]
new_spec2, fixes_applied2 = fixer.apply_fixes(spec_base, error_gxx)
print(f"   Fixes applied: {len(fixes_applied2)}")
for fix in fixes_applied2:
    print(f"   - {fix}")

if 'gcc-c++' in new_spec2:
    print("   ✓ gcc-c++ successfully added!")
else:
    print("   ✗ gcc-c++ addition failed!")

# Test 6: Unpackaged files fixer
print("\n6. Testing Unpackaged Files Fixer")
spec_files = """Name:           python3-test
%files
%{python3_sitelib}/*
"""

error_unpackaged = [{'category': 'Unpackaged Files', 'items': ['/usr/bin/test-script']}]
new_spec3, fixes_applied3 = fixer.apply_fixes(spec_files, error_unpackaged)
print(f"   Fixes applied: {len(fixes_applied3)}")
for fix in fixes_applied3:
    print(f"   - {fix}")

if '%{_bindir}' in new_spec3:
    print("   ✓ _bindir pattern successfully added!")
else:
    print("   ✗ _bindir pattern addition failed!")

print("\n" + "=" * 80)
print("AUTO-FIXABLE CATEGORIES")
print("=" * 80)
from backend.core.spec_fixer import AUTO_FIXABLE_CATEGORIES
print(f"\nTotal auto-fixable categories: {len(AUTO_FIXABLE_CATEGORIES)}")
for cat in sorted(AUTO_FIXABLE_CATEGORIES):
    print(f"  - {cat}")

print("\n✓ All tests completed!")
