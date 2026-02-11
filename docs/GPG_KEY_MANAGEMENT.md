# GPG Key Management

ReqPM includes automatic GPG key management to prevent build failures due to outdated or missing GPG keys. This is especially important for RHEL builds where GPG keys are frequently updated.

## Overview

The GPG key management system:
- Automatically downloads and updates GPG keys from the [distribution-gpg-keys](https://github.com/rpm-software-management/distribution-gpg-keys) repository
- Keeps keys up to date with periodic checks (every 12 hours by default)
- Prevents build failures due to GPG signature verification errors
- Automatically updates keys before each build if they're stale (older than 7 days)

## How It Works

### Automatic Updates

1. **Before Builds**: The mock builder automatically checks if GPG keys are up to date before starting a build
2. **Periodic Task**: A Celery task runs every 12 hours to update keys proactively
3. **Manual Updates**: You can manually trigger updates using the management command

### Key Storage

- **System Keys**: `/usr/share/distribution-gpg-keys/` (used by Mock)
- **Cache**: `/var/cache/reqpm/distribution-gpg-keys/` (local copy)
- **Repository Clone**: `/var/cache/reqpm/distribution-gpg-keys/repo/` (Git clone)

## Configuration

Add these settings to your `.env` file or Django settings:

```bash
# GPG key cache directory
GPG_KEYS_CACHE_DIR=/var/cache/reqpm/distribution-gpg-keys

# Enable/disable automatic GPG key updates
AUTO_UPDATE_GPG_KEYS=true

# Maximum age of GPG keys before update (in days)
GPG_KEYS_MAX_AGE_DAYS=7
```

### Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `GPG_KEYS_CACHE_DIR` | `/var/cache/reqpm/distribution-gpg-keys` | Directory to cache GPG keys |
| `AUTO_UPDATE_GPG_KEYS` | `true` | Enable automatic updates before builds |
| `GPG_KEYS_MAX_AGE_DAYS` | `7` | Maximum age before keys are considered stale |

## Manual Management

### Update GPG Keys

Update GPG keys manually:

```bash
# Update keys if stale (older than 7 days)
./manage.py update_gpg_keys

# Force update regardless of age
./manage.py update_gpg_keys --force

# Show information about cached keys
./manage.py update_gpg_keys --info

# Show info for specific distribution
./manage.py update_gpg_keys --info --distribution centos

# Verify keys are properly installed
./manage.py update_gpg_keys --verify-only
```

### Check Key Status

```bash
# View key information
./manage.py update_gpg_keys --info

# Output:
# GPG Key Information for redhat:
#   Cache age: 2 days
#   Found 15 keys:
#     - RPM-GPG-KEY-redhat10-release (1234 bytes)
#     - RPM-GPG-KEY-redhat9-release (1234 bytes)
#     ...
```

## Troubleshooting

### Build Fails with GPG Key Errors

If you see errors like:
```
Error: GPG check FAILED
Public key for glibc-2.39-58.el10_1.7.x86_64.rpm is not installed
GPG Keys are configured as: file:///usr/share/distribution-gpg-keys/redhat/RPM-GPG-KEY-redhat10-release
```

**Solution**: Update GPG keys manually:

```bash
./manage.py update_gpg_keys --force
```

### Keys Not Being Updated Automatically

1. **Check Celery is running**:
   ```bash
   ./reqpm.sh status celery-beat
   ```

2. **Check automatic updates are enabled**:
   ```bash
   grep AUTO_UPDATE_GPG_KEYS .env
   # Should show: AUTO_UPDATE_GPG_KEYS=true
   ```

3. **Check Celery beat schedule**:
   ```bash
   celery -A backend.reqpm inspect scheduled
   ```

### Permission Issues

If you get permission errors when updating system keys:

1. **Ensure sudo access**: The update process requires sudo to update `/usr/share/distribution-gpg-keys/`

2. **Configure sudo without password** (optional):
   ```bash
   sudo visudo
   # Add:
   # yourusername ALL=(ALL) NOPASSWD: /usr/bin/rsync, /usr/bin/cp
   ```

3. **Or run update with sudo**:
   ```bash
   sudo ./manage.py update_gpg_keys
   ```

### Check System Keys Directory

Verify the system keys are properly installed:

```bash
ls -la /usr/share/distribution-gpg-keys/redhat/
```

You should see multiple `RPM-GPG-KEY-*` files.

## How GPG Key Updates Work

### Update Process

1. **Clone/Update Repository**: Git clone or pull the distribution-gpg-keys repository
2. **Copy to Cache**: Copy keys from repository to local cache
3. **Update System**: Sync keys to `/usr/share/distribution-gpg-keys/` (requires sudo)
4. **Create Backup**: Existing keys are backed up before updating
5. **Update Timestamp**: Record update time for staleness checks

### Backup Files

When keys are updated, a backup is created:
```
/usr/share/distribution-gpg-keys.backup.20260211143522/
```

These backups can be used to rollback if needed:
```bash
sudo rm -rf /usr/share/distribution-gpg-keys
sudo mv /usr/share/distribution-gpg-keys.backup.20260211143522 /usr/share/distribution-gpg-keys
```

## Architecture

### Components

1. **GPGKeyManager** (`backend/core/gpg_key_manager.py`)
   - Core logic for downloading and updating keys
   - Handles Git operations, file copying, and system updates

2. **Management Command** (`backend/apps/builds/management/commands/update_gpg_keys.py`)
   - Django command for manual updates
   - Provides CLI interface with various options

3. **Celery Task** (`backend/apps/builds/tasks.py::update_gpg_keys_task`)
   - Periodic task that runs every 12 hours
   - Automatically updates stale keys

4. **Mock Builder Integration** (`backend/plugins/builders/mock.py::_ensure_gpg_keys_updated`)
   - Checks key freshness before each build
   - Updates keys if stale (once per builder instance)

### Integration Flow

```
Build Started
    ↓
MockBuilder.__init__()
    ↓
build_rpm() called
    ↓
_ensure_gpg_keys_updated()
    ↓
Check if keys are stale
    ↓
If stale → Update keys
    ↓
Continue with build
```

## Monitoring

### Check Last Update

```bash
cat /var/cache/reqpm/distribution-gpg-keys/.last_update
# Output: 2026-02-11T14:35:22.123456
```

### View Update Logs

```bash
# Check Django logs for GPG key updates
tail -f logs/django.log | grep GPG

# Check Celery logs
tail -f logs/celery.log | grep update_gpg_keys
```

### Celery Task Status

```bash
# Check if update task is scheduled
celery -A backend.reqpm inspect scheduled | grep update-gpg-keys

# Check recent task results
celery -A backend.reqpm result <task-id>
```

## Performance Considerations

- **Initial Update**: First update downloads ~10MB and may take 30-60 seconds
- **Subsequent Updates**: Git pull is faster, usually < 10 seconds
- **Build Impact**: Key check adds < 1 second to build time
- **Cache Efficiency**: Keys are checked once per builder instance, not per build

## Best Practices

1. **Run Initial Update**: Update keys manually when first setting up:
   ```bash
   ./manage.py update_gpg_keys --force
   ```

2. **Monitor Updates**: Check logs periodically to ensure updates are working

3. **Keep Celery Beat Running**: Ensure celery-beat is running for automatic updates

4. **Test After Updates**: After a manual update, test a build to ensure it works

5. **Backup Before Changes**: Keys are backed up automatically, but you can create manual backups:
   ```bash
   sudo cp -a /usr/share/distribution-gpg-keys /usr/share/distribution-gpg-keys.manual.backup
   ```

## Disabling Automatic Updates

If you prefer to manage keys manually:

1. **Disable in settings**:
   ```bash
   # In .env
   AUTO_UPDATE_GPG_KEYS=false
   ```

2. **Update keys manually** as needed:
   ```bash
   ./manage.py update_gpg_keys
   ```

## Related Documentation

- [Mock Setup Guide](MOCK_SETUP.md)
- [Build System Documentation](BUILD_CONCURRENCY.md)
- [Troubleshooting Guide](TROUBLESHOOTING.md)
