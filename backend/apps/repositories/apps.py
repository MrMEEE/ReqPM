"""
Repositories app configuration
"""
from django.apps import AppConfig


class RepositoriesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'backend.apps.repositories'
    verbose_name = 'Repositories'
