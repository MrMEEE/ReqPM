# ReqPM Scripts

This directory contains utility scripts for setting up and managing ReqPM.

## Mock Installation Scripts

### build-mock-deb.sh

Builds Mock as a .deb package using Podman containers.

**Purpose:** Create distributable .deb package for Ubuntu/Debian systems

**Requirements:**
- Podman installed
- ~2GB disk space
- Internet connection

**Usage:**
```bash
./scripts/build-mock-deb.sh
```

**Output:** `build/mock-deb/output/mock_VERSION_all.deb`

**See also:** [docs/MOCK_DEB_BUILD.md](../docs/MOCK_DEB_BUILD.md)

---

### install-mock-deb.sh

Quick installer for Mock .deb package from GitHub Releases.

**Purpose:** Download and install latest Mock package automatically

**Requirements:**
- Ubuntu/Debian system
- wget or curl
- Internet connection

**Usage:**
```bash
./scripts/install-mock-deb.sh
```

**What it does:**
1. Downloads latest .deb from GitHub Releases
2. Installs package and dependencies
3. Creates mock group
4. Adds current user to mock group
5. Provides verification instructions

**After running:** Log out and log back in

---

### install-mock-ubuntu.sh

Installs Mock from source on Ubuntu/Debian systems.

**Purpose:** Development/testing installation without package

**Requirements:**
- Ubuntu/Debian system
- sudo access
- Internet connection

**Usage:**
```bash
./scripts/install-mock-ubuntu.sh
```

**Warning:** This installs from source and is less clean than using .deb package. Use for development only.

**See also:** [docs/MOCK_SETUP_UBUNTU.md](../docs/MOCK_SETUP_UBUNTU.md)

---

## Which Script Should I Use?

### For Production/Users:
```bash
./scripts/install-mock-deb.sh
```
Downloads and installs pre-built package from releases.

### For Building Packages:
```bash
./scripts/build-mock-deb.sh
```
Builds .deb package locally for testing or custom builds.

### For Development:
```bash
./scripts/install-mock-ubuntu.sh
```
Installs from source for development and testing.

---

## Verification

After installing Mock with any method:

```bash
# Check Mock is installed
mock --version

# Check group membership
groups | grep mock

# Check directories
ls -ld /var/lib/mock /var/cache/mock

# List build targets
mock --list-chroots

# Restart ReqPM
./reqpm.sh restart all
```

---

## Troubleshooting

### "mock: command not found"

Mock is not installed or not in PATH.
```bash
# Check if installed
dpkg -l | grep mock

# Reinstall if needed
./scripts/install-mock-deb.sh
```

### "Permission denied" when running mock

You're not in the mock group or haven't logged out/in.
```bash
# Check group
groups | grep mock

# Add to group if missing
sudo usermod -a -G mock $USER

# Log out and log back in!
```

### Package installation fails

Dependencies missing.
```bash
# Install dependencies
sudo apt-get update
sudo apt-get install -f

# Retry installation
sudo dpkg -i mock_*.deb
```

---

## Documentation

- Mock Setup (RHEL): [docs/MOCK_SETUP.md](../docs/MOCK_SETUP.md)
- Mock Setup (Ubuntu): [docs/MOCK_SETUP_UBUNTU.md](../docs/MOCK_SETUP_UBUNTU.md)
- Mock .deb Build System: [docs/MOCK_DEB_BUILD.md](../docs/MOCK_DEB_BUILD.md)
- Main README: [README.md](../README.md)
