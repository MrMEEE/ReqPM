"""
Build management models
"""
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from backend.apps.projects.models import Project
from backend.apps.packages.models import Package


class BuildJob(models.Model):
    """
    Represents a complete build job for a project
    """
    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending')
        PREPARING = 'preparing', _('Preparing')
        QUEUED = 'queued', _('Queued')
        RUNNING = 'running', _('Running')
        COMPLETED = 'completed', _('Completed')
        FAILED = 'failed', _('Failed')
        CANCELLED = 'cancelled', _('Cancelled')
    
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='build_jobs'
    )
    
    # Build configuration
    build_version = models.CharField(max_length=50)
    git_ref = models.CharField(max_length=255)
    git_commit = models.CharField(max_length=40)
    rhel_versions = models.JSONField(default=list)
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    status_message = models.TextField(blank=True)
    
    # Progress tracking
    total_packages = models.IntegerField(default=0)
    completed_packages = models.IntegerField(default=0)
    failed_packages = models.IntegerField(default=0)
    
    # Celery task tracking
    celery_task_id = models.CharField(max_length=255, blank=True)
    
    # User
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='triggered_builds'
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'build_jobs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['project', 'status']),
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"Build #{self.id} - {self.project.name} v{self.build_version}"
    
    @property
    def progress_percentage(self):
        """Calculate build progress percentage"""
        if self.total_packages == 0:
            return 0
        return int((self.completed_packages / self.total_packages) * 100)


class BuildQueue(models.Model):
    """
    Queue for managing build order based on dependencies
    """
    class Status(models.TextChoices):
        QUEUED = 'queued', _('Queued')
        BUILDING = 'building', _('Building')
        COMPLETED = 'completed', _('Completed')
        FAILED = 'failed', _('Failed')
        BLOCKED = 'blocked', _('Blocked')
        CANCELLED = 'cancelled', _('Cancelled')
    
    build_job = models.ForeignKey(
        BuildJob,
        on_delete=models.CASCADE,
        related_name='queue_items'
    )
    package = models.ForeignKey(
        Package,
        on_delete=models.CASCADE,
        related_name='queue_items'
    )
    
    # Build targets
    rhel_version = models.CharField(max_length=20)
    architecture = models.CharField(max_length=20, default='x86_64')
    
    # Queue information
    priority = models.IntegerField(
        default=0,
        help_text=_('Higher priority builds first')
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED
    )
    
    # Dependencies check
    dependencies_met = models.BooleanField(default=False)
    blocked_by = models.ManyToManyField(
        'self',
        symmetrical=False,
        blank=True,
        related_name='blocking'
    )
    
    # Celery task
    celery_task_id = models.CharField(max_length=255, blank=True)
    
    # Build output
    build_log = models.TextField(blank=True, help_text=_('Build output log'))
    error_message = models.TextField(blank=True, help_text=_('Error message if build failed'))
    
    # Build artifacts
    srpm_path = models.CharField(max_length=500, blank=True)
    rpm_path = models.CharField(max_length=500, blank=True)
    
    # Retry information
    retry_count = models.IntegerField(default=0)
    max_retries = models.IntegerField(default=3)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'build_queue'
        ordering = ['-priority', 'package__build_order', 'created_at']
        indexes = [
            models.Index(fields=['build_job', 'status']),
            models.Index(fields=['status', 'dependencies_met']),
            models.Index(fields=['package']),
        ]
    
    def __str__(self):
        return f"{self.package.name} (RHEL {self.rhel_version}) - {self.status}"


class BuildWorker(models.Model):
    """
    Tracks build worker status
    """
    class Status(models.TextChoices):
        ONLINE = 'online', _('Online')
        BUSY = 'busy', _('Busy')
        OFFLINE = 'offline', _('Offline')
    
    hostname = models.CharField(max_length=255, unique=True)
    celery_worker_name = models.CharField(max_length=255)
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OFFLINE
    )
    
    # Capabilities
    max_concurrent_builds = models.IntegerField(default=1)
    current_builds = models.IntegerField(default=0)
    
    # Statistics
    total_builds = models.IntegerField(default=0)
    successful_builds = models.IntegerField(default=0)
    failed_builds = models.IntegerField(default=0)
    
    # Timestamps
    last_heartbeat = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'build_workers'
        ordering = ['hostname']
    
    def __str__(self):
        return f"{self.hostname} ({self.status})"
    
    @property
    def is_available(self):
        """Check if worker can accept more builds"""
        return (
            self.status == self.Status.ONLINE and
            self.current_builds < self.max_concurrent_builds
        )
