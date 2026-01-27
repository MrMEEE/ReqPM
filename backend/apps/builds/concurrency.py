"""
Build concurrency control using Redis-based semaphore
"""
import redis
import time
import logging
from django.conf import settings
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class BuildConcurrencyLimiter:
    """
    Limits the number of concurrent builds using Redis semaphore
    """
    
    def __init__(self, max_concurrent=None):
        """
        Initialize the concurrency limiter
        
        Args:
            max_concurrent: Maximum number of concurrent builds (default from settings)
        """
        self.max_concurrent = max_concurrent or settings.REQPM.get('MAX_CONCURRENT_BUILDS', 4)
        self.redis_client = redis.from_url(settings.CELERY_BROKER_URL)
        self.semaphore_key = 'reqpm:build:semaphore'
        self.lock_timeout = 7200  # 2 hours max per build
    
    @contextmanager
    def acquire(self, build_id, timeout=10):
        """
        Acquire a build slot with timeout
        
        Args:
            build_id: Unique identifier for this build
            timeout: How long to wait for a slot (seconds)
        
        Yields:
            True if acquired, raises exception on timeout
        """
        acquired = False
        start_time = time.time()
        
        try:
            # Try to acquire a slot
            while time.time() - start_time < timeout:
                # Get current number of active builds
                active_count = self.redis_client.scard(self.semaphore_key)
                
                if active_count < self.max_concurrent:
                    # Add this build to active set
                    if self.redis_client.sadd(self.semaphore_key, build_id):
                        # Set expiration on the member (cleanup safety)
                        self.redis_client.expire(self.semaphore_key, self.lock_timeout)
                        acquired = True
                        logger.info(f"Build {build_id} acquired slot ({active_count + 1}/{self.max_concurrent})")
                        yield True
                        return
                
                # Wait a bit before retrying
                time.sleep(0.5)
            
            # Timeout reached
            raise TimeoutError(
                f"Could not acquire build slot after {timeout}s. "
                f"Max concurrent builds: {self.max_concurrent}. "
                f"Consider increasing MAX_CONCURRENT_BUILDS setting."
            )
        
        finally:
            # Release the slot
            if acquired:
                removed = self.redis_client.srem(self.semaphore_key, build_id)
                if removed:
                    active_count = self.redis_client.scard(self.semaphore_key)
                    logger.info(f"Build {build_id} released slot ({active_count}/{self.max_concurrent})")
    
    def get_active_builds(self):
        """Get list of currently active build IDs"""
        return [
            member.decode('utf-8') if isinstance(member, bytes) else member
            for member in self.redis_client.smembers(self.semaphore_key)
        ]
    
    def get_active_count(self):
        """Get number of currently active builds"""
        return self.redis_client.scard(self.semaphore_key)
    
    def force_release(self, build_id):
        """Force release a specific build slot"""
        return self.redis_client.srem(self.semaphore_key, build_id)
    
    def clear_all(self):
        """Clear all build slots (use with caution!)"""
        return self.redis_client.delete(self.semaphore_key)


# Global instance
limiter = BuildConcurrencyLimiter()
