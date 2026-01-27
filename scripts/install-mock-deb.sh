#!/bin/bash
# Quick install Mock from pre-built .deb package
# Downloads and installs the latest Mock .deb package for Ubuntu/Debian

set -e

GITHUB_REPO="${GITHUB_REPO:-YOUR_USERNAME/ReqPM}"
RELEASE_TAG="${RELEASE_TAG:-mock-deb-latest}"

echo "=== Mock Quick Install for Ubuntu/Debian ==="
echo

# Check if running on Ubuntu/Debian
if [ ! -f /etc/os-release ]; then
    echo "Error: Cannot detect OS"
    exit 1
fi

. /etc/os-release
if [[ "$ID" != "ubuntu" && "$ID" != "debian" ]]; then
    echo "Warning: This script is designed for Ubuntu/Debian"
    echo "Detected: $ID $VERSION_ID"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Check for required tools
for cmd in wget curl dpkg; do
    if ! command -v $cmd &> /dev/null; then
        echo "Error: $cmd is required but not installed"
        echo "Install with: sudo apt-get install $cmd"
        exit 1
    fi
done

# Create temporary directory
TMPDIR=$(mktemp -d)
cd "$TMPDIR"

echo "Fetching latest release info..."
RELEASE_URL="https://api.github.com/repos/$GITHUB_REPO/releases/tags/$RELEASE_TAG"

# Get download URL for .deb file
DEB_URL=$(curl -s "$RELEASE_URL" | grep "browser_download_url.*\.deb" | cut -d '"' -f 4)

if [ -z "$DEB_URL" ]; then
    echo "Error: Could not find .deb package in release"
    echo "You may need to build it yourself using: ./scripts/build-mock-deb.sh"
    exit 1
fi

echo "Downloading Mock .deb package..."
echo "URL: $DEB_URL"
wget -q --show-progress "$DEB_URL" -O mock.deb

echo
echo "Installing Mock..."
sudo dpkg -i mock.deb || true

echo
echo "Installing dependencies..."
sudo apt-get install -f -y

echo
echo "Verifying installation..."
if command -v mock &> /dev/null; then
    MOCK_VERSION=$(mock --version 2>&1 | head -1)
    echo "✓ Mock installed: $MOCK_VERSION"
else
    echo "✗ Mock installation failed"
    exit 1
fi

echo
echo "Configuring mock group..."
if ! getent group mock > /dev/null 2>&1; then
    sudo groupadd -r mock
    echo "✓ Mock group created"
else
    echo "✓ Mock group already exists"
fi

echo
echo "Adding $USER to mock group..."
sudo usermod -a -G mock "$USER"
echo "✓ User added to mock group"

# Cleanup
cd /
rm -rf "$TMPDIR"

echo
echo "=== Installation Complete ==="
echo
echo "IMPORTANT: You must log out and log back in for group membership to take effect!"
echo
echo "To verify:"
echo "  1. Log out and log back in (or run: newgrp mock)"
echo "  2. Run: mock --version"
echo "  3. Run: groups | grep mock"
echo
echo "For ReqPM users:"
echo "  After logging back in, restart ReqPM services:"
echo "    ./reqpm.sh restart all"
echo
