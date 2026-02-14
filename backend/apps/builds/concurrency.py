"""
Job concurrency control using Redis-based semaphore
Limits concurrent execution of all intensive tasks (builds, spec generation, etc.)
"""
import redis
import time
import logging
from django.conf import settings
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Lua script for atomic acquire: checks set size and adds member in one call.
# Returns 1 if the slot was acquired, 0 if the set is already full.
_ACQUIRE_LUA = """
local key = KEYS[1]
local job_id = ARGV[1]
local max = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
if redis.call('scard', key) < max then
    redis.call('sadd', key, job_id)
    redis.call('expire', key, ttl)
    return 1
end
return 0
"""


class JobConcurrencyLimiter:
    """
    Limits the number of concurrent jobs using Redis semaphore.
    Uses an atomic Lua script so the check-and-add cannot race.
    """
    
    def __init__(self, max_concurrent=None):
        """
        Initialize the concurrency limiter
        
        Args:
            max_concurrent: Maximum number of concurrent jobs (default from settings)
        """
        self.max_concurrent = max_concurrent or settings.REQPM.get('MAX_CONCURRENT_BUILDS', 4)
        self.redis_client = redis.from_url(settings.CELERY_BROKER_URL)
        self.semaphore_key = 'reqpm:job:semaphore'
        self.lock_timeout = 7200  # 2 hours max per job
        self._acquire_script = self.redis_client.register_script(_ACQUIRE_LUA)
    
    @contextmanager
    def acquire(self, job_id, timeout=None):
        """
        Acquire a job slot, waiting indefinitely if needed
        
        Args:
            job_id: Unique identifier for this job (e.g., 'build_123', 'spec_456')
            timeout: How long to wait for a slot (seconds). None = wait forever
        
        Yields:
            True if acquired, raises exception on timeout (if timeout is set)
        """
        acquired = False
        start_time = time.time()
        
        try:
            # Try to acquire a slot
            while True:
                # Check timeout if set
                if timeout is not None and time.time() - start_time >= timeout:
                    raise TimeoutError(
                        f"Could not acquire job slot after {timeout}s. "
                        f"Max concurrent jobs: {self.max_concurrent}. "
                        f"Consider increasing MAX_CONCURRENT_BUILDS setting."
                    )
                
                # Atomic check-and-add via Lua script
                result = self._acquire_script(
                    keys=[self.semaphore_key],
                    args=[job_id, self.max_concurrent, self.lock_timeout],
                )
                
                if result:
                    acquired = True
                    active_count = self.redis_client.scard(self.semaphore_key)
                    logger.info(f"Job {job_id} acquired slot ({active_count}/{self.max_concurrent})")
                    yield True
                    return
                
                # Wait a bit before retrying
                time.sleep(5)
        
        finally:
            # Release the slot
            if acquired:
                removed = self.redis_client.srem(self.semaphore_key, job_id)
                if removed:
                    active_count = self.redis_client.scard(self.semaphore_key)
                    logger.info(f"Job {job_id} released slot ({active_count}/{self.max_concurrent})")
    
    def get_active_jobs(self):
        """Get list of currently active job IDs"""
        return [
            member.decode('utf-8') if isinstance(member, bytes) else member
            for member in self.redis_client.smembers(self.semaphore_key)
        ]
    
    @contextmanager
    def try_acquire(self, job_id):
        """
        Non-blocking acquire: try once and either yield True or raise TimeoutError.
        Does NOT block the calling thread/worker.
        """
        acquired = False
        try:
            result = self._acquire_script(
                keys=[self.semaphore_key],
                args=[job_id, self.max_concurrent, self.lock_timeout],
            )
            if result:
                acquired = True
                active_count = self.redis_client.scard(self.semaphore_key)
                logger.info(f"Job {job_id} acquired slot ({active_count}/{self.max_concurrent})")
                yield True
            else:
                raise TimeoutError(
                    f"No build slot available (0/{self.max_concurrent} free). "
                    f"Will retry when a slot opens up."
                )
        finally:
            if acquired:
                removed = self.redis_client.srem(self.semaphore_key, job_id)
                if removed:
                    active_count = self.redis_client.scard(self.semaphore_key)
                    logger.info(f"Job {job_id} released slot ({active_count}/{self.max_concurrent})")
    
    def get_active_count(self):
        """Get number of currently active jobs"""
        return self.redis_client.scard(self.semaphore_key)
    
    def force_release(self, job_id):
        """Force release a specific job slot"""
        return self.redis_client.srem(self.semaphore_key, job_id)
    
    def clear_all(self):
        """Clear all job slots (use with caution!)"""
        return self.redis_client.delete(self.semaphore_key)


# Global instance
limiter = JobConcurrencyLimiter()
