"""
WebSocket consumers for project real-time updates
"""
import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

logger = logging.getLogger(__name__)


class ProjectConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for project updates
    Sends real-time updates about packages in a project
    """
    
    async def connect(self):
        self.project_id = self.scope['url_route']['kwargs']['project_id']
        self.room_group_name = f'project_{self.project_id}'
        
        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        
        logger.info(f"WebSocket connected for project {self.project_id}")
        
        # Send initial data
        initial_data = await self.get_project_data()
        await self.send(text_data=json.dumps({
            'type': 'initial_data',
            **initial_data
        }))
    
    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
        
        logger.info(f"WebSocket disconnected for project {self.project_id}")
    
    async def receive(self, text_data):
        """Handle messages from WebSocket"""
        try:
            data = json.loads(text_data)
            action = data.get('action')
            
            if action == 'refresh':
                # Send current project data
                project_data = await self.get_project_data()
                await self.send(text_data=json.dumps({
                    'type': 'refresh',
                    **project_data
                }))
        except Exception as e:
            logger.error(f"Error handling WebSocket message: {e}")
    
    async def project_update(self, event):
        """
        Handle project_update messages from channel layer
        """
        await self.send(text_data=json.dumps({
            'type': 'update',
            **event
        }))
    
    async def package_update(self, event):
        """
        Handle package_update messages from channel layer
        """
        await self.send(text_data=json.dumps({
            'type': 'package_update',
            **event
        }))
    
    @database_sync_to_async
    def get_project_data(self):
        """Get current project and packages data"""
        from backend.apps.projects.models import Project
        from backend.apps.packages.models import Package
        
        try:
            project = Project.objects.get(id=self.project_id)
            packages = Package.objects.filter(project=project).select_related('project').prefetch_related('dependents')
            
            packages_data = []
            for pkg in packages:
                dependents = list(pkg.dependents.select_related('package').values_list('package__name', flat=True))
                packages_data.append({
                    'id': pkg.id,
                    'name': pkg.name,
                    'version': pkg.version,
                    'status': pkg.status,
                    'status_message': pkg.status_message,
                    'package_type': pkg.package_type,
                    'build_order': pkg.build_order,
                    'has_spec': pkg.spec_revisions.exists(),
                    'requirements_file': pkg.requirements_file,
                    'is_direct_dependency': pkg.is_direct_dependency,
                    'dependent_packages': dependents,
                })
            
            return {
                'project': {
                    'id': project.id,
                    'name': project.name,
                    'status': project.status,
                    'status_message': project.status_message,
                },
                'packages': packages_data
            }
        except Exception as e:
            logger.error(f"Error getting project data: {e}")
            return {'project': None, 'packages': []}
