"""
WebSocket consumers for real-time package build updates
"""
import json
import asyncio
import logging
from pathlib import Path
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

logger = logging.getLogger(__name__)


class PackageBuildLogConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for streaming live package build logs
    
    URL: /ws/packages/{package_id}/build-log/
    
    Streams logs from three sources depending on build state:
    1. Completed/failed builds: sends the stored build_log from DB
    2. Active builds: tails the mock build.log file on disk in real-time
    3. Pending builds: waits for the build to start, then switches to (2)
    """
    
    async def connect(self):
        self.package_id = self.scope['url_route']['kwargs']['package_id']
        self.room_group_name = f'package_build_{self.package_id}'
        self._streaming = True
        
        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        
        # Start streaming the log
        await self.stream_log()
    
    async def disconnect(self, close_code):
        self._streaming = False
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
    
    @database_sync_to_async
    def get_package(self):
        """Get package from database"""
        from backend.apps.packages.models import Package
        try:
            return Package.objects.get(id=self.package_id)
        except Package.DoesNotExist:
            return None

    @database_sync_to_async
    def get_package_snapshot(self):
        """Get a dict snapshot of package fields (avoids lazy DB access outside sync context)"""
        from backend.apps.packages.models import Package
        try:
            pkg = Package.objects.get(id=self.package_id)
            return {
                'id': pkg.id,
                'name': pkg.name,
                'build_status': pkg.build_status,
                'build_log': pkg.build_log or '',
                'build_error_message': pkg.build_error_message or '',
                'analyzed_errors': pkg.analyzed_errors or [],
                'build_started_at': pkg.build_started_at.isoformat() if pkg.build_started_at else None,
                'build_completed_at': pkg.build_completed_at.isoformat() if pkg.build_completed_at else None,
                'srpm_path': pkg.srpm_path or '',
                'rpm_path': pkg.rpm_path or '',
            }
        except Package.DoesNotExist:
            return None

    @database_sync_to_async
    def get_build_dir(self):
        """Get the build artifacts directory for this package"""
        from django.conf import settings
        build_dir = Path(settings.REQPM['BUILD_DIR']) / 'package_builds' / str(self.package_id)
        return str(build_dir)

    def _find_log_files(self, build_dir):
        """Find mock log files in the build directory (RPMS/build.log, RPMS/root.log)"""
        bd = Path(build_dir)
        log_files = []
        for sub in ['RPMS', 'SRPMS', '']:
            d = bd / sub if sub else bd
            for name in ['build.log', 'root.log']:
                f = d / name
                if f.exists():
                    log_files.append(f)
        return log_files

    async def stream_log(self):
        """Stream the build log in real-time"""
        try:
            pkg = await self.get_package_snapshot()
            
            if not pkg:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': 'Package not found'
                }))
                await self.close()
                return
            
            # Send initial status
            await self.send(text_data=json.dumps({
                'type': 'status',
                'status': pkg['build_status'],
                'package': pkg['name'],
                'build_started_at': pkg['build_started_at'],
                'build_completed_at': pkg['build_completed_at'],
            }))
            
            # ----- CASE 1: Build already completed/failed → send stored log -----
            if pkg['build_status'] in ('completed', 'failed'):
                await self._send_completed_log(pkg)
                return
            
            # ----- CASE 2: Not built yet / pending → wait for build to start -----
            if pkg['build_status'] in ('not_built', 'pending'):
                await self.send(text_data=json.dumps({
                    'type': 'log',
                    'data': 'Build is queued, waiting to start...\n'
                }))
                
                while self._streaming and pkg['build_status'] in ('not_built', 'pending'):
                    await asyncio.sleep(2)
                    pkg = await self.get_package_snapshot()
                    if not pkg:
                        return
                
                if not self._streaming:
                    return
                
                await self.send(text_data=json.dumps({
                    'type': 'status',
                    'status': pkg['build_status']
                }))
                
                # If it went straight to completed/failed while we waited
                if pkg['build_status'] in ('completed', 'failed'):
                    await self._send_completed_log(pkg)
                    return
            
            # ----- CASE 3: Building → tail log files from disk -----
            await self._stream_live_build(pkg)
                
        except Exception as e:
            logger.exception(f"Stream error for package {self.package_id}")
            try:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': f'Stream error: {str(e)}'
                }))
            except Exception:
                pass

    async def _send_completed_log(self, pkg):
        """Send the full stored build log for a completed/failed build"""
        if pkg['build_log']:
            # Send in chunks to avoid overwhelming the WebSocket
            log = pkg['build_log']
            chunk_size = 64 * 1024  # 64KB chunks
            for i in range(0, len(log), chunk_size):
                await self.send(text_data=json.dumps({
                    'type': 'log',
                    'data': log[i:i + chunk_size]
                }))
        
        if pkg['build_error_message']:
            await self.send(text_data=json.dumps({
                'type': 'error_message',
                'message': pkg['build_error_message']
            }))
        
        if pkg['analyzed_errors']:
            await self.send(text_data=json.dumps({
                'type': 'analyzed_errors',
                'errors': pkg['analyzed_errors']
            }))
        
        await self.send(text_data=json.dumps({
            'type': 'status',
            'status': pkg['build_status'],
            'completed': True,
            'build_completed_at': pkg['build_completed_at'],
            'srpm_path': pkg['srpm_path'],
            'rpm_path': pkg['rpm_path'],
        }))

    async def _stream_live_build(self, pkg):
        """
        Tail log files from disk while the build is running.
        
        Mock writes build.log and root.log to the RPMS result directory.
        We poll those files and stream new content as it appears.
        """
        build_dir = await self.get_build_dir()
        
        # Track file positions for each log file we find
        file_positions = {}  # path → last read position
        sent_any = False
        
        while self._streaming:
            # Check for new/existing log files
            log_files = await asyncio.to_thread(self._find_log_files, build_dir)
            
            for log_file in log_files:
                fpath = str(log_file)
                last_pos = file_positions.get(fpath, 0)
                
                try:
                    file_size = log_file.stat().st_size
                    if file_size > last_pos:
                        with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                            f.seek(last_pos)
                            new_content = f.read()
                        
                        if new_content:
                            # Add a header when we first encounter a file
                            if last_pos == 0 and len(log_files) > 1:
                                header = f"\n=== {log_file.name} ===\n"
                                new_content = header + new_content
                            
                            await self.send(text_data=json.dumps({
                                'type': 'log',
                                'data': new_content
                            }))
                            sent_any = True
                        
                        file_positions[fpath] = file_size
                except (OSError, IOError) as e:
                    logger.debug(f"Could not read {fpath}: {e}")
            
            # Check if build has finished
            pkg = await self.get_package_snapshot()
            if not pkg:
                break
            
            if pkg['build_status'] in ('completed', 'failed'):
                # One final read of any remaining log content on disk
                for log_file in await asyncio.to_thread(self._find_log_files, build_dir):
                    fpath = str(log_file)
                    last_pos = file_positions.get(fpath, 0)
                    try:
                        with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                            f.seek(last_pos)
                            remaining = f.read()
                        if remaining:
                            await self.send(text_data=json.dumps({
                                'type': 'log',
                                'data': remaining
                            }))
                    except (OSError, IOError):
                        pass
                
                # If we never found log files on disk, fall back to DB log
                if not sent_any and pkg['build_log']:
                    await self.send(text_data=json.dumps({
                        'type': 'log',
                        'data': pkg['build_log']
                    }))
                
                if pkg['build_error_message']:
                    await self.send(text_data=json.dumps({
                        'type': 'error_message',
                        'message': pkg['build_error_message']
                    }))
                
                if pkg['analyzed_errors']:
                    await self.send(text_data=json.dumps({
                        'type': 'analyzed_errors',
                        'errors': pkg['analyzed_errors']
                    }))
                
                await self.send(text_data=json.dumps({
                    'type': 'status',
                    'status': pkg['build_status'],
                    'completed': True,
                    'build_completed_at': pkg['build_completed_at'],
                    'srpm_path': pkg['srpm_path'],
                    'rpm_path': pkg['rpm_path'],
                }))
                break
            
            # Poll interval
            await asyncio.sleep(1)
    
    async def build_update(self, event):
        """
        Handler for build update messages from channel layer
        """
        await self.send(text_data=json.dumps({
            'type': event['update_type'],
            'data': event.get('data', ''),
            'status': event.get('status'),
        }))
