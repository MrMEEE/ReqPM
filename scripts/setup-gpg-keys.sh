#!/bin/bash
# Initialize GPG keys for ReqPM builds
set -e

echo "=== ReqPM GPG Key Setup ==="
echo

# Check if Django is accessible
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed"
    exit 1
fi

# Check if we're in the correct directory
if [ ! -f "manage.py" ]; then
    echo "Error: manage.py not found. Run this script from the ReqPM root directory"
    exit 1
fi

# Get the project root directory
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Cache directory for GPG keys (configurable via environment variable)
CACHE_DIR="${GPG_KEYS_CACHE_DIR:-$PROJECT_ROOT/data/gpg_keys_cache}"
echo "Creating cache directory: $CACHE_DIR"
mkdir -p "$CACHE_DIR"

# Update GPG keys
echo
echo "Updating GPG keys from distribution-gpg-keys repository..."
echo "This may take a minute on first run..."
echo

python3 manage.py update_gpg_keys --force

echo
echo "=== GPG Key Setup Complete ==="
echo
echo "GPG keys have been installed to:"
echo "  - System: /usr/share/distribution-gpg-keys/"
echo "  - Cache:  $CACHE_DIR"
echo
echo "Keys will be automatically updated:"
echo "  - Before each build (if older than 7 days)"
echo "  - Every 12 hours via Celery Beat"
echo
echo "To manually update keys:"
echo "  ./manage.py update_gpg_keys"
echo
echo "To check key status:"
echo "  ./manage.py update_gpg_keys --info"
echo
