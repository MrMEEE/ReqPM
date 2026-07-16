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

    mock_memory_limit = models.CharField(
        max_length=20,
        blank=True,
        default='',
        help_text="Per-build memory cap enforced via cgroup (e.g. 8G, 4096M). Leave empty to disable."
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
    
    # AI fixer settings
    AI_BACKEND_CHOICES = [
        ('builtin', 'Built-in (llama.cpp, no external services)'),
        ('ollama', 'Ollama'),
        ('openai', 'OpenAI-compatible API'),
    ]
    
    ai_fixer_enabled = models.BooleanField(
        default=False,
        help_text="Use an LLM as fallback when rule-based build fixers fail"
    )
    
    ai_fixer_backend = models.CharField(
        max_length=20,
        choices=AI_BACKEND_CHOICES,
        default='builtin',
        help_text="LLM backend to use"
    )
    
    ai_fixer_model = models.CharField(
        max_length=200,
        default='qwen2.5-coder-3b',
        help_text="Model key (builtin) or model name (ollama/openai)"
    )
    
    ai_fixer_base_url = models.CharField(
        max_length=500,
        default='http://localhost:11434',
        blank=True,
        help_text="Base URL for ollama/openai backends"
    )
    
    ai_fixer_api_key = models.CharField(
        max_length=500,
        blank=True,
        default='',
        help_text="API key for OpenAI-compatible backends"
    )
    
    ai_fixer_timeout = models.IntegerField(
        default=300,
        validators=[MinValueValidator(30), MaxValueValidator(1800)],
        help_text="LLM request timeout in seconds"
    )

    ai_fixer_max_attempts = models.IntegerField(
        default=3,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="Maximum number of AI fix attempts per package before giving up"
    )

    ai_fixer_max_concurrent = models.IntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="Maximum number of packages the AI fixer may work on simultaneously"
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
