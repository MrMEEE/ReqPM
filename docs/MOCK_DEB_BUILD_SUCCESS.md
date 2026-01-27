# Mock .deb Package Build - Success Report

## Build Summary

Successfully built Mock as a .deb package for Ubuntu 25.10!

**Package Details:**
- **Version:** 43.4-1-1
- **Size:** 135 KB
- **Architecture:** all (architecture-independent)
- **Location:** `build/mock-deb-ubuntu-25.10/output/mock_43.4-1-1_all.deb`

## Package Information

```
Package: mock
Version: 43.4-1-1
Architecture: all
Maintainer: ReqPM Team <reqpm@example.com>
Installed-Size: 1276 KB
Section: devel
Priority: optional
Homepage: https://github.com/rpm-software-management/mock
```

### Dependencies

**Required:**
- python3-distro
- python3-jinja2
- python3-requests
- python3-rpm
- python3-pyroute2
- rpm
- createrepo-c
- systemd-container

**Recommended:**
- python3-systemd

### Package Contents

The package includes:
- `/usr/bin/mock` - Main Mock command
- `/usr/bin/mockchain` - Mock chain building tool
- `/usr/bin/mock-parse-buildlog` - Build log parser
- `/usr/lib/python3/dist-packages/mockbuild/` - Python modules
- `/etc/mock/` - Mock configuration files for various distributions
- `/usr/share/man/man1/mock.1` - Man page
- `/usr/share/bash-completion/completions/mock` - Bash completion

### Configuration Files

The package includes 468 configuration files for various distributions including:
- AlmaLinux (8, 9, 10)
- CentOS Stream (9, 10)
- Fedora (40, 41, 42, rawhide)
- RHEL (8, 9, 10)
- Rocky Linux (8, 9, 10)
- And many more...

## Installation

### Install the Package

```bash
sudo dpkg -i build/mock-deb-ubuntu-25.10/output/mock_43.4-1-1_all.deb
sudo apt-get install -f  # Install missing dependencies
```

### Add User to Mock Group

```bash
sudo usermod -a -G mock $USER
# Log out and back in for group changes to take effect
```

### Verify Installation

```bash
mock --version
mock --list-chroots | head -10
```

## Build Process

### Build Command

```bash
./scripts/build-mock-deb.sh
```

The script:
1. Creates an Ubuntu 25.10 container using Podman
2. Installs build dependencies (debhelper, python3, rpm, etc.)
3. Installs `templated-dictionary` via pip (not available in apt)
4. Clones the Mock repository from GitHub
5. Creates Debian packaging files (control, rules, changelog, etc.)
6. Builds the .deb package using `dpkg-buildpackage`
7. Copies the resulting package to `build/mock-deb-ubuntu-25.10/output/`

### Build Time

Approximately 2-3 minutes on a modern system (most time spent installing dependencies).

### Build Issues Resolved

1. **Python package availability:** `templated-dictionary` not in Ubuntu repos
   - **Solution:** Install via pip with `--break-system-packages` flag

2. **Version parsing:** Git tags include prefixes like `mock-core-configs-`
   - **Solution:** Updated sed to remove both `mock-core-configs-` and `mock-` prefixes

3. **Build system changes:** Mock no longer uses `setup.py`
   - **Solution:** Manual file installation in `debian/rules` following RPM spec logic

4. **Debian helper syntax:** Incorrect `--with python3` syntax
   - **Solution:** Changed to `--with=python3` then simplified to manual install

## Multi-Version Support

The build script supports building for multiple Ubuntu versions:

```bash
# Build for specific versions
UBUNTU_VERSIONS="22.04 24.04 25.10" ./scripts/build-mock-deb.sh

# Default: builds for 25.10 only
./scripts/build-mock-deb.sh
```

## GitHub Actions Integration

The `.github/workflows/build-mock-deb.yml` workflow will automatically:
- Build for Ubuntu 22.04, 24.04, and 25.10
- Create separate GitHub Releases for each version
- Include SHA256 checksums
- Provide installation instructions

## Next Steps

1. **Test the Package:**
   - Install on Ubuntu 25.10 system
   - Verify Mock can build RPM packages
   - Test with sample SPEC file

2. **Update Repository URLs:**
   - Replace `YOUR_USERNAME/ReqPM` with actual repository in:
     - `.github/workflows/build-mock-deb.yml`
     - `scripts/install-mock-deb.sh`
     - Documentation files

3. **Push to GitHub:**
   - Commit all changes
   - Push to GitHub
   - GitHub Actions will create releases automatically

4. **Test Multi-Version Builds:**
   - Build for Ubuntu 22.04 and 24.04
   - Verify compatibility

5. **Update ReqPM Documentation:**
   - Add Mock installation instructions for Ubuntu users
   - Link to GitHub Releases for easy download

## Related Documentation

- [Mock .deb Build System](./MOCK_DEB_BUILD.md) - Complete build system documentation
- [Mock Setup Guide - Ubuntu/Debian](./MOCK_SETUP_UBUNTU.md) - Installation and configuration
- [Scripts README](../scripts/README.md) - Build script usage guide

## Build Log

The full build log shows no errors:
- All dependencies installed successfully
- Package built without warnings (except sysctl warnings in container)
- dpkg-buildpackage completed successfully
- Final package passes dpkg-deb validation

**Build Status:** ✅ SUCCESS
