"""
User models for ReqPM
"""
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    """
    Custom user model with LDAP support preparation
    """
    class AuthBackend(models.TextChoices):
        LOCAL = 'local', _('Local')
        LDAP = 'ldap', _('LDAP')
    
    email = models.EmailField(_('email address'), unique=True)
    auth_backend = models.CharField(
        max_length=10,
        choices=AuthBackend.choices,
        default=AuthBackend.LOCAL,
        help_text=_('Authentication backend used for this user')
    )
    ldap_dn = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text=_('LDAP Distinguished Name')
    )
    api_key = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        unique=True,
        help_text=_('API key for programmatic access')
    )
    
    # Audit fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'users'
        ordering = ['username']
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['auth_backend']),
            models.Index(fields=['api_key']),
        ]
    
    def __str__(self):
        return self.username
    
    @property
    def full_name(self):
        """Get user's full name"""
        return self.get_full_name() or self.username
    
    def generate_api_key(self):
        """Generate a new API key for the user"""
        import secrets
        self.api_key = secrets.token_urlsafe(48)
        self.save(update_fields=['api_key'])
        return self.api_key
    
    def revoke_api_key(self):
        """Revoke the user's API key"""
        self.api_key = None
        self.save(update_fields=['api_key'])


class UserProfile(models.Model):
    """
    Extended user profile for additional settings
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='profile'
    )
    
    # Notification preferences
    email_on_build_complete = models.BooleanField(default=True)
    email_on_build_failure = models.BooleanField(default=True)
    email_on_project_activity = models.BooleanField(default=False)
    
    # UI preferences
    theme = models.CharField(
        max_length=20,
        choices=[('light', 'Light'), ('dark', 'Dark'), ('auto', 'Auto')],
        default='auto'
    )
    items_per_page = models.IntegerField(default=50)
    
    # Timezone
    timezone = models.CharField(max_length=50, default='UTC')
    
    class Meta:
        db_table = 'user_profiles'
    
    def __str__(self):
        return f"{self.user.username}'s profile"
