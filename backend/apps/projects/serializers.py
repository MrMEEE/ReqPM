"""
Serializers for Projects app
"""
from rest_framework import serializers
from backend.apps.projects.models import (
    Project, ProjectBranch, ProjectBuildConfig, ProjectCollaborator
)
from backend.apps.users.serializers import UserSerializer


class ProjectBranchSerializer(serializers.ModelSerializer):
    """Serializer for ProjectBranch model"""
    
    class Meta:
        model = ProjectBranch
        fields = [
            'id', 'name', 'commit_hash', 'is_tag',
            'last_updated'
        ]
        read_only_fields = ['id', 'last_updated']


class ProjectBuildConfigSerializer(serializers.ModelSerializer):
    """Serializer for ProjectBuildConfig model"""
    
    created_by = UserSerializer(read_only=True)
    
    class Meta:
        model = ProjectBuildConfig
        fields = [
            'id', 'name', 'description', 'rhel_version',
            'build_options', 'is_default',
            'created_by', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']


class ProjectCollaboratorSerializer(serializers.ModelSerializer):
    """Serializer for ProjectCollaborator model"""
    
    user = UserSerializer(read_only=True)
    user_id = serializers.IntegerField(write_only=True)
    added_by = UserSerializer(read_only=True)
    
    class Meta:
        model = ProjectCollaborator
        fields = [
            'id', 'user', 'user_id', 'role', 'permissions',
            'added_by', 'added_at'
        ]
        read_only_fields = ['id', 'user', 'added_by', 'added_at']


class ProjectListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for project listings"""
    
    owner = UserSerializer(read_only=True)
    package_count = serializers.SerializerMethodField()
    branch = serializers.CharField(source='git_branch')
    tag = serializers.CharField(source='git_tag', allow_blank=True, required=False)
    
    class Meta:
        model = Project
        fields = [
            'id', 'name', 'description', 'git_url', 'branch', 'tag',
            'status', 'owner', 'build_version', 'python_version',
            'rhel_version', 'package_count', 'created_at', 'updated_at', 'last_build_at'
        ]
        read_only_fields = [
            'id', 'status', 'owner', 'package_count',
            'created_at', 'updated_at', 'last_build_at'
        ]
    
    def get_package_count(self, obj):
        """Get count of packages for this project"""
        return obj.packages.count()


class ProjectDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for project with all related data"""
    
    owner = UserSerializer(read_only=True)
    branches = ProjectBranchSerializer(many=True, read_only=True)
    build_configs = ProjectBuildConfigSerializer(many=True, read_only=True)
    collaborators = ProjectCollaboratorSerializer(many=True, read_only=True)
    package_count = serializers.SerializerMethodField()
    build_count = serializers.SerializerMethodField()
    branch = serializers.CharField(source='git_branch')
    tag = serializers.CharField(source='git_tag', allow_blank=True, required=False)
    
    class Meta:
        model = Project
        fields = [
            'id', 'name', 'description', 'git_url', 'branch', 'tag',
            'git_commit', 'requirements_files', 'build_version', 'python_version',
            'rhel_version',
            'status', 'status_message', 'owner',
            'git_ssh_key', 'git_api_token',
            'spec_repo_url', 'spec_repo_ssh_key', 'spec_repo_api_token',
            'parallel_builds', 'build_repositories',
            'branches', 'build_configs', 'collaborators',
            'package_count', 'build_count',
            'created_at', 'updated_at', 'last_build_at'
        ]
        read_only_fields = [
            'id', 'git_commit', 'status', 'status_message', 'owner',
            'branches', 'build_configs', 'collaborators',
            'package_count', 'build_count',
            'created_at', 'updated_at', 'last_build_at'
        ]
        extra_kwargs = {
            'git_ssh_key': {'write_only': True},
            'git_api_token': {'write_only': True},
            'spec_repo_ssh_key': {'write_only': True},
            'spec_repo_api_token': {'write_only': True}
        }
    
    def get_package_count(self, obj):
        """Get count of packages for this project"""
        return obj.packages.count()
    
    def get_build_count(self, obj):
        """Get count of builds for this project"""
        return obj.build_jobs.count()


class ProjectCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating new projects"""
    
    branch = serializers.CharField(source='git_branch', default='main')
    tag = serializers.CharField(source='git_tag', allow_blank=True, required=False, default='')
    
    class Meta:
        model = Project
        fields = [
            'name', 'description', 'git_url', 'branch', 'tag',
            'requirements_files', 'build_version', 'rhel_version', 'python_version',
            'git_ssh_key', 'git_api_token'
        ]
        extra_kwargs = {
            'git_ssh_key': {'write_only': True, 'required': False},
            'git_api_token': {'write_only': True, 'required': False},
            'requirements_files': {'required': False, 'default': list},
            'build_version': {'required': False},
            'rhel_version': {'required': False, 'default': '9'},
            'python_version': {'required': False, 'default': 'default'}
        }
    
    def create(self, validated_data):
        """Create project and trigger initial sync"""
        # Set owner to current user
        validated_data['owner'] = self.context['request'].user
        validated_data['status'] = 'pending'
        
        # Set defaults for required fields if not provided
        if 'build_version' not in validated_data:
            validated_data['build_version'] = '1.0'
        
        project = Project.objects.create(**validated_data)
        
        # Trigger clone task
        from backend.apps.projects.tasks import clone_project_task
        clone_project_task.delay(project.id)
        
        return project


class ProjectUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating projects"""
    
    branch = serializers.CharField(source='git_branch', required=False)
    tag = serializers.CharField(source='git_tag', allow_blank=True, required=False)
    
    class Meta:
        model = Project
        fields = [
            'name', 'description', 'branch', 'tag',
            'requirements_files', 'build_version', 'python_version', 'rhel_version',
            'parallel_builds', 'build_repositories',
            'git_ssh_key', 'git_api_token',
            'spec_repo_url', 'spec_repo_ssh_key', 'spec_repo_api_token'
        ]
        extra_kwargs = {
            'git_ssh_key': {'write_only': True, 'required': False},
            'git_api_token': {'write_only': True, 'required': False},
            'spec_repo_ssh_key': {'write_only': True, 'required': False},
            'spec_repo_api_token': {'write_only': True, 'required': False}
        }
    
    def update(self, instance, validated_data):
        """Update project and trigger sync if git ref changed"""
        branch_changed = 'git_branch' in validated_data and validated_data['git_branch'] != instance.git_branch
        tag_changed = 'git_tag' in validated_data and validated_data['git_tag'] != instance.git_tag
        requirements_changed = 'requirements_files' in validated_data and validated_data['requirements_files'] != instance.requirements_files
        python_version_changed = 'python_version' in validated_data and validated_data['python_version'] != instance.python_version
        
        project = super().update(instance, validated_data)
        
        # Trigger sync if branch or tag changed
        if branch_changed or tag_changed:
            from backend.apps.projects.tasks import clone_project_task
            clone_project_task.delay(project.id)
        # Trigger re-analysis if requirements files changed
        elif requirements_changed:
            from backend.apps.projects.tasks import analyze_requirements_task
            analyze_requirements_task.delay(project.id)
        # Trigger spec regeneration if python_version changed
        elif python_version_changed:
            from backend.apps.packages.tasks import generate_all_spec_files_task
            generate_all_spec_files_task.delay(project.id)
        
        return project
