"""
Packages app configuration
"""
from django.apps import AppConfig


class PackagesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'backend.apps.packages'
    verbose_name = 'Packages'
