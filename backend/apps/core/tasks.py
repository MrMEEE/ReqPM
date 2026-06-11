"""
Celery tasks for the core app (AI model management).
"""
import logging
from pathlib import Path

from celery import shared_task
from django.core.cache import cache

logger = logging.getLogger(__name__)

DOWNLOAD_STATUS_KEY = 'ai_model_download:{key}'
DOWNLOAD_STATUS_TTL = 3600


def get_download_status(model_key: str) -> dict:
    """Current download status for a model (or empty dict)."""
    return cache.get(DOWNLOAD_STATUS_KEY.format(key=model_key)) or {}


def _set_status(model_key: str, **status):
    cache.set(DOWNLOAD_STATUS_KEY.format(key=model_key), status, DOWNLOAD_STATUS_TTL)


@shared_task(bind=True)
def download_ai_model_task(self, model_key: str):
    """
    Download a GGUF model from the catalog into data/models/ with progress
    reporting via the Django cache (read by the Settings UI).
    """
    import requests
    from backend.core.ai_fixer import MODEL_CATALOG, model_path

    entry = MODEL_CATALOG.get(model_key)
    if not entry:
        _set_status(model_key, state='error', error=f'Unknown model: {model_key}')
        return

    dest = model_path(model_key)
    part = dest.parent / (dest.name + '.part')

    if dest.exists() and not part.exists():
        _set_status(model_key, state='done', progress=100)
        return

    _set_status(model_key, state='downloading', progress=0, downloaded_mb=0,
                total_mb=entry['size_mb'])
    logger.info(f'Downloading AI model {model_key} from {entry["url"]}')

    try:
        with requests.get(entry['url'], stream=True, timeout=60,
                          allow_redirects=True) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get('Content-Length', 0)) or entry['size_mb'] * 1024 * 1024
            done = 0
            last_pct = -1
            with open(part, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    pct = min(99, int(done * 100 / total))
                    if pct != last_pct:
                        last_pct = pct
                        _set_status(model_key, state='downloading', progress=pct,
                                    downloaded_mb=done // (1024 * 1024),
                                    total_mb=total // (1024 * 1024))

        part.rename(dest)
        _set_status(model_key, state='done', progress=100)
        logger.info(f'AI model {model_key} downloaded to {dest}')

    except Exception as e:
        logger.error(f'AI model download failed for {model_key}: {e}')
        _set_status(model_key, state='error', error=str(e)[:300])
        try:
            Path(part).unlink(missing_ok=True)
        except OSError:
            pass
