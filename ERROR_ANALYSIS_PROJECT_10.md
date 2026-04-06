# Project 10 Build Error Analysis

## Summary
**Total Failed Packages**: 457 out of ~614 packages

## Major Error Categories (with fix recommendations)

### 1. Missing setup.py - Using Legacy Build Macros (171 packages)
**Impact**: ~37% of failed builds

**Root Cause**: 
- Spec files use `%py3_build` and `%py3_install` macros which expand to `python3 setup.py build/install`
- Modern Python packages (2020+) only have `pyproject.toml`, no `setup.py`
- The `spec_generator.py` has post-processing code to fix this, but it's NOT being applied

**Examples**: ansi2html, channels, click, cryptography, daphne, django, jinja2, idna, incremental, packaging

**Error Pattern**:
```
/usr/bin/python3: can't open file '/builddir/build/BUILD/click-8.1.8/setup.py': [Errno 2] No such file or directory
error: Bad exit status from /var/tmp/rpm-tmp.xxxxx (%build)
```

**Fix Required**:
1. ✅ **IMMEDIATE FIX**: Update spec_fixer.py to detect this pattern and replace macros
   - Detect: `%py3_build` or `/usr/bin/python3 setup.py` in spec
   - Replace with: `%pyproject_wheel` and `%pyproject_install`
   - Add: `BuildRequires: pyproject-rpm-macros`
   - Add: `%generate_buildrequires` section with `%pyproject_buildrequires`

2. 🔧 **ROOT CAUSE FIX**: Investigate why `spec_generator.py`'s `_post_process_spec()` is not being applied
   - The function exists and has the right logic
   - But generated specs still have old macros
   - Check if specs are being re-saved after generation

**Auto-fixable**: YES - High priority!

---

### 2. Invalid pyproject.toml License Format (14 packages)  
**Impact**: ~3% of failed builds

**Root Cause**:
- PEP 621 requires: `license = {text = "BSD"}` 
- Source tarball has: `license = "BSD"`
- This is a pyproject.toml format violation

**Examples**: cffi, markupsafe, txaio, zstandard, cbor2, ipython, more_itertools, websockets, greenlet, oracledb

**Error Pattern**:
```
ValueError: invalid pyproject.toml config: `project.license`.
configuration error: `project.license` must be valid exactly by one definition (2 matches found)
```

**Fix Required**:
✅ **ALREADY PARTIALLY IMPLEMENTED** in `spec_fixer.py` - `_fix_pyprojectlicense()`
- But needs to be verified/enhanced

**Auto-fixable**: YES - Already in fixing engine

---

### 3. Unpackaged Files (34 packages)
**Impact**: ~7% of failed builds

**Root Cause**:
- Files are installed but not listed in `%files` section
- RPM build fails because all installed files must be packaged

**Examples**: ansi2html, dynaconf, jmespath, pbr, pygerduty, python-string-utils, uwsgitop, wheel, mypy

**Error Pattern**:
```
Installed (but unpackaged) file(s) found:
   /usr/bin/some-script
   /usr/lib/python3.12/site-packages/some_file.py
```

**Fix Required**:
✅ **NEW FIX NEEDED**: Add to spec_fixer.py
1. Parse log for "Installed (but unpackaged)" section
2. Extract file paths
3. Add to `%files` section in spec (or use more generic glob patterns)

**Auto-fixable**: YES - Medium priority

---

### 4. Missing g++ Compiler (at least 1 explicit, likely more)
**Impact**: Small but affects C++ extension packages

**Example**: grpcio

**Error Pattern**:
```
FileNotFoundError: [Errno 2] No such file or directory: 'g++'
```

**Fix Required**:
✅ **NEW PATTERN NEEDED** in error_analyzer.py
- Pattern: `FileNotFoundError.*'g\+\+'` or `command 'g\+\+' failed: No such file`
- Add to `AUTO_FIXABLE_CATEGORIES`

**Fixer**:
- Add `BuildRequires: gcc-c++` to spec

**Auto-fixable**: YES - Easy fix

---

### 5. KeyError 'text' in Metadata (1 package)
**Impact**: Very small

**Example**: autocommand

**Error Pattern**:
```
KeyError: 'text'
error: Bad exit status from /var/tmp/rpm-tmp.NDaLCO (%build)
```

**Fix Required**:
- Likely related to license parsing in pyproject.toml
- May be a variant of the pyproject license issue (#2)

** Auto-fixable**: Needs investigation

---

## Currently Detected but Not Fixed

### Scriplet Errors (already detected)
- 171 packages with %build scriplet failures (see #1 above)
- 2 packages with %install scriplet failures

The error_analyzer already detects these with the `scriplet_error` pattern, but most root causes are actually the setup.py issue above.

---

## Error Detection Status

### Already Detected by error_analyzer.py ✅
- Missing Dependencies
- Missing Packages
- Missing Python Modules
- Missing Python Wheel
- Missing GCC (compiler)
- Ambiguous Python Shebang
- Empty Debug Info
- Architecture Mismatch
- Invalid Pyproject License
- Scriplet errors (generic)

### Needs New Pattern 🆕
1. **Missing g++ compiler** (g++ != gcc)
2. **Legacy build macros** (setup.py missing pattern)
3. **Unpackaged files** (already detected, needs fixer)

---

## Recommendations for Fixing Engine Priority

### High Priority (Would fix ~60% of failures)
1. ✅ **Setup.py / Build Macro Fix** (#1) - 171 packages
   - Add to spec_fixer.py.
   - Pattern: Detect `can't open file.*setup.py` or `%py3_build` in spec
   - Fix: Replace with pyproject macros

2. ✅ **Unpackaged Files Fixer** (#3) - 34 packages
   - Add to spec_fixer.py
   - Parse log, extract file list, add to %files

### Medium Priority
3. ✅ **Missing g++ Detection** (#4)
   - Add to error_analyzer.py patterns
   - Add to spec_fixer.py (add gcc-c++ BuildRequires)

### Already Done
- Invalid pyproject license (#2) - already in spec_fixer
- Missing gcc - already in error_analyzer
- Empty debuginfo - already handled
- Ambiguous shebang - already handled

---

## Implementation Plan

1. **Verify existing fixes are working**
   - Check why spec_generator post-processing isn't being applied
   - Verify invalid_pyproject_license fixer is active

2. **Add new error patterns to error_analyzer.py**
   - g++ missing pattern
   - Better setup.py detection

3. **Add new fixers to spec_fixer.py**
   - Legacy macro -> pyproject macro converter
   - Unpackaged files handler

4. **Test on project 10**
   - Run fix cycle
   - Measure improvement

---

## Notes

- Many "MISSING_GCC" detections are actually false positives from the setup.py issue
- The database shows 591/614 packages have `build_system='unknown'`
- Only 13 packages are marked as 'setuptools'
- The spec_generator already has the logic to handle this, but it's not being applied
