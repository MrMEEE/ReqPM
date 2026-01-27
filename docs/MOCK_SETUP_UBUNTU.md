# Mock Setup for Ubuntu/Debian Systems

This guide explains how to install and configure Mock on Ubuntu, Debian, and other non-RPM based systems where Mock packages are not available.

## Overview

Mock can run on Ubuntu/Debian systems. We provide pre-built .deb packages that make installation easy.

## Quick Installation (Recommended)

### Option 1: Install from Pre-built .deb Package

We provide pre-built .deb packages via GitHub Releases:

```bash
# Download the latest .deb package
wget https://github.com/YOUR_USERNAME/ReqPM/releases/latest/download/mock_VERSION_all.deb

# Install the package
sudo dpkg -i mock_VERSION_all.deb

# Install any missing dependencies
sudo apt-get install -f

# Install additional Python dependencies system-wide
sudo apt-get install -y python3-backoff
sudo pip3 install --break-system-packages templated-dictionary rpmautospec-core

# Add your user to mock group
sudo usermod -a -G mock $USER
```

**Important:** 
- After installation, you **must** log out and log back in for group membership to take effect.
- The Python dependencies must be installed system-wide because Mock uses the system Python interpreter.

### Option 2: Build .deb Package Locally

If you prefer to build the package yourself:

```bash
# Build the .deb package using Podman
cd /path/to/ReqPM
./scripts/build-mock-deb.sh

# Install the built package
sudo dpkg -i build/mock-deb/output/mock_*.deb
sudo apt-get install -f

# Add your user to mock group
sudo usermod -a -G mock $USER
```

### Option 3: Use Automated Installation Script

For development/testing, you can install from source:

```bash
# Run the installation script
cd /path/to/ReqPM
./scripts/install-mock-ubuntu.sh
```

## Manual Installation

If you prefer to install manually or the script doesn't work for your system:

### 1. Install Dependencies

```bash
sudo apt-get update
sudo apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    python3-distro \
    python3-jinja2 \
    python3-requests \
    python3-rpm \
    python3-pyroute2 \
    python3-systemd \
    python3-templated-dictionary \
    rpm \
    createrepo-c \
    dnf \
    yum \
    systemd-container \
    debootstrap \
    squashfs-tools \
    pigz \
    git
```

**Note:** Some packages might have different names depending on your Ubuntu/Debian version:
- On older systems, `dnf` might not be available (Mock can work without it)
- `python3-rpm` is in the `python3-rpm` package
- If `createrepo-c` is not available, try `createrepo`

### 2. Install Mock from Source

```bash
# Create temporary directory
cd /tmp

# Clone Mock repository
git clone https://github.com/rpm-software-management/mock.git
cd mock

# Get latest stable version
LATEST_TAG=$(git describe --tags --abbrev=0)
git checkout $LATEST_TAG

# Install Mock
cd mock
sudo python3 setup.py install

# Install mock-core-configs
cd ../mock-core-configs
sudo python3 setup.py install
```

### 3. Create Mock Group and Add User

```bash
# Create mock group
sudo groupadd -r mock

# Add your user to mock group
sudo usermod -a -G mock $USER

# Verify
groups | grep mock
```

**Important:** Log out and log back in for group changes to take effect!

### 4. Create Mock Directories

```bash
# Create necessary directories
sudo mkdir -p /var/lib/mock
sudo mkdir -p /var/cache/mock
sudo mkdir -p /etc/mock

# Set correct permissions
sudo chown root:mock /var/lib/mock
sudo chown root:mock /var/cache/mock
sudo chmod 2775 /var/lib/mock
sudo chmod 2775 /var/cache/mock
```

### 5. Configure Mock

Create `/etc/mock/site-defaults.cfg`:

```bash
sudo tee /etc/mock/site-defaults.cfg > /dev/null <<'EOF'
# Site-specific default configuration for Mock

config_opts['plugin_conf']['root_cache_enable'] = True
config_opts['plugin_conf']['yum_cache_enable'] = True
config_opts['plugin_conf']['ccache_enable'] = False

# Cleanup options
config_opts['cleanup_on_success'] = True
config_opts['cleanup_on_failure'] = True

# Build user
config_opts['chrootuser'] = 'mockbuild'
config_opts['chrootuid'] = 1000
config_opts['chrootgid'] = 1000
EOF
```

### 6. Install RHEL Mock Configurations

You need the RHEL/CentOS mock configuration files. Download them from the Mock repository:

```bash
# Download RHEL configs
cd /tmp
git clone https://github.com/rpm-software-management/mock.git mock-configs
cd mock-configs/mock-core-configs/etc/mock

# Copy the configs you need
sudo cp rhel-8-x86_64.cfg /etc/mock/
sudo cp rhel-9-x86_64.cfg /etc/mock/
sudo cp rhel-10-x86_64.cfg /etc/mock/

# Also copy the templates directory
sudo cp -r templates /etc/mock/
```

## Verification

### Test Mock Installation

```bash
# Check Mock version
mock --version

# You should see something like:
# 6.6
```

### Test Group Membership

```bash
# Check you're in the mock group
groups | grep mock

# Should show: ... mock ...
```

### List Available Configurations

```bash
# List available build targets
mock --list-chroots

# Should show:
# rhel-8-x86_64
# rhel-9-x86_64
# rhel-10-x86_64
```

### Test Build (Optional)

Create a simple test spec:

```bash
mkdir ~/mock-test
cd ~/mock-test

cat > test.spec <<'EOF'
Name:           test-package
Version:        1.0
Release:        1%{?dist}
Summary:        Test package

License:        MIT
URL:            https://example.com

%description
A test package.

%prep

%build

%install
mkdir -p %{buildroot}/usr/share/test
echo "Hello" > %{buildroot}/usr/share/test/hello.txt

%files
/usr/share/test/hello.txt

%changelog
* Sat Jan 25 2026 Test User <test@example.com> - 1.0-1
- Initial package
EOF

# Try building
mock -r rhel-9-x86_64 --buildsrpm --spec test.spec --sources .
```

If successful, you'll see the SRPM created in `/var/lib/mock/rhel-9-x86_64/result/`.

## Platform-Specific Notes

### Ubuntu 22.04 LTS (Jammy)

All dependencies are available in the default repositories:

```bash
sudo apt-get install python3-rpm python3-distro python3-jinja2 python3-requests rpm createrepo-c dnf
```

### Ubuntu 20.04 LTS (Focal)

Some packages might need to be installed from different sources:

```bash
# DNF might not be available, install from PPA or compile from source
# Mock can work without DNF using YUM instead

sudo apt-get install python3-rpm python3-distro python3-jinja2 python3-requests rpm createrepo-c yum
```

### Debian 11/12

```bash
sudo apt-get install python3-rpm python3-distro python3-jinja2 python3-requests rpm createrepo-c
```

## Troubleshooting

### Permission Denied Error

**Error:** `ERROR: Could not open /var/lib/mock`

**Solution:**
```bash
# Make sure you're in the mock group
groups | grep mock

# If not, add yourself
sudo usermod -a -G mock $USER

# Log out and log back in!
```

### Python Module Not Found

**Error:** `ModuleNotFoundError: No module named 'distro'`

**Solution:**
```bash
sudo apt-get install python3-distro
# or
sudo pip3 install distro
```

### RPM Command Not Found

**Error:** `mock: command not found` or `rpm: command not found`

**Solution:**
```bash
sudo apt-get install rpm mock
```

### DNF/YUM Issues

**Error:** Mock complains about DNF

**Solution:** Mock can work with YUM on systems without DNF:
```bash
sudo apt-get install yum
```

Or modify the mock config to use YUM instead of DNF.

### Config File Not Found

**Error:** `ERROR: Could not find required config file: rhel-9-x86_64`

**Solution:** You need to copy the RHEL configs:
```bash
cd /tmp
git clone https://github.com/rpm-software-management/mock.git
cd mock/mock-core-configs/etc/mock
sudo cp rhel-*.cfg /etc/mock/
sudo cp -r templates /etc/mock/
```

## Updating Mock

To update Mock to a newer version:

```bash
cd /tmp
git clone https://github.com/rpm-software-management/mock.git
cd mock
git checkout <new-version-tag>
cd mock
sudo python3 setup.py install
cd ../mock-core-configs
sudo python3 setup.py install
```

## Alternative: Use Container

If you have issues running Mock natively on Ubuntu/Debian, you can use a Fedora/RHEL container that has Mock pre-installed:

```bash
# Using Docker
docker run -it --privileged fedora:latest
dnf install -y mock
mock --version

# Using Podman
podman run -it --privileged fedora:latest
dnf install -y mock
mock --version
```

However, this adds complexity to the ReqPM setup.

## Integration with ReqPM

Once Mock is installed and verified:

### 1. Ensure Python Dependencies are Installed

Mock requires certain Python packages to be installed **system-wide** (not just in the venv) because Mock uses the system Python interpreter (`/usr/bin/python3`):

```bash
# Install what's available via apt
sudo apt-get install -y python3-backoff

# Install packages not in apt repositories
sudo pip3 install --break-system-packages templated-dictionary rpmautospec-core
```

**Note:** If you followed Option 1 above, these should already be installed.

### 2. (Optional) Install Dependencies in ReqPM Virtual Environment

If you want to run Mock-related Python code from within the ReqPM application (not just call the mock binary), also install in the venv:

```bash
# Activate ReqPM virtual environment
cd /path/to/ReqPM
source venv/bin/activate

# Install dependencies (already in requirements.txt)
pip install -r requirements.txt
```

### 3. Restart ReqPM Services

```bash
./reqpm.sh restart celery  # or restart all
```

### 4. Verify in Web UI

1. Navigate to the Builds page
2. Check system health indicator - the warning banner should disappear
3. You can now start builds for RHEL 8/9/10

### 4. Set PYTHONPATH (Optional)

If you need to run mock commands from the ReqPM environment:

```bash
export PYTHONPATH=/path/to/ReqPM/venv/lib/python3.*/site-packages:$PYTHONPATH
mock --version
```

Or add it to your ReqPM systemd service file or `.env` configuration.

## Getting Help

If you encounter issues:

1. Check Mock logs: `/var/lib/mock/<config>/build.log`
2. Check Mock documentation: https://rpm-software-management.github.io/mock/
3. Check ReqPM logs: `./reqpm.sh logs celery`
4. Open an issue on the ReqPM repository

## Known Limitations

- Building RPMs on Ubuntu/Debian works, but:
  - Some RPM-specific features might behave differently
  - SELinux contexts won't work (Ubuntu uses AppArmor)
  - Some systemd features might not be available
  - You're building RPMs on a non-RPM system (technically works, but less tested)

For production use, running ReqPM on a RHEL/Fedora/CentOS system is recommended.
