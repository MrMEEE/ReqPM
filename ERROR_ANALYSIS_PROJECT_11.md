# Error Analysis for Project 11

## Overview
Analyzed 24 failed packages from build logs stored in the database.

**Root Cause of Analysis Issues:** The error analyzer patterns weren't working because:
1. Error analyzer runs after each build (✓ confirmed in code)
2. But patterns didn't match - log messages appeared in Swedish/Norwegian locale
3. **FIX APPLIED:** Set `LANG=en_US.UTF-8` and `LC_ALL=en_US.UTF-8` for all build commands

## Error Categories

### 1. Missing Source Files (SRPM Build Failures) - 13 packages

**Error Pattern:**
```
error: Bad file: /home/mj/Downloads/ReqPM/build_artifacts/package_builds/XXXX/Package-X.X.X.tar.gz: Ingen sådan fil eller filkatalog
```
(Swedish/Norwegian for "No such file or directory")

**Affected Packages:**
- Django v6.0.3
- MarkupSafe v3.0.3
- PyJWT v2.12.1
- PyYAML v6.0.3
- async-timeout v5.0.1
- backports.tarfile v1.2.0
- importlib-resources v6.5.2
- jaraco.collections v5.2.1
- jaraco.context v6.1.2
- jaraco.functools v4.4.0
- jaraco.logging v3.4.0
- jaraco.stream v3.0.4
- jaraco.text v4.2.0

**Root Cause:** Source tarball download failed or wasn't copied to the build directory before rpmbuild was invoked.

**Solution:** Fix the source download/copy step in the build task to ensure source files are present before running rpmbuild.

---

### 2. Unpackaged Files (RPM Build Failures) - 11 packages

**Error Pattern:**
```
error: Installed (but unpackaged) file(s) found:
   /usr/bin/normalizer
```

**Affected Packages:**
- awx-plugins-core v0.1.1a0 (Scriplet Error detected)
- awx-plugins-interfaces v0.0.1a5 (Scriplet Error detected)
- charset-normalizer v3.4.3 (Missing `/usr/bin/normalizer`)
- jmespath v1.0.1
- pygerduty v0.38.3
- python-string-utils v1.0.0 (Scriplet Error detected)
- slack-sdk v3.37.0

**Root Cause:** Packages install files (executables, libraries, etc.) that aren't declared in the `%files` section of the spec file.

**Solution:** Enhance spec_generator.py to:
1. Detect console_scripts from setup.py/pyproject.toml
2. Scan installed files after %install
3. Auto-add unpackaged files to %files section

---

## Recommended Fixes

### ✅ COMPLETED: Fixed Locale Issues
**Fixed the error analyzer by setting English locale for all builds:**
- Added `LANG=en_US.UTF-8` and `LC_ALL=en_US.UTF-8` to rpmbuild commands ([mock.py](backend/plugins/builders/mock.py#L472-L480))
- Added same environment variables to Mock commands ([mock.py](backend/plugins/builders/mock.py#L186-L198))
- Fixed unpackaged files pattern to match actual format ([error_analyzer.py](backend/core/error_analyzer.py#L147-L151))
- **Result:** Error messages will now be in English and patterns will match correctly

### Priority 1: Fix Source Download (Affects 13 packages)
Check the build task code that downloads/copies source files:
1. Verify PyPI source download is successful
2. Ensure source tarball is copied to the correct build directory
3. Add error handling if source download fails

### Priority 2: Auto-detect Unpackaged Files (Affects 11 packages)
Enhance `spec_generator.py`:

```python
def detect_console_scripts(self, metadata):
    """Extract console_scripts from package metadata."""
    scripts = []
    
    # From setup.py entry_points
    if 'entry_points' in metadata:
        console_scripts = metadata['entry_points'].get('console_scripts', [])
        for script in console_scripts:
            # Parse "name = module:function" format
            if '=' in script:
                name = script.split('=')[0].strip()
                scripts.append(f'/usr/bin/{name}')
    
    return scripts

def add_to_files_section(self, spec_content, additional_files):
    """Add detected files to %files section."""
    # Insert before %files section or append to it
    pass
```

---

## Statistics

- Total Failed: 24 packages
- Missing Source Files: 13 packages (54%)
- Unpackaged Files: 11 packages (46%)
- Packages with analyzed_errors populated: 3 (12.5%)

---

## Next Steps

1. ✅ Query database for build logs (DONE)
2. ✅ Fix locale issues for error detection (DONE - set LANG=en_US.UTF-8)
3. ✅ Fix error analyzer patterns (DONE - unpackaged files pattern)
4. ⏭️ Fix source download/copy logic in build tasks
5. ⏭️ Enhance spec_generator.py to detect console_scripts
6. ⏭️ Retry failed builds after fixes - errors should now be properly detected and analyzed
