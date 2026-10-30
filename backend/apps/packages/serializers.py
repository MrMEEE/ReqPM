"""
Serializers for Packages app
"""
from rest_framework import serializers
from backend.apps.packages.models import (
    Package, PackageDependency, PackageBuild, SpecFileRevision, PackageLog, PackageExtra,
    AIFixAttempt,
)
from backend.apps.users.serializers import UserSerializer


def _collect_dependency_blockers(package, node_cache):
    """Include blockers of waiting dependencies, visiting each package once."""
    from backend.apps.packages.tasks import (
        _analyze_missing_item_resolution, _normalize_dep_names,
        _is_self_dependency_item, _satisfies_dep_version_constraint, _built_for_rhel,
    )

    missing_categories = {
        'Missing Packages', 'Missing Dependencies', 'Missing Python Modules',
        'Missing Header Files', 'Missing Rust/Cargo', 'Missing Python Wheel', 'Missing GCC',
    }
    queue = [package]
    visited = set()
    blockers = []
    while queue:
        current = queue.pop()
        if current.pk in visited:
            continue
        visited.add(current.pk)
        if current.build_status not in (
            'waiting_for_deps', 'dep_build_pending', 'missing_packages', 'pending', 'failed',
        ):
            continue
        if current.pk in node_cache:
            cached_blockers, cached_dependencies = node_cache[current.pk]
            blockers.extend(cached_blockers)
            queue.extend(cached_dependencies)
            continue
        blocker_start = len(blockers)
        queue_start = len(queue)
        items = [
            item for error in (current.analyzed_errors or [])
            if error.get('category') in missing_categories
            for item in (error.get('items') or [])
            if _normalize_dep_names(item) and not _is_self_dependency_item(current, item)
        ]
        resolution = _analyze_missing_item_resolution(current, current.project, items)
        for item in (
            resolution['unresolved_with_project_match']
            + resolution['unresolved_without_project_match']
        ):
            names = {name.lower() for name in _normalize_dep_names(item)}
            candidates = []
            for dep in resolution['matched']:
                if dep.pk == current.pk or dep.name.lower() not in names:
                    continue
                if not _satisfies_dep_version_constraint(item, dep.version):
                    reason = 'Version conflict'
                elif not _built_for_rhel(dep, current.project.rhel_version):
                    reason = 'Built for a different RHEL version'
                elif dep.build_status not in ('completed', 'not_required'):
                    reason = 'Dependency is not built'
                else:
                    reason = 'Required RPM extras are missing or not enabled'
                candidates.append({
                    'id': dep.pk, 'name': dep.name, 'version': dep.version,
                    'build_status': dep.build_status, 'reason': reason,
                })
                queue.append(dep)
            blockers.append({
                'package_id': current.pk, 'package_name': current.name,
                'requirement': item, 'candidates': candidates,
            })
        if current.build_status == 'waiting_for_deps':
            for relation in current.dependencies.select_related('depends_on'):
                dep = relation.depends_on
                if dep.build_status in ('completed', 'not_required'):
                    continue
                blockers.append({
                    'package_id': current.pk, 'package_name': current.name,
                    'requirement': relation.version_constraint or dep.name,
                    'candidates': [{
                        'id': dep.pk, 'name': dep.name, 'version': dep.version,
                        'build_status': dep.build_status, 'reason': 'Dependency is not built',
                    }],
                })
                queue.append(dep)
        node_cache[current.pk] = (blockers[blocker_start:], queue[queue_start:])
    return blockers


def get_dependency_blockers(package):
    return _collect_dependency_blockers(package, {})


class PackageStatusSerializer(serializers.ModelSerializer):
    def get_dependency_blockers(self, obj):
        cache = self.context.setdefault('dependency_blockers', {})
        if obj.pk not in cache:
            nodes = self.context.setdefault('dependency_blocker_nodes', {})
            cache[obj.pk] = _collect_dependency_blockers(obj, nodes)
        return cache[obj.pk]

    def get_status_detail(self, obj):
        lines = [obj.get_build_status_display()]
        blockers = self.get_dependency_blockers(obj)
        for blocker in blockers:
            lines.append(f"{blocker['package_name']} requires {blocker['requirement']}")
            if not blocker['candidates']:
                lines.append('No matching package in this project.')
            for candidate in blocker['candidates']:
                lines.append(
                    f"{candidate['reason']}: {candidate['name']} {candidate['version']} "
                    f"({candidate['build_status'].replace('_', ' ')})",
                )
        if obj.build_status == 'pending' and not blockers:
            lines.append('Queued for build execution; waiting for a worker or available build slot.')
        if obj.build_error_message and obj.build_status == 'failed':
            lines.append(obj.build_error_message)
        return '\n'.join(lines)


class PackageDependencySerializer(serializers.ModelSerializer):
    """Serializer for PackageDependency model"""
    
    depends_on_name = serializers.CharField(source='depends_on.name', read_only=True)
    depends_on_version = serializers.CharField(source='depends_on.version', read_only=True)
    depends_on_build_status = serializers.CharField(source='depends_on.build_status', read_only=True)
    
    class Meta:
        model = PackageDependency
        fields = [
            'id', 'depends_on', 'depends_on_name', 'depends_on_version',
            'depends_on_build_status', 'dependency_type', 'version_constraint'
        ]
        read_only_fields = ['id']


class PackageDependentSerializer(serializers.ModelSerializer):
    """Serializer for the reverse side of PackageDependency (packages requiring this one)"""

    package_name = serializers.CharField(source='package.name', read_only=True)
    package_version = serializers.CharField(source='package.version', read_only=True)
    package_build_status = serializers.CharField(source='package.build_status', read_only=True)

    class Meta:
        model = PackageDependency
        fields = [
            'id', 'package', 'package_name', 'package_version',
            'package_build_status', 'dependency_type', 'version_constraint'
        ]
        read_only_fields = fields


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
    ai_feedback_by_username = serializers.CharField(source='ai_feedback_by.username', read_only=True)
    ai_taught_by_username = serializers.CharField(source='ai_taught_by.username', read_only=True)
    is_ai_fix = serializers.SerializerMethodField()

    def get_is_ai_fix(self, obj):
        return bool((obj.commit_message or '').startswith('AI-fixed:'))
    
    class Meta:
        model = SpecFileRevision
        fields = [
            'id', 'content', 'commit_message', 'git_commit_hash', 'git_commit_url',
            'created_by', 'created_at',
            'is_ai_fix',
            'ai_feedback', 'ai_feedback_note', 'ai_feedback_at', 'ai_feedback_by_username',
            'ai_taught', 'ai_taught_note', 'ai_taught_at', 'ai_taught_by_username',
        ]
        read_only_fields = ['id', 'created_by', 'created_at']


class AIFixAttemptSerializer(serializers.ModelSerializer):
    """Serializer for a recorded AI fixer exchange."""

    created_by_username = serializers.CharField(source='created_by.username', read_only=True, default=None)
    revision_commit_message = serializers.CharField(source='revision.commit_message', read_only=True, default=None)
    revision_ai_feedback = serializers.CharField(source='revision.ai_feedback', read_only=True, default=None)
    summary = serializers.SerializerMethodField()

    def get_summary(self, obj):
        from backend.core.ai_fixer import summarize_attempt
        if obj.status in ('pending', 'running'):
            return 'Waiting for the AI model...'
        return summarize_attempt(obj)

    class Meta:
        model = AIFixAttempt
        fields = [
            'id', 'parent', 'source', 'status', 'summary',
            'user_message', 'prompt', 'raw_response',
            'error_category', 'reasoning', 'actions', 'applied_changes', 'error_message',
            'model_name', 'rebuild_requested',
            'revision', 'revision_commit_message', 'revision_ai_feedback',
            'created_by_username', 'created_at', 'completed_at',
        ]
        read_only_fields = fields


class PackageListSerializer(PackageStatusSerializer):
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
    status_detail = serializers.SerializerMethodField()
    dependency_blockers = serializers.SerializerMethodField()
    
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
            'has_build_log', 'waiting_for_dep_names', 'failed_dep_names', 'dep_blocking_items', 'status_detail', 'dependency_blockers',
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
        from backend.apps.packages.tasks import _analyze_missing_item_resolution
        items = [
            item for error in (obj.analyzed_errors or [])
            if error.get('category') in {
                'Missing Packages', 'Missing Dependencies', 'Missing Python Modules',
                'Missing Header Files', 'Missing Rust/Cargo', 'Missing Python Wheel', 'Missing GCC',
            }
            for item in (error.get('items') or []) if item
        ]
        resolution = _analyze_missing_item_resolution(obj, obj.project, items)
        return (
            resolution['unresolved_with_project_match']
            + resolution['unresolved_without_project_match']
        )

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


class PackageDetailSerializer(PackageStatusSerializer):
    """Detailed serializer for package with all related data"""
    
    project_name = serializers.CharField(source='project.name', read_only=True)
    dependencies = PackageDependencySerializer(many=True, read_only=True)
    builds = PackageBuildSerializer(many=True, read_only=True)
    spec_files = SpecFileRevisionSerializer(many=True, read_only=True, source='spec_revisions')
    extras = PackageExtraSerializer(many=True, read_only=True)
    latest_spec = serializers.SerializerMethodField()
    source_fetched = serializers.BooleanField(read_only=True)
    has_build_log = serializers.SerializerMethodField()
    dependency_blockers = serializers.SerializerMethodField()
    status_detail = serializers.SerializerMethodField()
    ignored_version_requirements = serializers.SerializerMethodField()
    
    class Meta:
        model = Package
        fields = [
            'id', 'name', 'version', 'package_type',
            'status', 'build_order', 'summary', 'description', 'license', 'homepage',
            'build_system', 'autofix_enabled',
            'build_status', 'build_error_message', 'analyzed_errors',
            'source_fetched', 'has_build_log', 'dependency_blockers', 'status_detail',
            'ignored_version_requirements',
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

    def get_ignored_version_requirements(self, obj):
        from backend.apps.packages.version_relax import ignored_version_requirements
        latest = obj.spec_revisions.order_by('-created_at').only('content').first()
        return ignored_version_requirements(latest.content) if latest else []

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
