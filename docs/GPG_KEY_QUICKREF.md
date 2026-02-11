# GPG Key Management - Quick Reference

## Quick Start

```bash
# Initial setup (run once)
./scripts/setup-gpg-keys.sh

# Manual update
./manage.py update_gpg_keys

# Check status
./manage.py update_gpg_keys --info
```

## Common Commands

| Command | Description |
|---------|-------------|
| `./manage.py update_gpg_keys` | Update keys if stale (>7 days) |
| `./manage.py update_gpg_keys --force` | Force update regardless of age |
| `./manage.py update_gpg_keys --info` | Show key information |
| `./manage.py update_gpg_keys --verify-only` | Check if keys are installed |
| `./scripts/setup-gpg-keys.sh` | Initial setup script |

## Configuration (.env)

```bash
# Enable/disable automatic updates
AUTO_UPDATE_GPG_KEYS=true

# Maximum age before update (days)
GPG_KEYS_MAX_AGE_DAYS=7

# Cache directory
GPG_KEYS_CACHE_DIR=/var/cache/reqpm/distribution-gpg-keys
```

## File Locations

| Path | Description |
|------|-------------|
| `/usr/share/distribution-gpg-keys/` | System keys (used by Mock) |
| `/var/cache/reqpm/distribution-gpg-keys/` | Local cache |
| `/var/cache/reqpm/distribution-gpg-keys/repo/` | Git repository |
| `/var/cache/reqpm/distribution-gpg-keys/.last_update` | Update timestamp |

## Troubleshooting

### Build Fails with GPG Error
```bash
./manage.py update_gpg_keys --force
```

### Check Key Status
```bash
./manage.py update_gpg_keys --info
./manage.py update_gpg_keys --verify-only
```

### View Update Logs
```bash
tail -f logs/django.log | grep -i gpg
```

### Check Celery Task
```bash
celery -A backend.reqpm inspect scheduled | grep update-gpg-keys
```

## How It Works

1. **Automatic**: Keys checked before each build (if >7 days old)
2. **Periodic**: Celery task runs every 12 hours
3. **Source**: https://github.com/rpm-software-management/distribution-gpg-keys
4. **Safe**: Backups created before updates

## Disable Automatic Updates

```bash
# In .env
AUTO_UPDATE_GPG_KEYS=false
```

Then update manually:
```bash
./manage.py update_gpg_keys
```

## Documentation

- Full guide: [docs/GPG_KEY_MANAGEMENT.md](GPG_KEY_MANAGEMENT.md)
- Implementation: [docs/GPG_KEY_AUTO_UPDATE_IMPLEMENTATION.md](GPG_KEY_AUTO_UPDATE_IMPLEMENTATION.md)
