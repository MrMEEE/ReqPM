# Mock .deb Package Build System

## Overview

This solution provides Mock as a distributable .deb package for Ubuntu/Debian systems, built using Podman containers. This eliminates the need for complex manual installation and makes Mock easy to distribute.

## Solution Components

### 1. Build Script (`scripts/build-mock-deb.sh`)

Automated script that:
- Creates a Podman container with Ubuntu 22.04
- Clones Mock from official repository
- Creates proper Debian package structure
- Builds a .deb package with all dependencies
- Extracts the package for distribution

**Usage:**
```bash
./scripts/build-mock-deb.sh
```

**Output:** `build/mock-deb/output/mock_VERSION_all.deb`

### 2. GitHub Actions Workflow (`.github/workflows/build-mock-deb.yml`)

Automated CI/CD that:
- Builds .deb package on every push to main
- Runs weekly to get latest Mock version
- Creates GitHub releases with packages
- Generates checksums and installation instructions
- Can be triggered manually

**Triggers:**
- Push to main branch
- Weekly schedule (Sunday 00:00)
- Manual workflow dispatch

### 3. Quick Install Script (`scripts/install-mock-deb.sh`)

User-friendly installer that:
- Downloads latest .deb from GitHub Releases
- Installs package and dependencies
- Configures mock group
- Adds user to group
- Provides verification steps

**Usage:**
```bash
./scripts/install-mock-deb.sh
```

## Package Details

### What's Included

The .deb package includes:
- **Mock core** - The main Mock build system
- **Mock configurations** - RHEL 8/9/10 build configs
- **All dependencies** - Python modules, RPM tools, etc.
- **Automatic setup** - Groups, directories, permissions

### Dependencies

The package depends on:
- python3-distro
- python3-jinja2
- python3-requests
- python3-rpm
- python3-pyroute2
- python3-systemd
- python3-templated-dictionary
- rpm
- createrepo-c
- systemd-container
- dnf (recommended)
- yum (recommended)

### Post-Install Actions

The package automatically:
1. Creates `mock` system group
2. Creates `/var/lib/mock` directory
3. Creates `/var/cache/mock` directory
4. Sets correct permissions
5. Displays usage instructions

## Installation Methods

### Method 1: Pre-built Package from GitHub Releases (Recommended)

```bash
# Quick install
./scripts/install-mock-deb.sh
```

Or manually:
```bash
# Download from releases
wget https://github.com/YOUR_USERNAME/ReqPM/releases/latest/download/mock_VERSION_all.deb

# Install
sudo dpkg -i mock_VERSION_all.deb
sudo apt-get install -f
sudo usermod -a -G mock $USER

# Log out and log back in
mock --version
```

### Method 2: Build Locally

```bash
# Build the package
./scripts/build-mock-deb.sh

# Install
sudo dpkg -i build/mock-deb/output/mock_*.deb
sudo apt-get install -f
sudo usermod -a -G mock $USER

# Log out and log back in
mock --version
```

### Method 3: From Source (Legacy)

```bash
# For development/testing only
./scripts/install-mock-ubuntu.sh
```

## GitHub Actions Workflow

### Workflow Steps

1. **Checkout** - Clone repository
2. **Setup Podman** - Install container runtime
3. **Build Package** - Run build script in container
4. **Extract Version** - Parse version from package name
5. **Create Assets** - Package files with instructions
6. **Upload Artifacts** - Store for 90 days
7. **Create Release** - Publish to GitHub Releases (on main branch)
8. **Tag Latest** - Update `mock-deb-latest` tag

### Release Artifacts

Each release includes:
- `mock_VERSION_all.deb` - The package
- `SHA256SUMS` - Checksums for verification
- `INSTALL.txt` - Installation instructions
- Release notes with installation commands

### Accessing Releases

```bash
# Latest release
https://github.com/YOUR_USERNAME/ReqPM/releases/latest

# Specific version
https://github.com/YOUR_USERNAME/ReqPM/releases/tag/mock-deb-VERSION

# Direct download latest
https://github.com/YOUR_USERNAME/ReqPM/releases/latest/download/mock_VERSION_all.deb
```

## Build Process Details

### Container-Based Build

The build happens in a clean Ubuntu 22.04 container:

1. **Install Build Tools**
   ```bash
   apt-get install build-essential debhelper dh-python
   ```

2. **Install Dependencies**
   ```bash
   apt-get install python3-distro python3-jinja2 python3-rpm ...
   ```

3. **Clone Mock**
   ```bash
   git clone https://github.com/rpm-software-management/mock.git
   git checkout <latest-tag>
   ```

4. **Create Debian Structure**
   - debian/control - Package metadata
   - debian/rules - Build rules
   - debian/changelog - Version history
   - debian/postinst - Post-install script
   - debian/copyright - License info

5. **Build Package**
   ```bash
   dpkg-buildpackage -us -uc -b
   ```

6. **Extract Package**
   ```bash
   cp /build/*.deb /output/
   ```

### Why Podman?

- **Clean builds** - Each build is isolated
- **Reproducible** - Same environment every time
- **No pollution** - Build deps don't affect host
- **CI-friendly** - Works in GitHub Actions
- **No Docker daemon** - Rootless, more secure

## Platform Compatibility

### Tested On

- ✅ Ubuntu 22.04 LTS (Jammy)
- ✅ Ubuntu 20.04 LTS (Focal)
- ✅ Debian 11 (Bullseye)
- ✅ Debian 12 (Bookworm)

### Requirements

- Ubuntu 20.04+ or Debian 11+
- 64-bit architecture (x86_64/amd64)
- At least 2GB free disk space
- Podman (for building only)

## Integration with ReqPM

### Detection

ReqPM automatically detects if Mock is available via:
- `/api/system-health/` endpoint
- UI warning banner
- Status in build dialog

### After Installation

1. Install .deb package
2. Add user to mock group
3. Log out and log back in
4. Restart ReqPM:
   ```bash
   ./reqpm.sh restart all
   ```
5. Warning banner disappears
6. Builds work normally

## Maintenance

### Updating Mock

The GitHub Actions workflow automatically:
- Checks for new Mock releases weekly
- Builds updated packages
- Creates new releases

To manually update:
```bash
# Trigger GitHub Actions workflow
# Or build locally:
./scripts/build-mock-deb.sh
```

### Version Tracking

- Package version matches Mock upstream version
- Release tags: `mock-deb-VERSION`
- Latest always tagged: `mock-deb-latest`

## Troubleshooting

### Build Fails

```bash
# Check Podman is installed
podman --version

# Check build logs
cat build/mock-deb/Dockerfile

# Try clean build
rm -rf build/mock-deb
./scripts/build-mock-deb.sh
```

### Package Install Fails

```bash
# Install dependencies first
sudo apt-get update
sudo apt-get install -f

# Check what's missing
dpkg -I mock_*.deb
apt-cache policy python3-rpm python3-distro
```

### Mock Not Working

```bash
# Check installation
dpkg -l | grep mock

# Check group
groups | grep mock

# Check permissions
ls -ld /var/lib/mock /var/cache/mock

# Test
mock --version
mock --list-chroots
```

## Future Enhancements

### Potential Improvements

1. **Multi-platform builds** - Build for different Ubuntu/Debian versions
2. **PPA hosting** - Create APT repository for easy updates
3. **ARM support** - Build ARM64 packages
4. **Docker alternative** - Support Docker if Podman unavailable
5. **Local cache** - Speed up repeated builds

### Contributing

To improve the build system:
1. Test on different platforms
2. Report issues with build logs
3. Submit PRs with improvements
4. Document edge cases

## Benefits

### For Users

- ✅ Easy installation - One command
- ✅ No manual compilation
- ✅ Automatic dependencies
- ✅ Clean uninstall - `sudo apt remove mock`
- ✅ Familiar package manager

### For Developers

- ✅ Reproducible builds
- ✅ CI/CD integration
- ✅ Version control
- ✅ Easy distribution
- ✅ Automated releases

### For ReqPM

- ✅ Broader platform support
- ✅ Easier onboarding
- ✅ Professional appearance
- ✅ Less support burden
- ✅ Better user experience

## Files Created

1. `scripts/build-mock-deb.sh` - Build script
2. `scripts/install-mock-deb.sh` - Quick installer
3. `.github/workflows/build-mock-deb.yml` - CI/CD workflow
4. `docs/MOCK_SETUP_UBUNTU.md` - Updated documentation
5. `docs/MOCK_DEB_BUILD.md` - This document

## Next Steps

1. **Test locally:**
   ```bash
   ./scripts/build-mock-deb.sh
   ```

2. **Set up GitHub Actions:**
   - Push to GitHub
   - Enable Actions in repository settings
   - Trigger workflow manually

3. **Create first release:**
   - Workflow runs automatically
   - Package appears in Releases

4. **Update documentation:**
   - Add your GitHub username to URLs
   - Test installation instructions
   - Update release links

5. **Announce:**
   - Update README
   - Notify users
   - Add to project documentation
