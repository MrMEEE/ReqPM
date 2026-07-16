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
    dependency_count = serializers.IntegerField(read_only=True)  # Use annotated value
    spec_files_count = serializers.IntegerField(read_only=True)  # Use annotated value
    dependent_packages = serializers.SerializerMethodField()
    extras = serializers.SerializerMethodField()
    source_fetched = serializers.BooleanField(read_only=True)
    source_path = serializers.CharField(read_only=True)
    has_build_log = serializers.SerializerMethodField()
    waiting_for_dep_names = serializers.SerializerMethodField()
    failed_dep_names = serializers.SerializerMethodField()
    dep_blocking_items = serializers.SerializerMethodField()
    
    class Meta:
        model = Package
        fields = [
            'id', 'name', 'version', 'package_type',
            'status', 'project', 'project_name',
            'dependency_count', 'spec_files_count', 'requirements_file',
            'is_direct_dependency', 'dependent_packages', 'extras',
            'source_fetched', 'source_path',
            'build_system',
            'build_status', 'build_started_at', 'build_completed_at',
            'build_error_message', 'build_dependency_repo_url', 'analyzed_errors', 'srpm_path', 'rpm_path',
            'has_build_log', 'waiting_for_dep_names', 'failed_dep_names', 'dep_blocking_items',
            'created_at', 'updated_at', 'last_built_at'
        ]
        read_only_fields = [
            'id', 'project_name', 'dependency_count', 'spec_files_count',
            'dependent_packages', 'extras', 'source_fetched', 'source_path',
            'build_status', 'build_started_at', 'build_completed_at',
            'build_dependency_repo_url', 'srpm_path', 'rpm_path', 'created_at', 'updated_at', 'last_built_at'
        ]
    
    def get_has_build_log(self, obj):
        """Check if a build log exists (without loading the deferred field)"""
        # Use annotated _has_build_log if available (from optimized query)
        if hasattr(obj, '_has_build_log'):
            return obj._has_build_log
        # Fallback: check if build_log exists (may trigger DB query if not deferred)
        return bool(obj.build_log)

    def get_waiting_for_dep_names(self, obj):
        """Names of pending/building direct deps (excludes failed) when package is waiting_for_deps."""
        if obj.build_status != 'waiting_for_deps':
            return []
        # Use prefetched data to avoid additional queries
        if hasattr(obj, '_prefetched_objects_cache') and 'dependencies' in obj._prefetched_objects_cache:
            return [
                dep.depends_on.name
                for dep in obj.dependencies.all()
                if dep.depends_on and dep.depends_on.build_status not in ('completed', 'not_required', 'failed')
            ]
        return []

    def get_failed_dep_names(self, obj):
        """Names of failed direct deps blocking this package from building."""
        if obj.build_status != 'waiting_for_deps':
            return []
        if hasattr(obj, '_prefetched_objects_cache') and 'dependencies' in obj._prefetched_objects_cache:
            return [
                dep.depends_on.name
                for dep in obj.dependencies.all()
                if dep.depends_on and dep.depends_on.build_status == 'failed'
            ]
        return []

    def get_dep_blocking_items(self, obj):
        """For dep_build_pending packages, return only the items still blocked (not yet completed)."""
        if obj.build_status != 'dep_build_pending':
            return []
        import re
        from django.db.models import Q
        from backend.apps.packages.models import Package as Pkg

        missing_cats = {
            'Missing Packages', 'Missing Dependencies', 'Missing Python Modules',
            'Missing Header Files', 'Missing Rust/Cargo', 'Missing Python Wheel', 'Missing GCC'
        }
        all_items = [
            item
            for e in (obj.analyzed_errors or [])
            if e.get('category') in missing_cats
            for item in (e.get('items') or [])
            if item
        ]
        if not all_items:
            return []

        # Normalize: python3dist(foo) >= x  →  candidate names
        def _normalize(item):
            s = item.strip().strip('()')
            s = re.split(r'\s+(with|[><=!])', s)[0].strip()
            m = re.match(r'python3?dist\(([^)]+)\)', s, re.IGNORECASE)
            if m:
                pkg_name = m.group(1).replace('_', '-').lower()
                return [f'python3-{pkg_name}', pkg_name]
            m = re.match(r'python3?\(([^)]+)\)', s, re.IGNORECASE)
            if m:
                pkg_name = m.group(1).replace('_', '-').lower()
                return [f'python3-{pkg_name}', pkg_name]
            return [s, s.replace('_', '-')]

        # Build a map: candidate_name → original item string
        name_to_item = {}
        for item in all_items:
            for name in _normalize(item):
                name_to_item[name.lower()] = item

        if not name_to_item:
            return all_items

        # Find matching project packages that are NOT yet completed
        q = Q()
        for name in name_to_item:
            q |= Q(name__iexact=name)
        unresolved_names = set(
            Pkg.objects.filter(project=obj.project)
            .filter(q)
            .exclude(build_status__in=('completed', 'not_required'))
            .values_list('name', flat=True)
        )

        # Return original item strings whose project package is still unresolved
        seen = set()
        result = []
        for name, item in name_to_item.items():
            if name in {n.lower() for n in unresolved_names} and item not in seen:
                seen.add(item)
                result.append(item)
        return result

    def get_dependent_packages(self, obj):
        """Get list of packages that depend on this package"""
        # Use prefetched data to avoid additional queries
        if hasattr(obj, '_prefetched_objects_cache') and 'dependents' in obj._prefetched_objects_cache:
            return [dep.package.name for dep in obj.dependents.all() if dep.package]
        return []
    
    def get_extras(self, obj):
        """Get list of extras with their enabled status"""
        # Use prefetched data to avoid additional queries
        if hasattr(obj, '_prefetched_objects_cache') and 'extras' in obj._prefetched_objects_cache:
            return [
                {'id': extra.id, 'name': extra.name, 'enabled': extra.enabled}
                for extra in obj.extras.all()
            ]
        return []


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
    source_fetched = serializers.BooleanField(read_only=True)
    has_build_log = serializers.SerializerMethodField()
    
    class Meta:
        model = Package
        fields = [
            'id', 'name', 'version', 'package_type',
            'status', 'build_order', 'description', 'license', 'homepage',
            'build_system',
            'build_status', 'build_error_message', 'analyzed_errors',
            'source_fetched', 'has_build_log',
            'project', 'project_name', 'dependencies', 'builds',
            'spec_files', 'extras', 'latest_spec',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'project_name', 'dependencies', 'builds',
            'spec_files', 'extras', 'latest_spec', 'created_at', 'updated_at',
            'build_status', 'build_error_message', 'analyzed_errors',
            'source_fetched', 'has_build_log',
        ]
    
    def get_has_build_log(self, obj):
        if hasattr(obj, '_has_build_log'):
            return obj._has_build_log
        return bool(obj.build_log)

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
    
    def validate(self, attrs):
        """Validate that no duplicate package exists (case-insensitive)"""
        name = attrs.get('name', '')
        project = attrs.get('project')
        
        # Normalize name to lowercase
        normalized_name = name.lower()
        
        # Check for existing package with same name (case-insensitive)
        if project:
            existing = Package.objects.filter(
                project=project,
                name__iexact=normalized_name
            ).first()
            
            if existing:
                raise serializers.ValidationError({
                    'name': f'Package "{existing.name}" already exists in this project (case-insensitive match)'
                })
        
        attrs['name'] = normalized_name  # Store normalized name
        return attrs
    
    def create(self, validated_data):
        """Create package with default values"""
        validated_data['status'] = 'pending'
        # Store original name as python_name if not provided
        if 'python_name' not in validated_data or not validated_data['python_name']:
            validated_data['python_name'] = validated_data['name']
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
