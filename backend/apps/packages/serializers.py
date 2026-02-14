"""
Serializers for Packages app
"""
from rest_framework import serializers
from backend.apps.packages.models import (
    Package, PackageDependency, PackageBuild, SpecFileRevision, PackageLog, PackageExtra
)
from backend.apps.users.serializers import UserSerializer


class PackageDependencySerializer(serializers.ModelSerializer):
    """Serializer for PackageDependency model"""
    
    depends_on_name = serializers.CharField(source='depends_on.name', read_only=True)
    depends_on_version = serializers.CharField(source='depends_on.version', read_only=True)
    
    class Meta:
        model = PackageDependency
        fields = [
            'id', 'depends_on', 'depends_on_name', 'depends_on_version',
            'dependency_type', 'version_constraint'
        ]
        read_only_fields = ['id']


class PackageBuildSerializer(serializers.ModelSerializer):
    """Serializer for PackageBuild model"""
    
    built_by = UserSerializer(read_only=True)
    
    class Meta:
        model = PackageBuild
        fields = [
            'id', 'rhel_version', 'status', 'rpm_file', 'srpm_file',
            'build_log', 'built_by', 'built_at'
        ]
        read_only_fields = ['id', 'built_by', 'built_at']


class SpecFileRevisionSerializer(serializers.ModelSerializer):
    """Serializer for SpecFileRevision model"""
    
    created_by = UserSerializer(read_only=True)
    
    class Meta:
        model = SpecFileRevision
        fields = [
            'id', 'content', 'commit_message', 'git_commit_hash', 'git_commit_url',
            'created_by', 'created_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at']


class PackageListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for package listings"""
    
    project_name = serializers.CharField(source='project.name', read_only=True)
    dependency_count = serializers.SerializerMethodField()
    spec_files_count = serializers.SerializerMethodField()
    dependent_packages = serializers.SerializerMethodField()
    extras = serializers.SerializerMethodField()
    source_fetched = serializers.BooleanField(read_only=True)
    source_path = serializers.CharField(read_only=True)
    has_build_log = serializers.SerializerMethodField()
    
    class Meta:
        model = Package
        fields = [
            'id', 'name', 'version', 'package_type',
            'status', 'project', 'project_name',
            'dependency_count', 'spec_files_count', 'requirements_file',
            'is_direct_dependency', 'dependent_packages', 'extras',
            'source_fetched', 'source_path',
            'build_status', 'build_started_at', 'build_completed_at',
            'build_error_message', 'analyzed_errors', 'srpm_path', 'rpm_path',
            'has_build_log',
            'created_at', 'updated_at', 'last_built_at'
        ]
        read_only_fields = [
            'id', 'project_name', 'dependency_count', 'spec_files_count',
            'dependent_packages', 'extras', 'source_fetched', 'source_path',
            'build_status', 'build_started_at', 'build_completed_at',
            'srpm_path', 'rpm_path', 'created_at', 'updated_at', 'last_built_at'
        ]
    
    def get_has_build_log(self, obj):
        """Check if a build log exists (without sending the full log)"""
        return bool(obj.build_log)

    def get_dependency_count(self, obj):
        """Get count of dependencies"""
        return obj.dependencies.count()
    
    def get_spec_files_count(self, obj):
        """Get count of spec file revisions"""
        return obj.spec_revisions.count()
    
    def get_dependent_packages(self, obj):
        """Get list of packages that depend on this package"""
        # Get all dependencies where this package is depended upon
        dependents = obj.dependents.select_related('package').values_list('package__name', flat=True)
        return list(dependents)
    
    def get_extras(self, obj):
        """Get list of extras with their enabled status"""
        return [
            {'id': extra.id, 'name': extra.name, 'enabled': extra.enabled}
            for extra in obj.extras.all()
        ]


class PackageExtraSerializer(serializers.ModelSerializer):
    """Serializer for PackageExtra model"""
    
    class Meta:
        model = PackageExtra
        fields = ['id', 'name', 'enabled', 'dependencies', 'created_at', 'updated_at']
        read_only_fields = ['id', 'dependencies', 'created_at', 'updated_at']


class PackageDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for package with all related data"""
    
    project_name = serializers.CharField(source='project.name', read_only=True)
    dependencies = PackageDependencySerializer(many=True, read_only=True)
    builds = PackageBuildSerializer(many=True, read_only=True)
    spec_files = SpecFileRevisionSerializer(many=True, read_only=True, source='spec_revisions')
    extras = PackageExtraSerializer(many=True, read_only=True)
    latest_spec = serializers.SerializerMethodField()
    
    class Meta:
        model = Package
        fields = [
            'id', 'name', 'version', 'package_type',
            'status', 'build_order', 'description', 'license', 'homepage',
            'project', 'project_name', 'dependencies', 'builds',
            'spec_files', 'extras', 'latest_spec',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'project_name', 'dependencies', 'builds',
            'spec_files', 'extras', 'latest_spec', 'created_at', 'updated_at'
        ]
    
    def get_latest_spec(self, obj):
        """Get latest spec file revision"""
        latest = obj.spec_revisions.order_by('-created_at').first()
        if latest:
            return SpecFileRevisionSerializer(latest).data
        return None


class PackageCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating packages"""
    
    class Meta:
        model = Package
        fields = [
            'name', 'version', 'package_type', 'description',
            'license', 'homepage', 'project'
        ]
    
    def create(self, validated_data):
        """Create package with default values"""
        validated_data['status'] = 'pending'
        return Package.objects.create(**validated_data)


class PackageUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating packages"""
    
    class Meta:
        model = Package
        fields = [
            'version', 'package_type', 'description',
            'license', 'homepage', 'is_active'
        ]


class SpecFileCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating spec file revisions"""
    
    class Meta:
        model = SpecFileRevision
        fields = ['content', 'commit_message']
    
    def create(self, validated_data):
        """Create spec file revision"""
        package = self.context['package']
        user = self.context['request'].user
        
        return SpecFileRevision.objects.create(
            package=package,
            created_by=user,
            **validated_data
        )


class PackageLogSerializer(serializers.ModelSerializer):
    """Serializer for PackageLog model"""
    
    class Meta:
        model = PackageLog
        fields = ['id', 'level', 'message', 'timestamp']
        read_only_fields = ['id', 'timestamp']
