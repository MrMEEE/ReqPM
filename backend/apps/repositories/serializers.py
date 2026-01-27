"""
Serializers for Repositories app
"""
from rest_framework import serializers
from backend.apps.repositories.models import (
    Repository, RepositoryPackage, RepositoryMetadata, RepositoryAccess
)
from backend.apps.packages.serializers import PackageBuildSerializer


class RepositoryMetadataSerializer(serializers.ModelSerializer):
    """Serializer for RepositoryMetadata model"""
    
    class Meta:
        model = RepositoryMetadata
        fields = [
            'id', 'package_count', 'last_updated',
            'revision', 'checksum', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class RepositoryPackageSerializer(serializers.ModelSerializer):
    """Serializer for RepositoryPackage model"""
    
    package_build = PackageBuildSerializer(read_only=True)
    
    class Meta:
        model = RepositoryPackage
        fields = [
            'id', 'name', 'version', 'rpm_path',
            'package_build', 'added_at'
        ]
        read_only_fields = ['id', 'added_at']


class RepositoryAccessSerializer(serializers.ModelSerializer):
    """Serializer for RepositoryAccess model"""
    
    class Meta:
        model = RepositoryAccess
        fields = [
            'id', 'access_type', 'allowed_users',
            'allowed_groups', 'requires_auth', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class RepositoryListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for repository listings"""
    
    project_name = serializers.CharField(source='project.name', read_only=True)
    package_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Repository
        fields = [
            'id', 'name', 'description', 'project', 'project_name',
            'rhel_version', 'repo_url', 'status', 'is_active',
            'package_count', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'project_name', 'status', 'package_count',
            'created_at', 'updated_at'
        ]
    
    def get_package_count(self, obj):
        """Get count of packages in repository"""
        metadata = obj.metadata.first()
        if metadata:
            return metadata.package_count
        return 0


class RepositoryDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for repository with all data"""
    
    project_name = serializers.CharField(source='project.name', read_only=True)
    packages = RepositoryPackageSerializer(many=True, read_only=True)
    metadata = RepositoryMetadataSerializer(many=True, read_only=True)
    access = RepositoryAccessSerializer(many=True, read_only=True)
    repo_file_content = serializers.CharField(read_only=True)
    
    class Meta:
        model = Repository
        fields = [
            'id', 'name', 'description', 'project', 'project_name',
            'rhel_version', 'repo_path', 'base_url', 'repo_url',
            'gpg_key_id', 'gpg_check', 'status', 'is_active',
            'packages', 'metadata', 'access', 'repo_file_content',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'project_name', 'status', 'packages',
            'metadata', 'access', 'repo_file_content',
            'created_at', 'updated_at'
        ]


class RepositoryCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating repositories"""
    
    class Meta:
        model = Repository
        fields = [
            'name', 'description', 'project', 'rhel_version',
            'repo_path', 'base_url', 'gpg_key_id', 'gpg_check'
        ]
    
    def validate_repo_path(self, value):
        """Validate repo path"""
        import os
        from pathlib import Path
        
        path = Path(value)
        
        # Check if parent directory exists or can be created
        if not path.parent.exists():
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                raise serializers.ValidationError(
                    f"Cannot create repository directory: {e}"
                )
        
        return value
    
    def create(self, validated_data):
        """Create repository and initialize it"""
        validated_data['status'] = 'pending'
        repository = Repository.objects.create(**validated_data)
        
        # Trigger repository creation
        from backend.apps.repositories.tasks import create_repository_task
        create_repository_task.delay(repository.id)
        
        return repository


class RepositoryUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating repositories"""
    
    class Meta:
        model = Repository
        fields = [
            'name', 'description', 'base_url',
            'gpg_key_id', 'gpg_check', 'is_active'
        ]
