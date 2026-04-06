"""
Serializers for Celery task results
"""
from rest_framework import serializers
from django_celery_results.models import TaskResult
import json
import re
import ast


class TaskResultSerializer(serializers.ModelSerializer):
    """Serializer for Celery task results"""
    
    duration = serializers.SerializerMethodField()
    task_context = serializers.SerializerMethodField()
    related_package = serializers.SerializerMethodField()
    
    class Meta:
        model = TaskResult
        fields = [
            'id', 'task_id', 'task_name', 'task_args', 'task_kwargs',
            'status', 'result', 'traceback',
            'date_created', 'date_done', 'duration',
            'task_context', 'related_package'
        ]
        read_only_fields = ['id', 'task_id', 'task_name', 'task_args', 'task_kwargs',
                           'status', 'result', 'traceback',
                           'date_created', 'date_done', 'duration',
                           'task_context', 'related_package']
    
    def get_duration(self, obj):
        """Calculate task duration in seconds"""
        if obj.date_done and obj.date_created:
            delta = obj.date_done - obj.date_created
            return round(delta.total_seconds(), 2)
        return None
    
    def get_task_context(self, obj):
        """
        Extract context information about what the task is working on.
        
        Returns dict with:
        - type: 'package', 'build', 'project', 'repository', etc.
        - description: Human-readable description
        - id: Related object ID if available
        """
        task_name = obj.task_name or ''
        
        # Parse task arguments to extract IDs and context
        args = []
        kwargs = {}
        
        try:
            if obj.task_args and obj.task_args != '[]':
                # First, try to parse as JSON
                try:
                    parsed = json.loads(obj.task_args)
                    # If the result is a list, use it directly
                    if isinstance(parsed, list):
                        args = parsed
                    # If the result is a string (e.g., '"(123,)"'), try to parse as Python tuple
                    elif isinstance(parsed, str):
                        try:
                            tuple_result = ast.literal_eval(parsed)
                            args = list(tuple_result) if isinstance(tuple_result, tuple) else [tuple_result]
                        except (ValueError, SyntaxError, TypeError):
                            # If it's just a plain string, wrap it in a list
                            args = [parsed]
                    else:
                        # Single value (int, etc.)
                        args = [parsed]
                except (json.JSONDecodeError, TypeError):
                    # Not JSON, try Python tuple/list format directly
                    try:
                        parsed_tuple = ast.literal_eval(obj.task_args)
                        args = list(parsed_tuple) if isinstance(parsed_tuple, tuple) else [parsed_tuple]
                    except (ValueError, SyntaxError, TypeError):
                        pass
        except Exception:
            pass
        
        try:
            if obj.task_kwargs and obj.task_kwargs != '{}':
                parsed = json.loads(obj.task_kwargs)
                # If it's a dict, use it directly
                if isinstance(parsed, dict):
                    kwargs = parsed
                # If it's a string representation of a dict, try to parse it
                elif isinstance(parsed, str):
                    try:
                        kwargs = ast.literal_eval(parsed)
                    except (ValueError, SyntaxError, TypeError):
                        pass
        except (json.JSONDecodeError, TypeError):
            pass
        
        # Package tasks
        if 'package' in task_name.lower():
            if 'build_package_task' in task_name:
                build_queue_id = args[0] if args else kwargs.get('build_queue_id')
                if build_queue_id:
                    return {
                        'type': 'build',
                        'description': 'Building package',
                        'build_queue_id': build_queue_id
                    }
            elif 'build_single_package' in task_name:
                package_id = args[0] if args else kwargs.get('package_id')
                if package_id:
                    return {
                        'type': 'package',
                        'description': 'Building package',
                        'package_id': package_id
                    }
            elif 'generate_spec_file_task' in task_name:
                package_id = args[0] if args else kwargs.get('package_id')
                if package_id:
                    return {
                        'type': 'package',
                        'description': 'Generating spec file',
                        'package_id': package_id
                    }
            elif 'fetch_package_source' in task_name:
                package_id = args[0] if args else kwargs.get('package_id')
                if package_id:
                    return {
                        'type': 'package',
                        'description': 'Fetching source files',
                        'package_id': package_id
                    }
        
        # Build tasks
        elif 'build' in task_name.lower():
            if 'build_job_task' in task_name or 'process_build_job' in task_name:
                build_job_id = args[0] if args else kwargs.get('build_job_id')
                if build_job_id:
                    return {
                        'type': 'build_job',
                        'description': 'Processing build job',
                        'build_job_id': build_job_id
                    }
            elif 'build_srpm' in task_name:
                return {
                    'type': 'build',
                    'description': 'Building SRPM',
                }
            elif 'build_rpm' in task_name:
                return {
                    'type': 'build',
                    'description': 'Building RPM',
                }
        
        # Project tasks
        elif 'project' in task_name.lower():
            if 'analyze_project' in task_name or 'process_project' in task_name:
                project_id = args[0] if args else kwargs.get('project_id')
                if project_id:
                    return {
                        'type': 'project',
                        'description': 'Analyzing project dependencies',
                        'project_id': project_id
                    }
            elif 'build_project' in task_name:
                project_id = args[0] if args else kwargs.get('project_id')
                if project_id:
                    return {
                        'type': 'project',
                        'description': 'Building project packages',
                        'project_id': project_id
                    }
        
        # Repository tasks
        elif 'repository' in task_name.lower() or 'repo' in task_name.lower():
            if 'sync_repository' in task_name:
                repository_id = args[0] if args else kwargs.get('repository_id')
                if repository_id:
                    return {
                        'type': 'repository',
                        'description': 'Syncing repository',
                        'repository_id': repository_id
                    }
            elif 'create_repository' in task_name or 'createrepo' in task_name:
                return {
                    'type': 'repository',
                    'description': 'Creating repository metadata',
                }
        
        # GPG key tasks
        elif 'gpg' in task_name.lower():
            return {
                'type': 'gpg',
                'description': 'GPG key operation',
            }
        
        # Default - extract task name
        simple_name = task_name.split('.')[-1].replace('_', ' ').title()
        return {
            'type': 'task',
            'description': simple_name,
        }
    
    def get_related_package(self, obj):
        """
        Get package information if this task is related to a package.
        
        Returns dict with package name and ID if found.
        """
        from backend.apps.packages.models import Package
        from backend.apps.builds.models import BuildQueue
        
        try:
            task_context = self.get_task_context(obj)
            
            # Direct package task
            if task_context.get('package_id'):
                try:
                    package_id = task_context['package_id']
                    # Ensure it's an integer
                    if not isinstance(package_id, int):
                        package_id = int(package_id)
                    
                    package = Package.objects.get(id=package_id)
                    return {
                        'id': package.id,
                        'name': package.name,
                        'version': package.version,
                    }
                except (Package.DoesNotExist, ValueError, TypeError):
                    pass
            
            # Build task - get package from build queue
            if task_context.get('build_queue_id'):
                try:
                    build_queue_id = task_context['build_queue_id']
                    # Ensure it's an integer
                    if not isinstance(build_queue_id, int):
                        build_queue_id = int(build_queue_id)
                    
                    build_queue = BuildQueue.objects.select_related('package').get(
                        id=build_queue_id
                    )
                    return {
                        'id': build_queue.package.id,
                        'name': build_queue.package.name,
                        'version': build_queue.package.version,
                        'build_queue_id': build_queue.id,
                        'rhel_version': build_queue.rhel_version,
                    }
                except (BuildQueue.DoesNotExist, ValueError, TypeError):
                    pass
        except Exception:
            # Silently fail on any error - better to return None than crash
            pass
        
        return None
