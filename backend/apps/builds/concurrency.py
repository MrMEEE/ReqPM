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
if redis.call('sismember', key, job_id) == 1 then
    return 0
end
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
    Also prevents duplicate acquisition of the same job_id.
    """
    
    def __init__(
        self,
        max_concurrent=None,
        semaphore_key='reqpm:job:semaphore',
        use_db_setting=True,
        slot_label='build',
    ):
        """
        Initialize the concurrency limiter
        
        Args:
            max_concurrent: Maximum number of concurrent jobs (default from settings)
            semaphore_key: Redis key holding the active job ids
            use_db_setting: Read the limit from SystemSettings.max_concurrent_builds
            slot_label: Name used in "no slot available" messages
        """
        self._default_max_concurrent = max_concurrent or settings.REQPM.get('MAX_CONCURRENT_BUILDS', 4)
        self.redis_client = redis.from_url(settings.CELERY_BROKER_URL)
        self.semaphore_key = semaphore_key
        self.orphan_suspect_key = f'{semaphore_key}:orphan_suspects'
        self.use_db_setting = use_db_setting
        self.slot_label = slot_label
        self.lock_timeout = 7200  # 2 hours max per job
        self._acquire_script = self.redis_client.register_script(_ACQUIRE_LUA)

    @property
    def max_concurrent(self):
        """Return the current concurrency limit from DB-backed settings."""
        if not self.use_db_setting:
            return int(self._default_max_concurrent)
        try:
            from backend.apps.core.models import SystemSettings

            return int(SystemSettings.load().max_concurrent_builds or self._default_max_concurrent)
        except Exception:
            return int(self._default_max_concurrent)
    
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
                        f"Consider increasing Maximum Concurrent Builds in Settings."
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
                    f"No {self.slot_label} slot available (0/{self.max_concurrent} free). "
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
    
    # Slot job-id prefix -> Celery task whose first argument is the id suffix.
    SLOT_OWNER_TASKS = (
        ('build_package_', 'backend.apps.packages.tasks.build_single_package_task'),
        ('fetch_', 'backend.apps.packages.tasks.fetch_package_source_task'),
        ('spec_', 'backend.apps.packages.tasks.generate_spec_file_task'),
        ('build_', 'backend.apps.builds.tasks.build_package_task'),
    )

    @classmethod
    def slot_owner(cls, job_id):
        """Return (task_name, object_id) for a slot job id, or None if unknown."""
        for prefix, task_name in cls.SLOT_OWNER_TASKS:
            suffix = job_id[len(prefix):]
            if job_id.startswith(prefix) and suffix.isdigit():
                return task_name, int(suffix)
        return None

    def reclaim_orphaned_slots(self, active_task_args):
        """
        Release slots whose owning task is no longer executing (e.g. the worker
        child was SIGKILLed by a cancel or the OOM killer before ``finally`` ran).

        ``active_task_args`` maps task name -> set of first args for tasks that
        are currently *executing*. A slot is only released after it has looked
        orphaned on two consecutive calls, so a task that acquired its slot
        between the inspect call and this check is never released.
        """
        suspects = {
            m.decode('utf-8') if isinstance(m, bytes) else m
            for m in self.redis_client.smembers(self.orphan_suspect_key)
        }
        orphaned = set()
        for job_id in self.get_active_jobs():
            owner = self.slot_owner(job_id)
            if owner is None:
                continue
            task_name, object_id = owner
            if object_id not in active_task_args.get(task_name, set()):
                orphaned.add(job_id)

        released = []
        for job_id in orphaned & suspects:
            if self.force_release(job_id):
                released.append(job_id)
                logger.warning(f"Released orphaned job slot {job_id} (owning task is no longer running)")

        pipe = self.redis_client.pipeline()
        pipe.delete(self.orphan_suspect_key)
        new_suspects = orphaned - set(released)
        if new_suspects:
            pipe.sadd(self.orphan_suspect_key, *new_suspects)
            pipe.expire(self.orphan_suspect_key, 600)
        pipe.execute()
        return released

    def force_release(self, job_id):
        """Force release a specific job slot"""
        return self.redis_client.srem(self.semaphore_key, job_id)
    
    def clear_all(self):
        """Clear all job slots (use with caution!)"""
        return self.redis_client.delete(self.semaphore_key)


# Global instances: RPM builds, and lighter non-build jobs (fetch/spec) which
# get their own slots so a full build pool never blocks them.
limiter = JobConcurrencyLimiter()
task_limiter = JobConcurrencyLimiter(
    max_concurrent=settings.REQPM.get('MAX_CONCURRENT_TASKS', 2),
    semaphore_key='reqpm:task:semaphore',
    use_db_setting=False,
    slot_label='task',
)
