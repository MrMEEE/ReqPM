# Mock Setup Guide

This guide explains how to set up Mock for building RPM packages in ReqPM.

## Platform-Specific Guides

Choose the guide for your operating system:

- **RHEL/Fedora/CentOS**: Continue reading this document
- **Ubuntu/Debian**: See [MOCK_SETUP_UBUNTU.md](MOCK_SETUP_UBUNTU.md)

## What is Mock?

Mock is a tool for building RPMs in a clean, isolated chroot environment. It's the standard tool used for building RPMs for Fedora, RHEL, and CentOS.

## Prerequisites

- RHEL/Fedora/CentOS system (or compatible distribution)
- Root/sudo access
- At least 10GB of free disk space for build environments

**Note:** For Ubuntu/Debian systems, see [MOCK_SETUP_UBUNTU.md](MOCK_SETUP_UBUNTU.md) for installation from source.

## Installation Steps (RHEL/Fedora/CentOS)

### 1. Install Mock

**On RHEL 8/9/10:**
```bash
sudo dnf install mock
```

**On Fedora:**
```bash
sudo dnf install mock
```

**On CentOS:**
```bash
sudo yum install epel-release  # Enable EPEL repository
sudo yum install mock
```

**On Ubuntu/Debian:**
```bash
# Use our automated installation script
./scripts/install-mock-ubuntu.sh
# See docs/MOCK_SETUP_UBUNTU.md for details
```

### 2. Add Your User to the Mock Group

Mock requires special permissions. Add your user to the `mock` group:

```bash
sudo usermod -a -G mock $USER
```

**Important:** After adding yourself to the mock group, you must log out and log back in (or reboot) for the group membership to take effect.

Verify you're in the mock group:
```bash
groups | grep mock
```

### 3. Verify Mock Installation

Check that Mock is installed and accessible:

```bash
mock --version
```

You should see output like:
```
4.3
```

### 4. Test Mock Access

Try listing available Mock configurations:

```bash
mock --list-chroots
```

If you see a list of available build targets (like `rhel-8-x86_64`, `rhel-9-x86_64`), Mock is properly configured.

### 5. Install RHEL Mock Configurations

For building RHEL packages, you need the appropriate Mock configurations:

**RHEL 8:**
```bash
sudo dnf install mock-core-configs
```

**RHEL 9/10:**
The configs should be included with mock by default, but verify:
```bash
ls /etc/mock/ | grep rhel
```

You should see files like:
- `rhel-8-x86_64.cfg`
- `rhel-9-x86_64.cfg`
- `rhel-10-x86_64.cfg`

### 6. Configure Mock Cache (Optional but Recommended)

To speed up builds, configure a persistent cache:

Create mock cache directory:
```bash
sudo mkdir -p /var/cache/mock
sudo chown root:mock /var/cache/mock
sudo chmod 2775 /var/cache/mock
```

This allows Mock to cache downloaded packages between builds.

### 7. Update ReqPM Configuration

The default ReqPM configuration should work, but you can customize Mock settings in your `.env` file if needed:

```bash
# Optional: Override default Mock configuration directory
MOCK_CONFIG_DIR=/etc/mock

# Optional: Override default Mock cache directory
MOCK_CACHE_DIR=/var/cache/mock
```

### 8. Restart ReqPM Services

After Mock is installed and configured, restart ReqPM to pick up the changes:

```bash
./reqpm.sh restart all
```

## Verifying the Setup

### Test Mock Build

Create a simple test spec file to verify Mock is working:

```bash
# Create a test directory
mkdir -p ~/mock-test
cd ~/mock-test

# Create a simple test spec
cat > test.spec <<'EOF'
Name:           test-package
Version:        1.0
Release:        1%{?dist}
Summary:        Test package

License:        MIT
URL:            https://example.com

%description
A test package to verify Mock is working.

%prep

%build

%install
mkdir -p %{buildroot}/usr/share/test-package
echo "Hello from Mock" > %{buildroot}/usr/share/test-package/test.txt

%files
/usr/share/test-package/test.txt

%changelog
* Sat Jan 25 2026 Test User <test@example.com> - 1.0-1
- Initial test package
EOF

# Try to build with Mock
mock -r rhel-9-x86_64 --buildsrpm --spec test.spec --sources .
```

If this succeeds, Mock is properly configured!

### Test in ReqPM

1. Log into ReqPM web interface
2. Go to a project
3. Click "Start Build"
4. Select RHEL versions to build
5. Click "Start Build"
6. Go to the **Builds** page to monitor progress
7. Go to the **Tasks** page to see detailed task execution

If Mock is properly configured, you should see builds progressing instead of failing with "Mock builder not available".

## Troubleshooting

### Permission Denied

**Error:** `ERROR: Could not open /var/lib/mock`

**Solution:** Make sure you're in the mock group and have logged out/in:
```bash
groups | grep mock
```

If not in the group:
```bash
sudo usermod -a -G mock $USER
```
Then log out and log back in.

### Mock Configs Not Found

**Error:** `ERROR: Could not find configuration`

**Solution:** Install mock-core-configs:
```bash
sudo dnf install mock-core-configs
```

### Disk Space Issues

**Error:** `ERROR: No space left on device`

**Solution:** Mock builds can use significant disk space. Clean up old build roots:
```bash
sudo mock --clean --scrub=all
```

Or configure a different cache directory with more space in `.env`:
```bash
MOCK_CACHE_DIR=/path/to/larger/disk/mock-cache
```

### SELinux Issues

If you're running with SELinux enabled and getting permission errors:

```bash
sudo setsebool -P mock_enable_homedirs 1
```

## Alternative: Docker-based Builds (Future Enhancement)

If Mock cannot be installed or configured on your system, ReqPM can be extended to support Docker-based builds as an alternative. This would allow building RPMs without requiring Mock to be installed on the host system.

Contact the ReqPM maintainers if you need this feature.

## Additional Resources

- [Mock Official Documentation](https://github.com/rpm-software-management/mock/wiki)
- [Fedora Mock Guide](https://fedoraproject.org/wiki/Mock)
- [RHEL RPM Building Guide](https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/)
