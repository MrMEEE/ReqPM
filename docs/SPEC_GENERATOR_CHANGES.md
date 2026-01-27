# Spec Generator Changes - awx-rpm-v2 Approach

## Summary

Changed the spec file generation from a template-based approach to using **pyp2rpm**, following the methodology used by the **awx-rpm-v2** project.

## What Changed

### Before (Template-Based)
- Used a static SPEC_TEMPLATE with placeholders
- Fetched PyPI metadata manually via urllib
- Parsed dependencies and metadata manually
- Filled template with extracted information

### After (pyp2rpm-Based)
- Uses **pyp2rpm** tool (Python package installer community standard)
- Generates spec files automatically from PyPI packages
- Handles dependencies, metadata, and build instructions automatically
- Follows Fedora/RHEL packaging standards out of the box

## Technical Details

### awx-rpm-v2 Approach
The awx-rpm-v2 project uses a script called `pypi2spec` which runs:
```bash
pyp2spec -p 3.11 --license gpl [-v VERSION] PACKAGE
```

We adapted this to use `pyp2rpm` (which is the actual available tool):
```bash
pyp2rpm -b 3 [-v VERSION] PACKAGE
```

### New Implementation
File: `backend/core/spec_generator.py`

**Key changes:**
1. `SpecFileGenerator.generate_spec()` now calls `pyp2rpm` subprocess
2. Captures stdout output (pyp2rpm prints spec to stdout by default)
3. Post-processes spec to add packager information
4. Falls back to basic template if pyp2rpm fails

**Dependencies:**
- Installed `pyp2rpm` package: `pip install pyp2rpm`

## Benefits

1. **Industry Standard**: pyp2rpm is the Fedora/RHEL community standard tool
2. **Better Quality**: Generates more complete and accurate spec files
3. **Automatic Updates**: Handles new Python packaging standards automatically
4. **Less Maintenance**: No need to maintain our own template and parsing logic
5. **Compatibility**: Same approach as awx-rpm-v2 project

## Testing

Tested with `requests` package version 2.28.0:
```python
from backend.core.spec_generator import SpecFileGenerator
generator = SpecFileGenerator()
spec = generator.generate_spec('requests', version='2.28.0')
```

Result: Successfully generated a complete RPM spec file with:
- Proper metadata (name, version, summary, license, URL)
- BuildRequires and Requires sections
- Build architecture (BuildArch: noarch)
- All necessary sections (%prep, %build, %install, %files, %changelog)

## Files Modified

- `backend/core/spec_generator.py` - Complete rewrite to use pyp2rpm
- `requirements.txt` (if exists) - Added pyp2rpm dependency

## Migration Notes

- Existing packages will continue to work
- New spec generations will use pyp2rpm
- Spec quality should improve automatically
- No database changes needed
- No API changes needed

## Future Enhancements

Could add support for:
- Custom templates (pyp2rpm -t option)
- Different distros (pyp2rpm -o option)
- Additional Python versions (pyp2rpm -p option)
- SRPM generation (pyp2rpm --srpm option)
