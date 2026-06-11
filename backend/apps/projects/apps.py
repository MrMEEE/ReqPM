"""
Projects app configuration
"""
from django.apps import AppConfig


class ProjectsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'backend.apps.projects'

    def ready(self):
        from django.db.models.signals import post_save
        from django.dispatch import receiver
        from backend.apps.projects.models import Project

        @receiver(post_save, sender=Project, dispatch_uid='projects.ws_update')
        def _on_project_saved(sender, instance, **kwargs):
            """Push project status to WebSocket clients whenever the project is saved."""
            try:
                from channels.layers import get_channel_layer
                from asgiref.sync import async_to_sync
                channel_layer = get_channel_layer()
                if channel_layer is None:
                    return
                async_to_sync(channel_layer.group_send)(
                    f'project_{instance.id}',
                    {
                        'type': 'project_update',
                        'status': instance.status,
                        'status_message': instance.status_message or '',
                    }
                )
            except Exception:
                pass
    verbose_name = 'Projects'
