"""
Project models for managing Python projects
"""
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
import json


class Project(models.Model):
    """
    Represents a Python project to be built as RPM
    """
    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending')
        CLONING = 'cloning', _('Cloning')
        ANALYZING = 'analyzing', _('Analyzing Dependencies')
        READY = 'ready', _('Ready')
        BUILDING = 'building', _('Building')
        COMPLETED = 'completed', _('Completed')
        FAILED = 'failed', _('Failed')
    
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    
    # Git repository information
    git_url = models.URLField(max_length=500)
    git_branch = models.CharField(max_length=100, default='main')
    git_tag = models.CharField(max_length=100, blank=True)
    git_commit = models.CharField(max_length=40, blank=True)
    
    # Authentication for private repos (optional)
    git_ssh_key = models.TextField(blank=True, help_text=_('SSH private key for repository access'))
    git_api_token = models.CharField(max_length=255, blank=True, help_text=_('API token for repository access'))
    
    # Build configuration
    requirements_files = models.JSONField(
        default=list,
        help_text=_('List of requirements file paths in repo, e.g., ["requirements.txt", "requirements/base.txt"]')
    )
    build_version = models.CharField(max_length=50)
    python_version = models.CharField(
        max_length=10,
        default='default',
        help_text=_('Python version to use for spec generation (e.g., "3.11", "3.12", or "default")')
    )
    rhel_versions = models.JSONField(
        default=list,
        help_text=_('List of RHEL versions to build for, e.g., ["8", "9"]')
    )
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    status_message = models.TextField(blank=True)
    
    # Ownership and permissions
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='projects'
    )
    
    # Spec file repository (optional)
    spec_repo_url = models.URLField(
        max_length=500,
        blank=True,
        help_text=_('Git repository for storing spec file changes')
    )
    spec_repo_ssh_key = models.TextField(blank=True)
    spec_repo_api_token = models.CharField(max_length=255, blank=True)
    
    # Build options
    parallel_builds = models.IntegerField(
        default=1,
        help_text=_('Number of packages to build in parallel')
    )
    build_repositories = models.TextField(
        blank=True,
        help_text=_('Additional YUM/DNF repositories to use during build (one per line)')
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_build_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'projects'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['owner', 'status']),
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
        ]
        permissions = [
            ('can_trigger_build', 'Can trigger project builds'),
            ('can_edit_specs', 'Can edit spec files'),
        ]
    
    def __str__(self):
        return self.name
    
    @property
    def git_ref(self):
        """Get the git reference to checkout (tag, branch, or commit)"""
        return self.git_tag or self.git_branch or 'main'


class ProjectBranch(models.Model):
    """
    Stores information about branches/tags available in a project
    """
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='branches'
    )
    name = models.CharField(max_length=255)
    commit_hash = models.CharField(max_length=40)
    is_tag = models.BooleanField(default=False)
    
    # Metadata
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'project_branches'
        unique_together = ['project', 'name']
        ordering = ['-is_tag', 'name']
    
    def __str__(self):
        return f"{self.project.name}:{self.name}"


class ProjectBuildConfig(models.Model):
    """
    Build configuration for a specific project version
    """
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='build_configs'
    )
    version = models.CharField(max_length=50)
    git_ref = models.CharField(max_length=255)
    
    # Build settings (reusable)
    rhel_versions = models.JSONField(default=list)
    build_options = models.JSONField(
        default=dict,
        help_text=_('Additional build options as JSON')
    )
    
    # Status
    is_active = models.BooleanField(default=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True
    )
    
    class Meta:
        db_table = 'project_build_configs'
        unique_together = ['project', 'version']
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.project.name} v{self.version}"


class ProjectCollaborator(models.Model):
    """
    Collaborators on a project with specific roles
    """
    class Role(models.TextChoices):
        VIEWER = 'viewer', _('Viewer')
        BUILDER = 'builder', _('Builder')
        MAINTAINER = 'maintainer', _('Maintainer')
        ADMIN = 'admin', _('Admin')
    
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='collaborators'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='collaborations'
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.VIEWER
    )
    
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='added_collaborators'
    )
    
    class Meta:
        db_table = 'project_collaborators'
        unique_together = ['project', 'user']
    
    def __str__(self):
        return f"{self.user.username} - {self.project.name} ({self.role})"


class ProjectLog(models.Model):
    """
    Stores log messages for project operations
    """
    class Level(models.TextChoices):
        DEBUG = 'debug', _('Debug')
        INFO = 'info', _('Info')
        WARNING = 'warning', _('Warning')
        ERROR = 'error', _('Error')
    
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='logs'
    )
    level = models.CharField(
        max_length=10,
        choices=Level.choices,
        default=Level.INFO
    )
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'project_logs'
        ordering = ['timestamp']
        indexes = [
            models.Index(fields=['project', 'timestamp']),
            models.Index(fields=['project', 'level']),
        ]
    
    def __str__(self):
        return f"[{self.level}] {self.project.name}: {self.message[:50]}"
