#!/bin/bash
# Build Mock .deb package in a Podman container
# This creates a distributable .deb package that can be installed on Ubuntu/Debian

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Ubuntu versions to build for
UBUNTU_VERSIONS="${UBUNTU_VERSIONS:-25.10}"

echo "=== Building Mock .deb Package in Podman Container ==="
echo

# Check if podman is installed
if ! command -v podman &> /dev/null; then
    echo "Error: podman is not installed"
    echo "Install with: sudo apt-get install podman"
    exit 1
fi

# Parse command line arguments
if [ $# -gt 0 ]; then
    UBUNTU_VERSIONS="$@"
fi

echo "Building for Ubuntu versions: $UBUNTU_VERSIONS"
echo

# Build for each Ubuntu version
for UBUNTU_VERSION in $UBUNTU_VERSIONS; do
    echo "=========================================="
    echo "Building for Ubuntu $UBUNTU_VERSION"
    echo "=========================================="
    echo

    BUILD_DIR="$PROJECT_ROOT/build/mock-deb-ubuntu-$UBUNTU_VERSION"
    mkdir -p "$BUILD_DIR"

    echo "Creating build container for Ubuntu $UBUNTU_VERSION..."
    echo

    # Create Dockerfile for building
    cat > "$BUILD_DIR/Dockerfile" <<EOF
FROM ubuntu:$UBUNTU_VERSION

ENV DEBIAN_FRONTEND=noninteractive

# Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    debhelper \
    dh-python \
    python3-all \
    python3-setuptools \
    python3-pip \
    python3-dev \
    python3-distro \
    python3-jinja2 \
    python3-requests \
    python3-rpm \
    python3-pyroute2 \
    rpm \
    createrepo-c \
    systemd-container \
    git \
    curl \
    wget \
    fakeroot \
    && rm -rf /var/lib/apt/lists/*

# Install additional Python packages via pip (not available in apt)
RUN pip3 install --break-system-packages templated-dictionary

WORKDIR /build

# Clone Mock repository
RUN git clone https://github.com/rpm-software-management/mock.git

WORKDIR /build/mock

# Get latest stable version
RUN LATEST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "main") && \
    echo "Building Mock version: $LATEST_TAG" && \
    git checkout "$LATEST_TAG" 2>/dev/null || true

# Create debian package structure
RUN mkdir -p debian

# Create debian/control
RUN cat > debian/control <<'CONTROL'
Source: mock
Section: devel
Priority: optional
Maintainer: ReqPM Team <reqpm@example.com>
Build-Depends: debhelper (>= 10), dh-python, python3-all, python3-setuptools
Standards-Version: 4.5.0
Homepage: https://github.com/rpm-software-management/mock

Package: mock
Architecture: all
Depends: ${python3:Depends}, ${misc:Depends},
 python3-distro,
 python3-jinja2,
 python3-requests,
 python3-rpm,
 python3-pyroute2,
 rpm,
 createrepo-c,
 systemd-container
Recommends: python3-systemd
Description: Build RPM packages in a chroot environment
 Mock is a tool for building RPM packages in a clean chroot environment.
 It is used by the Fedora Build System to build packages for different
 distributions and architectures.
 .
 This package includes both mock and mock-core-configs.
CONTROL

# Create debian/rules
RUN cat > debian/rules <<'RULES'
#!/usr/bin/make -f

%:
	dh \$@

override_dh_auto_build:
	# Mock doesn't need a build step - it's just Python files
	:

override_dh_auto_install:
	# Install Mock files manually
	install -D -m 755 mock/py/mock.py debian/mock/usr/bin/mock
	install -D -m 755 mock/mockchain debian/mock/usr/bin/mockchain
	install -D -m 755 mock/py/mock-parse-buildlog.py debian/mock/usr/bin/mock-parse-buildlog
	
	# Install Python modules
	mkdir -p debian/mock/usr/lib/python3/dist-packages
	cp -a mock/py/mockbuild debian/mock/usr/lib/python3/dist-packages/
	
	# Patch constants.py to use correct paths on Debian/Ubuntu
	sed -i 's|SYSCONFDIR = os.path.join(os.path.dirname(os.path.realpath(sys.argv\[0\])), "..", "etc")|SYSCONFDIR = "/etc"|g' debian/mock/usr/lib/python3/dist-packages/mockbuild/constants.py
	
	# Install config files
	mkdir -p debian/mock/etc/mock
	cp -a mock/etc/mock/* debian/mock/etc/mock/
	cp -a mock-core-configs/etc/mock/* debian/mock/etc/mock/
	
	# Install man pages
	install -D -m 644 mock/docs/mock.1 debian/mock/usr/share/man/man1/mock.1
	
	# Install bash completion
	install -D -m 644 mock/etc/bash_completion.d/mock debian/mock/usr/share/bash-completion/completions/mock

override_dh_auto_clean:
	rm -rf build
	rm -rf *.egg-info
	rm -rf mock/build mock/*.egg-info
	rm -rf mock-core-configs/build mock-core-configs/*.egg-info

override_dh_auto_test:
	# Skip tests for now
	:
RULES

RUN chmod +x debian/rules

# Create debian/changelog
RUN VERSION=\$(git describe --tags --abbrev=0 2>/dev/null | sed 's/^mock-core-configs-//; s/^mock-//' || echo "6.6") && \\
    cat > debian/changelog <<CHANGELOG
mock (\$VERSION-1) unstable; urgency=medium

  * Built from upstream source for ReqPM
  * Packaged for Ubuntu/Debian systems

 -- ReqPM Team <reqpm@example.com>  \$(date -R)
CHANGELOG

# Create debian/compat
RUN echo "10" > debian/compat

# Create debian/copyright
RUN cat > debian/copyright <<'COPYRIGHT'
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: mock
Source: https://github.com/rpm-software-management/mock

Files: *
Copyright: 2006-2024 Red Hat, Inc.
License: GPL-2.0-or-later

License: GPL-2.0-or-later
 This package is free software; you can redistribute it and/or modify
 it under the terms of the GNU General Public License as published by
 the Free Software Foundation; either version 2 of the License, or
 (at your option) any later version.
 .
 On Debian systems, the complete text of the GNU General
 Public License version 2 can be found in "/usr/share/common-licenses/GPL-2".
COPYRIGHT

# Create debian/postinst
RUN cat > debian/postinst <<'POSTINST'
#!/bin/sh
set -e

case "\$1" in
    configure)
        # Create mock group if it doesn't exist
        if ! getent group mock > /dev/null 2>&1; then
            addgroup --system mock
        fi

        # Create necessary directories
        mkdir -p /var/lib/mock
        mkdir -p /var/cache/mock
        mkdir -p /etc/mock

        # Set permissions
        chown root:mock /var/lib/mock
        chown root:mock /var/cache/mock
        chmod 2775 /var/lib/mock
        chmod 2775 /var/cache/mock

        echo "Mock installed successfully!"
        echo "To use mock, add your user to the mock group:"
        echo "  sudo usermod -a -G mock \$USER"
        echo "Then log out and log back in."
        ;;
esac

#DEBHELPER#

exit 0
POSTINST

RUN chmod +x debian/postinst

# Build the package
RUN dpkg-buildpackage -us -uc -b

# List built packages
RUN ls -lh /build/*.deb

# Copy packages to output directory
CMD cp /build/*.deb /output/
EOF

    echo "Building Docker image for Ubuntu $UBUNTU_VERSION..."
    podman build -t mock-deb-builder-$UBUNTU_VERSION "$BUILD_DIR"

    echo
    echo "Building .deb package for Ubuntu $UBUNTU_VERSION..."
    mkdir -p "$BUILD_DIR/output"

    podman run --rm \
        -v "$BUILD_DIR/output:/output:z" \
        mock-deb-builder-$UBUNTU_VERSION

    echo
    echo "=== Build Complete for Ubuntu $UBUNTU_VERSION ==="
    echo

    if ls "$BUILD_DIR/output"/*.deb 1> /dev/null 2>&1; then
        echo "✓ .deb packages created:"
        ls -lh "$BUILD_DIR/output"/*.deb
        echo
    else
        echo "✗ No .deb packages were created for Ubuntu $UBUNTU_VERSION"
    fi

    echo
done

echo "=========================================="
echo "All Builds Complete"
echo "=========================================="
echo

# Summary
echo "Built packages:"
for UBUNTU_VERSION in $UBUNTU_VERSIONS; do
    BUILD_DIR="$PROJECT_ROOT/build/mock-deb-ubuntu-$UBUNTU_VERSION"
    if ls "$BUILD_DIR/output"/*.deb 1> /dev/null 2>&1; then
        echo
        echo "Ubuntu $UBUNTU_VERSION:"
        ls -lh "$BUILD_DIR/output"/*.deb | awk '{print "  " $9 " (" $5 ")"}'
    fi
done

echo
echo "To install on Ubuntu 22.04:"
echo "  sudo dpkg -i $PROJECT_ROOT/build/mock-deb-ubuntu-22.04/output/mock_*.deb"
echo
echo "To install on Ubuntu 24.04:"
echo "  sudo dpkg -i $PROJECT_ROOT/build/mock-deb-ubuntu-24.04/output/mock_*.deb"
echo
echo "To install on Ubuntu 25.10:"
echo "  sudo dpkg -i $PROJECT_ROOT/build/mock-deb-ubuntu-25.10/output/mock_*.deb"
echo
echo "After installation:"
echo "  sudo apt-get install -f  # Install any missing dependencies"
echo "  sudo usermod -a -G mock \$USER"
echo "  # Log out and log back in"
echo "  mock --version"
