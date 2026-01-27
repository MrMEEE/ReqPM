"""
Builds app configuration
"""
from django.apps import AppConfig


class BuildsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'backend.apps.builds'
    verbose_name = 'Builds'
