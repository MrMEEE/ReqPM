"""
Serializers for Builds app
"""
from rest_framework import serializers
from backend.apps.builds.models import BuildJob, BuildQueue, BuildWorker
from backend.apps.users.serializers import UserSerializer
from backend.apps.packages.serializers import PackageListSerializer


class BuildQueueSerializer(serializers.ModelSerializer):
    """Serializer for BuildQueue model"""
    
    package = PackageListSerializer(read_only=True)
    blocked_by_packages = serializers.SerializerMethodField()
    
    class Meta:
        model = BuildQueue
        fields = [
            'id', 'package', 'rhel_version', 'architecture', 'status',
            'dependencies_met', 'started_at', 'completed_at',
            'blocked_by', 'blocked_by_packages', 'created_at',
            'retry_count', 'celery_task_id', 'build_log', 'error_message',
            'analyzed_errors', 'srpm_path', 'rpm_path'
        ]
        read_only_fields = [
            'id', 'package', 'status', 'dependencies_met',
            'started_at', 'completed_at',
            'blocked_by', 'blocked_by_packages', 'created_at',
            'retry_count', 'celery_task_id', 'build_log', 'error_message',
            'analyzed_errors', 'srpm_path', 'rpm_path'
        ]
    
    def get_blocked_by_packages(self, obj):
        """Get names of packages blocking this build"""
        if obj.blocked_by.exists():
            return [p.name for p in obj.blocked_by.all()]
        return []


class BuildWorkerSerializer(serializers.ModelSerializer):
    """Serializer for BuildWorker model"""
    
    class Meta:
        model = BuildWorker
        fields = [
            'id', 'hostname', 'status', 'current_capacity',
            'max_capacity', 'last_seen', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class BuildJobListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for build job listings"""
    
    project_name = serializers.CharField(source='project.name', read_only=True)
    triggered_by = UserSerializer(read_only=True)
    progress = serializers.IntegerField(source='progress_percentage', read_only=True)
    
    class Meta:
        model = BuildJob
        fields = [
            'id', 'project', 'project_name', 'rhel_versions',
            'status', 'progress', 'total_packages',
            'completed_packages', 'failed_packages',
            'triggered_by', 'created_at', 'started_at', 'completed_at'
        ]
        read_only_fields = [
            'id', 'project_name', 'status', 'progress',
            'total_packages', 'completed_packages', 'failed_packages',
            'triggered_by', 'created_at', 'started_at', 'completed_at'
        ]


class BuildJobDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for build job with queue"""
    
    project_name = serializers.CharField(source='project.name', read_only=True)
    triggered_by = UserSerializer(read_only=True)
    queue = BuildQueueSerializer(source='queue_items', many=True, read_only=True)
    queue_stats = serializers.SerializerMethodField()
    progress = serializers.IntegerField(source='progress_percentage', read_only=True)
    
    class Meta:
        model = BuildJob
        fields = [
            'id', 'project', 'project_name', 'rhel_versions',
            'status', 'progress', 'total_packages',
            'completed_packages', 'failed_packages',
            'triggered_by', 'queue', 'queue_stats',
            'created_at', 'started_at', 'completed_at'
        ]
        read_only_fields = [
            'id', 'project_name', 'status', 'progress',
            'total_packages', 'completed_packages', 'failed_packages',
            'triggered_by', 'queue', 'queue_stats',
            'created_at', 'started_at', 'completed_at'
        ]
    
    def get_queue_stats(self, obj):
        """Get statistics about build queue"""
        queue = obj.queue_items.all()
        return {
            'total': queue.count(),
            'queued': queue.filter(status='queued').count(),
            'building': queue.filter(status='building').count(),
            'completed': queue.filter(status='completed').count(),
            'failed': queue.filter(status='failed').count(),
        }


class BuildJobCreateSerializer(serializers.Serializer):
    """Serializer for creating build jobs - uses project configuration"""
    
    project = serializers.IntegerField()
    
    def validate_project(self, value):
        """Validate that project exists and user has access"""
        from backend.apps.projects.models import Project
        
        try:
            project = Project.objects.get(id=value)
        except Project.DoesNotExist:
            raise serializers.ValidationError("Project not found")
        
        # Check access
        user = self.context['request'].user
        if project.owner != user and not user.is_staff:
            if not project.collaborators.filter(user=user).exists():
                raise serializers.ValidationError("You don't have access to this project")
        
        # Validate project has required configuration
        if not project.rhel_versions:
            raise serializers.ValidationError(
                "Project must have RHEL versions configured before building"
            )
        
        return value
    
    def create(self, validated_data):
        """Create build jobs using project configuration - one job per RHEL version"""
        from backend.apps.builds.tasks import create_build_job_task
        from backend.apps.projects.models import Project
        
        project_id = validated_data['project']
        project = Project.objects.get(id=project_id)
        user_id = self.context['request'].user.id
        
        # Create one build job per RHEL version
        rhel_versions = project.rhel_versions
        task_ids = []
        
        for rhel_version in rhel_versions:
            # Trigger build job creation for this specific RHEL version
            result = create_build_job_task.delay(project_id, [rhel_version], user_id)
            task_ids.append(result.id)
        
        # Return info about all created jobs
        return {
            'project_id': project_id,
            'rhel_versions': rhel_versions,
            'python_version': project.python_version,
            'build_jobs_count': len(rhel_versions),
            'task_ids': task_ids,
            'status': 'pending'
        }
