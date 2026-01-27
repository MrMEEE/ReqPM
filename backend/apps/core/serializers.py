"""
Serializers for Core app
"""
from rest_framework import serializers
from backend.apps.core.models import SystemSettings


class SystemSettingsSerializer(serializers.ModelSerializer):
    """Serializer for SystemSettings model"""
    
    class Meta:
        model = SystemSettings
        fields = [
            'id',
            'max_concurrent_builds',
            'cleanup_builds_after_days',
            'cleanup_repos_after_days',
            'auto_sync_projects',
            'sync_interval_hours',
            'repository_sync_interval_minutes',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def validate_max_concurrent_builds(self, value):
        """Validate max_concurrent_builds"""
        if value < 1 or value > 20:
            raise serializers.ValidationError("Must be between 1 and 20")
        return value
    
    def validate_cleanup_builds_after_days(self, value):
        """Validate cleanup_builds_after_days"""
        if value < 1 or value > 365:
            raise serializers.ValidationError("Must be between 1 and 365 days")
        return value
    
    def validate_cleanup_repos_after_days(self, value):
        """Validate cleanup_repos_after_days"""
        if value < 1 or value > 90:
            raise serializers.ValidationError("Must be between 1 and 90 days")
        return value
    
    def validate_sync_interval_hours(self, value):
        """Validate sync_interval_hours"""
        if value < 1 or value > 24:
            raise serializers.ValidationError("Must be between 1 and 24 hours")
        return value
    
    def validate_repository_sync_interval_minutes(self, value):
        """Validate repository_sync_interval_minutes"""
        if value < 5 or value > 1440:
            raise serializers.ValidationError("Must be between 5 and 1440 minutes")
        return value
