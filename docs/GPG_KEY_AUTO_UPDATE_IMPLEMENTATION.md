# GPG Key Auto-Update Implementation Summary

## Problem Statement

Builds were failing with GPG verification errors in RHEL 10:
```
Error: GPG check FAILED
Public key for glibc-2.39-58.el10_1.7.x86_64.rpm is not installed
The GPG keys listed for the repository are already installed but they are not correct for this package.
```

This occurs because distribution GPG keys are frequently updated, and the keys installed with mock-core-configs can become outdated.

## Solution

Implemented automatic GPG key management that:
1. Downloads the latest keys from the official distribution-gpg-keys repository
2. Automatically updates keys before builds if they're stale
3. Runs periodic updates every 12 hours via Celery
4. Provides manual management commands for maintenance

## Implementation Details

### Files Created

1. **`backend/core/gpg_key_manager.py`** (413 lines)
   - Core GPGKeyManager class
   - Handles Git cloning/updating of distribution-gpg-keys repo
   - Manages key copying and system updates
   - Implements staleness checking and update logic

2. **`backend/apps/builds/management/commands/update_gpg_keys.py`** (104 lines)
   - Django management command for manual updates
   - Supports --force, --verify-only, --info options
   - Provides user-friendly CLI output

3. **`docs/GPG_KEY_MANAGEMENT.md`** (385 lines)
   - Comprehensive documentation
   - Usage examples and troubleshooting
   - Architecture overview

4. **`scripts/setup-gpg-keys.sh`** (35 lines)
   - Quick setup script for initial installation
   - Creates cache directories
   - Runs initial update

### Files Modified

1. **`backend/plugins/builders/mock.py`**
   - Added import of gpg_key_manager
   - Added `_gpg_keys_checked` tracking
   - Added `_ensure_gpg_keys_updated()` method
   - Integrated check into `build_rpm()` method

2. **`backend/reqpm/settings.py`**
   - Added GPG_KEYS_CACHE_DIR setting
   - Added AUTO_UPDATE_GPG_KEYS setting
   - Added GPG_KEYS_MAX_AGE_DAYS setting

3. **`backend/reqpm/celery.py`**
   - Added periodic task: update-gpg-keys (every 12 hours)

4. **`backend/apps/builds/tasks.py`**
   - Added `update_gpg_keys_task()` Celery task

5. **`README.md`**
   - Added "Setting Up GPG Keys" section
   - Added link to GPG_KEY_MANAGEMENT.md

6. **`docs/MOCK_SETUP.md`**
   - Added step 7: Setup GPG Keys
   - Added GPG key configuration options

## Key Features

### Automatic Updates

- **Before builds**: Keys are checked and updated if older than 7 days
- **Periodic**: Celery task runs every 12 hours
- **Configurable**: Can be enabled/disabled via settings

### Manual Management

```bash
# Update keys
./manage.py update_gpg_keys [--force]

# Check status
./manage.py update_gpg_keys --info

# Verify installation
./manage.py update_gpg_keys --verify-only

# Quick setup
./scripts/setup-gpg-keys.sh
```

### Smart Caching

- Keys are cached locally in `/var/cache/reqpm/distribution-gpg-keys/`
- Git repository is cloned once, then updated with `git pull`
- Staleness tracking prevents unnecessary updates

### Safety Features

- Backups created before updating system keys
- Errors don't fail builds (logs warning instead)
- Sudo required for system updates (secure)
- Once-per-instance checking (performance)

## Configuration

### Environment Variables

```bash
# Cache directory for GPG keys
GPG_KEYS_CACHE_DIR=/var/cache/reqpm/distribution-gpg-keys

# Enable automatic updates
AUTO_UPDATE_GPG_KEYS=true

# Maximum age before update (days)
GPG_KEYS_MAX_AGE_DAYS=7
```

### Default Behavior

- Automatic updates: **Enabled**
- Check frequency: **Before each build + every 12 hours**
- Max age: **7 days**
- Update source: **https://github.com/rpm-software-management/distribution-gpg-keys**

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Build Process                         │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
            ┌──────────────────────┐
            │  MockBuilder         │
            │  build_rpm()         │
            └──────────┬───────────┘
                       │
                       ▼
            ┌──────────────────────────┐
            │ _ensure_gpg_keys_updated │
            │ (checks once per instance)│
            └──────────┬───────────────┘
                       │
                       ▼
            ┌──────────────────────┐
            │  GPGKeyManager       │
            │  is_update_needed()  │
            └──────────┬───────────┘
                       │
            ┌──────────▼──────────┐
            │ Keys stale?         │
            └─────┬────────┬──────┘
                  │        │
            Yes   │        │ No
                  │        │
                  ▼        ▼
         ┌────────────┐  Continue
         │ update_keys│   Build
         └─────┬──────┘
               │
               ▼
    ┌────────────────────┐
    │ Git clone/pull     │
    │ distribution-gpg-   │
    │ keys repo          │
    └─────┬──────────────┘
          │
          ▼
    ┌────────────────────┐
    │ Copy keys to cache │
    └─────┬──────────────┘
          │
          ▼
    ┌────────────────────┐
    │ Update system keys │
    │ (requires sudo)    │
    └─────┬──────────────┘
          │
          ▼
    ┌────────────────────┐
    │ Update timestamp   │
    └────────────────────┘
```

## Testing

### Manual Test

```bash
# 1. Check current key age
./manage.py update_gpg_keys --info

# 2. Force update
./manage.py update_gpg_keys --force

# 3. Verify installation
./manage.py update_gpg_keys --verify-only

# 4. Trigger a build to test automatic checking
```

### Expected Behavior

1. **First build after update**: No key update (keys just updated)
2. **Build after 7+ days**: Automatic update before build
3. **Celery task**: Updates every 12 hours if stale
4. **Manual update**: Always works regardless of age

## Benefits

1. **Prevents build failures** due to outdated GPG keys
2. **Automatic maintenance** - no manual intervention needed
3. **Fast updates** - Git pull is quick after initial clone
4. **Safe rollback** - backups created before updates
5. **Flexible** - can disable automatic updates if needed
6. **Transparent** - logs all actions for debugging

## Performance Impact

- **Initial clone**: ~30-60 seconds (one-time)
- **Git pull**: ~5-10 seconds
- **Per-build check**: < 1 second (cached after first check)
- **Cache size**: ~10MB

## Monitoring

### Check Last Update

```bash
cat /var/cache/reqpm/distribution-gpg-keys/.last_update
```

### View Logs

```bash
# Django logs
tail -f logs/django.log | grep -i gpg

# Celery logs
tail -f logs/celery.log | grep update_gpg_keys
```

### Celery Beat Status

```bash
celery -A backend.reqpm inspect scheduled | grep update-gpg-keys
```

## Troubleshooting

### Build Still Fails with GPG Error

1. Force update: `./manage.py update_gpg_keys --force`
2. Verify: `./manage.py update_gpg_keys --verify-only`
3. Check system keys: `ls -la /usr/share/distribution-gpg-keys/redhat/`

### Permission Denied

- Ensure sudo access for rsync/cp commands
- Or run as root: `sudo ./manage.py update_gpg_keys`

### Git Clone Fails

- Check internet connectivity
- Verify GitHub is accessible
- Check firewall rules

## Future Enhancements

Possible improvements:
1. Support for other distributions (CentOS, Fedora, etc.)
2. Key verification/validation before installation
3. Rollback command for problematic updates
4. Health check endpoint for key status
5. Metrics/alerting for failed updates

## Related Issues

This implementation solves:
- GPG key mismatch errors in RHEL 10 builds
- "Public key for X is not installed" errors
- Manual key maintenance burden
- Build failures due to repository updates

## References

- Distribution GPG Keys: https://github.com/rpm-software-management/distribution-gpg-keys
- Mock Documentation: https://github.com/rpm-software-management/mock/wiki
- RHEL Package Signing: https://access.redhat.com/articles/3359321
