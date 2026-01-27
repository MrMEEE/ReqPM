"""
System settings model
"""
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.cache import cache


class SystemSettings(models.Model):
    """
    System-wide settings for ReqPM
    
    Singleton model - only one instance should exist
    """
    
    # Build settings
    max_concurrent_builds = models.IntegerField(
        default=4,
        validators=[MinValueValidator(1), MaxValueValidator(20)],
        help_text="Maximum number of simultaneous builds (1-20)"
    )
    
    # Cleanup settings
    cleanup_builds_after_days = models.IntegerField(
        default=30,
        validators=[MinValueValidator(1), MaxValueValidator(365)],
        help_text="Remove build artifacts older than N days"
    )
    
    cleanup_repos_after_days = models.IntegerField(
        default=7,
        validators=[MinValueValidator(1), MaxValueValidator(90)],
        help_text="Remove old git repository clones after N days"
    )
    
    # Sync settings
    auto_sync_projects = models.BooleanField(
        default=True,
        help_text="Automatically sync projects from git repositories"
    )
    
    sync_interval_hours = models.IntegerField(
        default=6,
        validators=[MinValueValidator(1), MaxValueValidator(24)],
        help_text="Hours between automatic project syncs"
    )
    
    # Repository settings
    repository_sync_interval_minutes = models.IntegerField(
        default=30,
        validators=[MinValueValidator(5), MaxValueValidator(1440)],
        help_text="Minutes between repository metadata syncs"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "System Settings"
        verbose_name_plural = "System Settings"
    
    def __str__(self):
        return "System Settings"
    
    def save(self, *args, **kwargs):
        """Ensure singleton pattern"""
        self.pk = 1
        super().save(*args, **kwargs)
        # Clear cache when settings change
        cache.delete('system_settings')
    
    def delete(self, *args, **kwargs):
        """Prevent deletion"""
        pass
    
    @classmethod
    def load(cls):
        """Load settings (singleton)"""
        settings = cache.get('system_settings')
        if settings is None:
            settings, created = cls.objects.get_or_create(pk=1)
            cache.set('system_settings', settings, timeout=300)  # Cache for 5 minutes
        return settings
