"""
WebSocket consumers for real-time Celery task log streaming
"""
import json
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async


class TaskLogConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for streaming live Celery task logs/results
    
    URL: /ws/tasks/{task_id}/log/
    
    Streams task status, result, and traceback in real-time by polling
    the django_celery_results TaskResult model.
    """
    
    async def connect(self):
        self.task_id = self.scope['url_route']['kwargs']['task_id']
        self.room_group_name = f'task_log_{self.task_id}'
        
        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        
        # Start streaming the task log
        await self.stream_log()
    
    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
    
    async def stream_log(self):
        """Stream the task result/log in real-time"""
        try:
            task_result = await self.get_task_result()
            
            if not task_result:
                # Task may not have a result yet - wait for it
                await self.send(text_data=json.dumps({
                    'type': 'status',
                    'status': 'PENDING',
                    'task_name': None,
                    'task_id': self.task_id,
                }))
                
                await self.send(text_data=json.dumps({
                    'type': 'log',
                    'data': 'Task is pending, waiting for execution...\n'
                }))
                
                # Poll until the task result appears
                max_wait = 300  # Wait up to 5 minutes
                waited = 0
                while not task_result and waited < max_wait:
                    await asyncio.sleep(2)
                    waited += 2
                    task_result = await self.get_task_result()
                
                if not task_result:
                    await self.send(text_data=json.dumps({
                        'type': 'error',
                        'message': 'Task result not found after waiting'
                    }))
                    await self.close()
                    return
            
            # Send initial status
            task_data = await self.serialize_task(task_result)
            await self.send(text_data=json.dumps({
                'type': 'status',
                'status': task_data['status'],
                'task_name': task_data['task_name'],
                'task_id': task_data['task_id'],
                'date_created': task_data['date_created'],
                'date_done': task_data['date_done'],
            }))
            
            # Send any existing result/traceback
            if task_data['result']:
                await self.send(text_data=json.dumps({
                    'type': 'result',
                    'data': task_data['result'],
                }))
            
            if task_data['traceback']:
                await self.send(text_data=json.dumps({
                    'type': 'traceback',
                    'data': task_data['traceback'],
                }))
            
            # If already completed, send completion and close
            if task_data['status'] in ['SUCCESS', 'FAILURE', 'REVOKED']:
                await self.send(text_data=json.dumps({
                    'type': 'status',
                    'status': task_data['status'],
                    'completed': True,
                    'date_done': task_data['date_done'],
                    'duration': task_data['duration'],
                }))
                return
            
            # Poll for updates while task is running
            last_result = task_data.get('result', '')
            last_traceback = task_data.get('traceback', '')
            last_status = task_data['status']
            
            while True:
                await asyncio.sleep(1)
                task_result = await self.get_task_result()
                
                if not task_result:
                    break
                
                task_data = await self.serialize_task(task_result)
                
                # Send status update if changed
                if task_data['status'] != last_status:
                    last_status = task_data['status']
                    await self.send(text_data=json.dumps({
                        'type': 'status',
                        'status': task_data['status'],
                        'date_done': task_data['date_done'],
                    }))
                
                # Send result update if changed
                current_result = task_data.get('result', '') or ''
                if current_result != (last_result or ''):
                    await self.send(text_data=json.dumps({
                        'type': 'result',
                        'data': current_result,
                    }))
                    last_result = current_result
                
                # Send traceback update if changed
                current_traceback = task_data.get('traceback', '') or ''
                if current_traceback != (last_traceback or ''):
                    await self.send(text_data=json.dumps({
                        'type': 'traceback',
                        'data': current_traceback,
                    }))
                    last_traceback = current_traceback
                
                # Check if task is complete
                if task_data['status'] in ['SUCCESS', 'FAILURE', 'REVOKED']:
                    await self.send(text_data=json.dumps({
                        'type': 'status',
                        'status': task_data['status'],
                        'completed': True,
                        'date_done': task_data['date_done'],
                        'duration': task_data['duration'],
                    }))
                    break
                    
        except Exception as e:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Stream error: {str(e)}'
            }))
    
    @database_sync_to_async
    def get_task_result(self):
        """Get task result from database by Celery task_id"""
        from django_celery_results.models import TaskResult
        try:
            return TaskResult.objects.get(task_id=self.task_id)
        except TaskResult.DoesNotExist:
            return None
    
    @database_sync_to_async
    def serialize_task(self, task_result):
        """Serialize task result to dict"""
        duration = None
        if task_result.date_done and task_result.date_created:
            delta = task_result.date_done - task_result.date_created
            duration = round(delta.total_seconds(), 2)
        
        return {
            'id': task_result.id,
            'task_id': task_result.task_id,
            'task_name': task_result.task_name,
            'task_args': task_result.task_args,
            'task_kwargs': task_result.task_kwargs,
            'status': task_result.status,
            'result': task_result.result,
            'traceback': task_result.traceback,
            'date_created': task_result.date_created.isoformat() if task_result.date_created else None,
            'date_done': task_result.date_done.isoformat() if task_result.date_done else None,
            'duration': duration,
        }
    
    async def task_update(self, event):
        """
        Handler for task update messages from channel layer
        """
        await self.send(text_data=json.dumps({
            'type': event['update_type'],
            'data': event.get('data', ''),
            'status': event.get('status'),
        }))
