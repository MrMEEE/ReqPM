"""
Package models for RPM package management
"""
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from backend.apps.projects.models import Project


class Package(models.Model):
    """
    Represents an RPM package (from requirements or main project)
    """
    class PackageType(models.TextChoices):
        DEPENDENCY = 'dependency', _('Dependency')
        MAIN = 'main', _('Main Project')
        EXTRA = 'extra', _('Extra Package')
    
    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending')
        ANALYZING = 'analyzing', _('Analyzing Dependencies')
        READY = 'ready', _('Ready to Build')
        BUILDING = 'building', _('Building')
        BUILT = 'built', _('Built')
        FAILED = 'failed', _('Failed')
        SKIPPED = 'skipped', _('Skipped')
    
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='packages'
    )
    
    # Package information
    name = models.CharField(max_length=255)
    python_name = models.CharField(
        max_length=255,
        help_text=_('Original Python package name from PyPI')
    )
    version = models.CharField(max_length=100)
    release = models.CharField(max_length=50, default='1')
    
    # Package metadata
    package_type = models.CharField(
        max_length=20,
        choices=PackageType.choices,
        default=PackageType.DEPENDENCY
    )
    summary = models.CharField(max_length=500, blank=True)
    description = models.TextField(blank=True)
    homepage = models.URLField(max_length=500, blank=True)
    license = models.CharField(max_length=100, blank=True)
    
    # Build requirements from requirements.txt
    requirement_spec = models.CharField(
        max_length=255,
        blank=True,
        help_text=_('Original requirement specification, e.g., "package>=1.0,<2.0"')
    )
    requirements_file = models.CharField(
        max_length=500,
        blank=True,
        help_text=_('Requirements file this package was defined in (for direct dependencies)')
    )
    is_direct_dependency = models.BooleanField(
        default=False,
        help_text=_('True if package is directly listed in requirements files, False if indirect dependency')
    )
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    status_message = models.TextField(blank=True)
    
    # Deprecated - keeping for backward compatibility during migration
    build_order = models.IntegerField(
        default=0,
        blank=True,
        null=True,
        help_text=_('DEPRECATED: Build order no longer used, builds happen on-demand')
    )
    
    # Spec file information
    spec_file_content = models.TextField(blank=True)
    spec_file_path = models.CharField(max_length=500, blank=True)
    spec_file_modified = models.BooleanField(default=False)
    
    # Build information (stored directly on package)
    build_status = models.CharField(
        max_length=20,
        choices=[
            ('not_built', 'Not Built'),
            ('waiting_for_deps', 'Waiting for Dependencies'),
            ('pending', 'Pending'),
            ('building', 'Building'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
        ],
        default='not_built',
        help_text=_('Current build status for this package')
    )
    build_started_at = models.DateTimeField(null=True, blank=True)
    build_completed_at = models.DateTimeField(null=True, blank=True)
    build_log = models.TextField(blank=True)
    build_error_message = models.TextField(blank=True)
    analyzed_errors = models.JSONField(default=list, blank=True, help_text=_('Parsed build error analysis'))
    srpm_path = models.CharField(max_length=500, blank=True, null=True)
    rpm_path = models.CharField(max_length=500, blank=True, null=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_built_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'packages'
        unique_together = ['project', 'name', 'version']
        ordering = ['name']
        indexes = [
            models.Index(fields=['project', 'status']),
            models.Index(fields=['status']),
            models.Index(fields=['package_type']),
            models.Index(fields=['project', 'build_status']),
            models.Index(fields=['build_status']),
        ]
    
    def __str__(self):
        return f"{self.name}-{self.version}"
    
    @property
    def enabled_extras(self):
        """Get list of enabled extras for this package"""
        return list(self.extras.filter(enabled=True).values_list('name', flat=True))
    
    @property
    def nvr(self):
        """Get Name-Version-Release string"""
        return f"{self.name}-{self.version}-{self.release}"
    
    @property
    def source_fetched(self):
        """Check if source file has been downloaded"""
        from pathlib import Path
        sources_dir = Path(settings.REQPM['BUILD_DIR']) / 'sources' / self.name
        if not sources_dir.exists():
            return False
        # Check for any archive file in the sources directory
        archive_extensions = ('.tar.gz', '.tar.bz2', '.zip', '.whl', '.tar.xz')
        for f in sources_dir.iterdir():
            if f.is_file() and any(f.name.endswith(ext) for ext in archive_extensions):
                return True
        return False
    
    @property
    def source_path(self):
        """Get the path to the source file"""
        from pathlib import Path
        sources_dir = Path(settings.REQPM['BUILD_DIR']) / 'sources' / self.name
        if sources_dir.exists():
            # Find the actual source file
            archive_extensions = ('.tar.gz', '.tar.bz2', '.zip', '.whl', '.tar.xz')
            for f in sources_dir.iterdir():
                if f.is_file() and any(f.name.endswith(ext) for ext in archive_extensions):
                    return str(f)
        return str(sources_dir / f"{self.name}-{self.version}.tar.gz")


class PackageDependency(models.Model):
    """
    Tracks dependencies between packages
    """
    class DependencyType(models.TextChoices):
        BUILD = 'build', _('Build Dependency')
        RUNTIME = 'runtime', _('Runtime Dependency')
        BOTH = 'both', _('Build and Runtime')
    
    package = models.ForeignKey(
        Package,
        on_delete=models.CASCADE,
        related_name='dependencies'
    )
    depends_on = models.ForeignKey(
        Package,
        on_delete=models.CASCADE,
        related_name='dependents'
    )
    dependency_type = models.CharField(
        max_length=20,
        choices=DependencyType.choices,
        default=DependencyType.BUILD
    )
    
    # Optional version constraints
    version_constraint = models.CharField(
        max_length=255,
        blank=True,
        help_text=_('Version constraint, e.g., ">= 1.0"')
    )
    
    class Meta:
        db_table = 'package_dependencies'
        unique_together = ['package', 'depends_on']
        verbose_name_plural = 'Package dependencies'
    
    def __str__(self):
        return f"{self.package.name} -> {self.depends_on.name}"


class PackageBuild(models.Model):
    """
    Represents a build of a package for a specific RHEL version/arch
    """
    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending')
        SCHEDULED = 'scheduled', _('Scheduled')
        BUILDING = 'building', _('Building')
        COMPLETED = 'completed', _('Completed')
        FAILED = 'failed', _('Failed')
    
    package = models.ForeignKey(
        Package,
        on_delete=models.CASCADE,
        related_name='builds'
    )
    
    # Build target
    rhel_version = models.CharField(max_length=20)
    architecture = models.CharField(max_length=20, default='x86_64')
    
    # Build information
    mock_config = models.CharField(max_length=255)
    build_log = models.TextField(blank=True)
    build_log_path = models.CharField(max_length=500, blank=True)
    
    # Build artifacts
    srpm_path = models.CharField(max_length=500, blank=True)
    rpm_paths = models.JSONField(
        default=list,
        help_text=_('List of paths to built RPM files')
    )
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    error_message = models.TextField(blank=True)
    
    # Build metadata
    build_duration = models.IntegerField(
        null=True,
        blank=True,
        help_text=_('Build duration in seconds')
    )
    builder_host = models.CharField(max_length=255, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'package_builds'
        unique_together = ['package', 'rhel_version', 'architecture']
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['package', 'status']),
            models.Index(fields=['status']),
            models.Index(fields=['rhel_version']),
        ]
    
    def __str__(self):
        return f"{self.package.nvr} (RHEL {self.rhel_version}/{self.architecture})"


class SpecFileRevision(models.Model):
    """
    Tracks revisions of spec files for version control
    """
    package = models.ForeignKey(
        Package,
        on_delete=models.CASCADE,
        related_name='spec_revisions'
    )
    
    content = models.TextField()
    commit_message = models.TextField()
    
    # Git information (if pushed to spec repo)
    git_commit_hash = models.CharField(max_length=40, blank=True)
    git_commit_url = models.URLField(max_length=500, blank=True)
    
    # Author
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='spec_revisions'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'spec_file_revisions'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.package.name} spec revision at {self.created_at}"


class PackageLog(models.Model):
    """
    Stores log messages for package operations
    """
    class Level(models.TextChoices):
        DEBUG = 'debug', _('Debug')
        INFO = 'info', _('Info')
        WARNING = 'warning', _('Warning')
        ERROR = 'error', _('Error')
    
    package = models.ForeignKey(
        Package,
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
        db_table = 'package_logs'
        ordering = ['timestamp']
        indexes = [
            models.Index(fields=['package', 'timestamp']),
            models.Index(fields=['package', 'level']),
        ]


class PackageExtra(models.Model):
    """
    Represents an optional 'extra' feature for a Python package
    (e.g., requests[security], requests[socks])
    """
    package = models.ForeignKey(
        Package,
        on_delete=models.CASCADE,
        related_name='extras'
    )
    name = models.CharField(
        max_length=100,
        help_text=_('Name of the extra feature (e.g., security, socks)')
    )
    enabled = models.BooleanField(
        default=False,
        help_text=_('Whether this extra should be included in the spec file')
    )
    dependencies = models.TextField(
        blank=True,
        help_text=_('Comma-separated list of dependencies for this extra')
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'package_extras'
        unique_together = ['package', 'name']
        ordering = ['name']
        indexes = [
            models.Index(fields=['package', 'enabled']),
        ]
    
    def __str__(self):
        return f"{self.package.name}[{self.name}]"
    
    def __str__(self):
        return f"[{self.level}] {self.package.name}: {self.message[:50]}"

