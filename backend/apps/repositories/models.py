"""
Repository models for managing RPM repositories
"""
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from backend.apps.projects.models import Project


class Repository(models.Model):
    """
    Represents a YUM/DNF repository
    """
    class Status(models.TextChoices):
        CREATING = 'creating', _('Creating')
        ACTIVE = 'active', _('Active')
        UPDATING = 'updating', _('Updating')
        ERROR = 'error', _('Error')
        ARCHIVED = 'archived', _('Archived')
    
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='repositories'
    )
    
    # Repository information
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    
    # Target platform
    rhel_version = models.CharField(max_length=20)
    architecture = models.CharField(max_length=20, default='x86_64')
    
    # Repository path and URL
    repo_path = models.CharField(max_length=500)
    repo_url = models.URLField(max_length=500, blank=True)
    
    # Repository metadata
    baseurl = models.URLField(max_length=500, blank=True)
    gpgcheck = models.BooleanField(default=True)
    gpgkey_url = models.URLField(max_length=500, blank=True)
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CREATING
    )
    status_message = models.TextField(blank=True)
    
    # Statistics
    package_count = models.IntegerField(default=0)
    last_updated = models.DateTimeField(null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'repositories'
        unique_together = ['project', 'name', 'rhel_version', 'architecture']
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['project', 'status']),
            models.Index(fields=['status']),
            models.Index(fields=['rhel_version']),
        ]
    
    def __str__(self):
        return f"{self.project.name} - {self.name} (RHEL {self.rhel_version})"
    
    @property
    def repo_file_content(self):
        """Generate .repo file content for YUM/DNF"""
        return f"""[{self.name}]
name={self.description or self.name}
baseurl={self.baseurl}
enabled=1
gpgcheck={1 if self.gpgcheck else 0}
{"gpgkey=" + self.gpgkey_url if self.gpgkey_url else ""}
"""


class RepositoryPackage(models.Model):
    """
    Tracks packages in a repository
    """
    repository = models.ForeignKey(
        Repository,
        on_delete=models.CASCADE,
        related_name='packages'
    )
    
    # Package information
    name = models.CharField(max_length=255)
    version = models.CharField(max_length=100)
    release = models.CharField(max_length=50)
    arch = models.CharField(max_length=20)
    
    # File information
    file_path = models.CharField(max_length=500)
    file_size = models.BigIntegerField()
    checksum = models.CharField(max_length=128)
    checksum_type = models.CharField(max_length=20, default='sha256')
    
    # Timestamps
    added_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'repository_packages'
        unique_together = ['repository', 'name', 'version', 'release', 'arch']
        ordering = ['name', '-version']
        indexes = [
            models.Index(fields=['repository', 'name']),
            models.Index(fields=['name']),
        ]
    
    def __str__(self):
        return f"{self.name}-{self.version}-{self.release}.{self.arch}"


class RepositoryMetadata(models.Model):
    """
    Stores repository metadata (repomd.xml, primary.xml, etc.)
    """
    class MetadataType(models.TextChoices):
        REPOMD = 'repomd', _('Repository Metadata')
        PRIMARY = 'primary', _('Primary')
        FILELISTS = 'filelists', _('File Lists')
        OTHER = 'other', _('Other')
    
    repository = models.ForeignKey(
        Repository,
        on_delete=models.CASCADE,
        related_name='metadata'
    )
    
    metadata_type = models.CharField(
        max_length=20,
        choices=MetadataType.choices
    )
    
    # File information
    file_path = models.CharField(max_length=500)
    checksum = models.CharField(max_length=128)
    
    # Timestamps
    generated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'repository_metadata'
        unique_together = ['repository', 'metadata_type']
        verbose_name_plural = 'Repository metadata'
    
    def __str__(self):
        return f"{self.repository.name} - {self.metadata_type}"


class RepositoryAccess(models.Model):
    """
    Manages access control for repositories (for future use)
    """
    class AccessLevel(models.TextChoices):
        PUBLIC = 'public', _('Public')
        PRIVATE = 'private', _('Private')
        AUTHENTICATED = 'authenticated', _('Authenticated Users Only')
    
    repository = models.OneToOneField(
        Repository,
        on_delete=models.CASCADE,
        related_name='access_control'
    )
    
    access_level = models.CharField(
        max_length=20,
        choices=AccessLevel.choices,
        default=AccessLevel.PUBLIC
    )
    
    # Allowed users (for private repos)
    allowed_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='accessible_repositories'
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'repository_access'
        verbose_name_plural = 'Repository access controls'
    
    def __str__(self):
        return f"{self.repository.name} - {self.access_level}"
