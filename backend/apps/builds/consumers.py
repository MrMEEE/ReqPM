"""
WebSocket consumers for real-time build updates
"""
import json
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from pathlib import Path


class BuildLogConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for streaming live build logs
    
    URL: /ws/builds/queue/{queue_item_id}/log/
    """
    
    async def connect(self):
        self.queue_item_id = self.scope['url_route']['kwargs']['queue_item_id']
        self.room_group_name = f'build_log_{self.queue_item_id}'
        
        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        
        # Start streaming the log
        await self.stream_log()
    
    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
    
    async def stream_log(self):
        """Stream the build log file in real-time"""
        from django.conf import settings
        
        try:
            queue_item = await self.get_queue_item()
            
            if not queue_item:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': 'Build queue item not found'
                }))
                await self.close()
                return
            
            # Send initial status
            await self.send(text_data=json.dumps({
                'type': 'status',
                'status': queue_item.status,
                'package': queue_item.package.name,
                'rhel_version': queue_item.rhel_version
            }))
            
            # If build hasn't started yet, wait
            if queue_item.status in ['queued', 'pending']:
                await self.send(text_data=json.dumps({
                    'type': 'log',
                    'data': 'Build is queued, waiting to start...\n'
                }))
                
                # Wait for build to start (poll status)
                while queue_item.status in ['queued', 'pending']:
                    await asyncio.sleep(2)
                    queue_item = await self.get_queue_item()
                    if not queue_item:
                        return
                
                await self.send(text_data=json.dumps({
                    'type': 'status',
                    'status': queue_item.status
                }))
            
            # Get log file path from Mock build
            build_dir = Path(settings.REQPM['BUILD_DIR']) / str(queue_item.build_job_id) / queue_item.package.name
            # Mock writes logs to the resultdir (RPMS directory)
            log_file = build_dir / 'RPMS' / 'build.log'
            
            # If there's already a build_log in database, send it first
            if queue_item.build_log:
                await self.send(text_data=json.dumps({
                    'type': 'log',
                    'data': queue_item.build_log
                }))
            
            # Stream the log file if building
            if queue_item.status == 'building':
                last_position = 0
                last_db_log_length = len(queue_item.build_log) if queue_item.build_log else 0
                
                while True:
                    queue_item = await self.get_queue_item()
                    
                    if not queue_item:
                        break
                    
                    # First, check if database log has been updated
                    if queue_item.build_log:
                        current_log_length = len(queue_item.build_log)
                        if current_log_length > last_db_log_length:
                            # Send the new part of the log from database
                            new_content = queue_item.build_log[last_db_log_length:]
                            await self.send(text_data=json.dumps({
                                'type': 'log',
                                'data': new_content
                            }))
                            last_db_log_length = current_log_length
                    
                    # Also check if log file exists and read from it
                    if await self.file_exists(log_file):
                        # Read new content from file
                        content, last_position = await self.read_log_file(log_file, last_position)
                        
                        if content:
                            await self.send(text_data=json.dumps({
                                'type': 'log',
                                'data': content
                            }))
                    
                    # Check if build finished
                    if queue_item.status in ['completed', 'failed', 'cancelled']:
                        # Send final status
                        await self.send(text_data=json.dumps({
                            'type': 'status',
                            'status': queue_item.status,
                            'completed': True
                        }))
                        
                        # Send any error analysis if available
                        if queue_item.analyzed_errors:
                            await self.send(text_data=json.dumps({
                                'type': 'errors',
                                'errors': queue_item.analyzed_errors
                            }))
                        
                        # Send final log if available
                        if queue_item.build_log and not await self.file_exists(log_file):
                            await self.send(text_data=json.dumps({
                                'type': 'log',
                                'data': queue_item.build_log,
                                'final': True
                            }))
                        
                        break
                    
                    # Wait before next check
                    await asyncio.sleep(1)
            
            # Build already finished
            elif queue_item.status in ['completed', 'failed', 'cancelled']:
                await self.send(text_data=json.dumps({
                    'type': 'status',
                    'status': queue_item.status,
                    'completed': True
                }))
                
                if queue_item.analyzed_errors:
                    await self.send(text_data=json.dumps({
                        'type': 'errors',
                        'errors': queue_item.analyzed_errors
                    }))
        
        except Exception as e:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': str(e)
            }))
    
    @database_sync_to_async
    def get_queue_item(self):
        """Get queue item from database"""
        from backend.apps.builds.models import BuildQueue
        
        try:
            return BuildQueue.objects.select_related('package', 'build_job').get(id=self.queue_item_id)
        except BuildQueue.DoesNotExist:
            return None
    
    @database_sync_to_async
    def file_exists(self, path):
        """Check if file exists"""
        return Path(path).exists()
    
    @database_sync_to_async
    def read_log_file(self, path, last_position):
        """Read log file from last position"""
        try:
            with open(path, 'r') as f:
                f.seek(last_position)
                content = f.read()
                new_position = f.tell()
                return content, new_position
        except FileNotFoundError:
            return '', last_position
        except Exception:
            return '', last_position
    
    # Receive message from room group
    async def build_update(self, event):
        """Receive build update from group"""
        await self.send(text_data=json.dumps(event['data']))


class BuildJobConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time build job updates
    
    URL: /ws/builds/{build_job_id}/
    """
    
    async def connect(self):
        self.build_job_id = self.scope['url_route']['kwargs']['build_job_id']
        self.room_group_name = f'build_job_{self.build_job_id}'
        
        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        
        # Send initial build job data
        build_data = await self.get_build_job_data()
        if build_data:
            await self.send(text_data=json.dumps({
                'type': 'build_update',
                'data': build_data
            }))
    
    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
    
    # Receive message from room group
    async def build_update(self, event):
        """Send build update to WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'build_update',
            'data': event['data']
        }))
    
    async def queue_update(self, event):
        """Send queue item update to WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'queue_update',
            'data': event['data']
        }))
    
    @database_sync_to_async
    def get_build_job_data(self):
        """Get BuildJob data with queue items"""
        from backend.apps.builds.models import BuildJob
        from backend.apps.builds.serializers import BuildJobDetailSerializer
        
        try:
            build_job = BuildJob.objects.get(id=self.build_job_id)
            serializer = BuildJobDetailSerializer(build_job)
            return serializer.data
        except BuildJob.DoesNotExist:
            return None
