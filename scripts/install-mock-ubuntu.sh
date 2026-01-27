#!/bin/bash
# Mock Installation Script for Debian/Ubuntu
# This script installs Mock and its dependencies on Debian/Ubuntu systems

set -e

echo "=== Mock Installation for Debian/Ubuntu ==="
echo

# Check if running as root
if [ "$EUID" -eq 0 ]; then 
   echo "Please run this script as a regular user, not root"
   echo "The script will use sudo when needed"
   exit 1
fi

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
    VERSION=$VERSION_ID
else
    echo "Cannot detect OS version"
    exit 1
fi

echo "Detected OS: $OS $VERSION"
echo

# Install dependencies
echo "=== Installing Dependencies ==="

# Core Python and build dependencies
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
    git \
    curl \
    wget

echo "✓ Dependencies installed"
echo

# Install Mock from source
echo "=== Installing Mock from Source ==="

# Create temporary directory
TMPDIR=$(mktemp -d)
cd "$TMPDIR"

# Clone Mock repository
echo "Cloning Mock repository..."
git clone https://github.com/rpm-software-management/mock.git
cd mock

# Get latest stable version
LATEST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "main")
echo "Using Mock version: $LATEST_TAG"
git checkout "$LATEST_TAG" 2>/dev/null || true

# Install Mock
cd mock
echo "Installing Mock..."
sudo python3 setup.py install

# Install mock-core-configs
cd ../mock-core-configs
echo "Installing Mock core configs..."
sudo python3 setup.py install

echo "✓ Mock installed"
echo

# Create mock group if it doesn't exist
if ! getent group mock > /dev/null 2>&1; then
    echo "Creating mock group..."
    sudo groupadd -r mock
    echo "✓ Mock group created"
else
    echo "✓ Mock group already exists"
fi

# Add current user to mock group
echo "Adding $USER to mock group..."
sudo usermod -a -G mock "$USER"
echo "✓ User added to mock group"
echo

# Create necessary directories
echo "=== Setting up Mock directories ==="
sudo mkdir -p /var/lib/mock
sudo mkdir -p /var/cache/mock
sudo mkdir -p /etc/mock

# Set permissions
sudo chown root:mock /var/lib/mock
sudo chown root:mock /var/cache/mock
sudo chmod 2775 /var/lib/mock
sudo chmod 2775 /var/cache/mock

echo "✓ Directories created"
echo

# Create basic Mock configuration
echo "=== Creating Mock configuration ==="

# Site-defaults.cfg
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

echo "✓ Mock configuration created"
echo

# Cleanup
cd /
rm -rf "$TMPDIR"

echo "=== Installation Complete ==="
echo
echo "IMPORTANT: You must log out and log back in for group membership to take effect!"
echo
echo "To verify installation:"
echo "  1. Log out and log back in (or run: newgrp mock)"
echo "  2. Run: mock --version"
echo "  3. Run: groups | grep mock"
echo
echo "Mock configs location: /etc/mock/"
echo "Mock cache location: /var/cache/mock/"
echo "Mock build location: /var/lib/mock/"
echo
echo "Note: You'll need to create or copy RHEL mock config files to /etc/mock/"
echo "See: https://github.com/rpm-software-management/mock/tree/main/mock-core-configs"
