"""
ViewSets for Repositories app
"""
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from django.http import HttpResponse

from backend.apps.repositories.models import (
    Repository, RepositoryPackage, RepositoryMetadata, RepositoryAccess
)
from backend.apps.repositories.serializers import (
    RepositoryListSerializer, RepositoryDetailSerializer,
    RepositoryCreateSerializer, RepositoryUpdateSerializer,
    RepositoryPackageSerializer, RepositoryMetadataSerializer
)
from backend.apps.repositories.tasks import (
    update_repository_metadata_task, sign_repository_task,
    add_package_to_repository_task, remove_package_from_repository_task
)


class RepositoryViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Repository model
    
    list: Get all repositories
    create: Create a new repository
    retrieve: Get repository details
    update: Update repository
    destroy: Delete repository
    
    Custom actions:
    - packages: List packages in repository
    - add_package: Add a package to repository
    - remove_package: Remove a package from repository
    - update_metadata: Update repository metadata
    - sign: Sign repository with GPG key
    - repo_file: Get .repo file content
    """
    
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['project', 'rhel_version', 'status', 'is_active']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at', 'updated_at']
    ordering = ['-created_at']
    
    def get_queryset(self):
        """Get repositories for projects accessible by user"""
        user = self.request.user
        
        if user.is_staff:
            return Repository.objects.all()
        
        return Repository.objects.filter(
            project__owner=user
        ) | Repository.objects.filter(
            project__collaborators__user=user
        ).distinct()
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action"""
        if self.action == 'list':
            return RepositoryListSerializer
        elif self.action == 'create':
            return RepositoryCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return RepositoryUpdateSerializer
        else:
            return RepositoryDetailSerializer
    
    @action(detail=True, methods=['get'])
    def packages(self, request, pk=None):
        """
        List packages in repository
        
        GET /api/repositories/{id}/packages/
        """
        repository = self.get_object()
        packages = repository.packages.all().order_by('name')
        serializer = RepositoryPackageSerializer(packages, many=True)
        
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def add_package(self, request, pk=None):
        """
        Add a package build to repository
        
        POST /api/repositories/{id}/add_package/
        Body: {"package_build": 1}
        """
        repository = self.get_object()
        package_build_id = request.data.get('package_build')
        
        if not package_build_id:
            return Response(
                {'detail': 'package_build field is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Trigger add package task
        add_package_to_repository_task.delay(repository.id, package_build_id)
        
        return Response({
            'detail': 'Package addition triggered',
            'repository_id': repository.id,
            'package_build_id': package_build_id
        })
    
    @action(detail=True, methods=['post'])
    def remove_package(self, request, pk=None):
        """
        Remove a package from repository
        
        POST /api/repositories/{id}/remove_package/
        Body: {"package_name": "python3-requests-2.31.0-1.el8.noarch.rpm"}
        """
        repository = self.get_object()
        package_name = request.data.get('package_name')
        
        if not package_name:
            return Response(
                {'detail': 'package_name field is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Trigger remove package task
        remove_package_from_repository_task.delay(repository.id, package_name)
        
        return Response({
            'detail': 'Package removal triggered',
            'repository_id': repository.id,
            'package_name': package_name
        })
    
    @action(detail=True, methods=['post'])
    def update_metadata(self, request, pk=None):
        """
        Update repository metadata
        
        POST /api/repositories/{id}/update_metadata/
        """
        repository = self.get_object()
        
        # Trigger metadata update
        update_repository_metadata_task.delay(repository.id)
        
        return Response({
            'detail': 'Metadata update triggered',
            'repository_id': repository.id
        })
    
    @action(detail=True, methods=['post'])
    def sign(self, request, pk=None):
        """
        Sign repository with GPG key
        
        POST /api/repositories/{id}/sign/
        Body: {"gpg_key_id": "ABCD1234"}
        """
        repository = self.get_object()
        gpg_key_id = request.data.get('gpg_key_id')
        
        if not gpg_key_id:
            return Response(
                {'detail': 'gpg_key_id field is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Trigger repository signing
        sign_repository_task.delay(repository.id, gpg_key_id)
        
        return Response({
            'detail': 'Repository signing triggered',
            'repository_id': repository.id,
            'gpg_key_id': gpg_key_id
        })
    
    @action(detail=True, methods=['get'], permission_classes=[AllowAny])
    def repo_file(self, request, pk=None):
        """
        Get .repo file content for YUM/DNF
        
        GET /api/repositories/{id}/repo_file/
        
        Returns plain text .repo file that can be installed on RHEL systems
        """
        repository = self.get_object()
        
        # Return as plain text
        return HttpResponse(
            repository.repo_file_content,
            content_type='text/plain'
        )
    
    @action(detail=True, methods=['get'])
    def metadata(self, request, pk=None):
        """
        Get repository metadata
        
        GET /api/repositories/{id}/metadata/
        """
        repository = self.get_object()
        metadata = repository.metadata.all().order_by('-last_updated')
        serializer = RepositoryMetadataSerializer(metadata, many=True)
        
        return Response(serializer.data)


class RepositoryPackageViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ReadOnly ViewSet for RepositoryPackage model
    
    View packages in repositories
    """
    
    permission_classes = [IsAuthenticated]
    serializer_class = RepositoryPackageSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['repository', 'name']
    search_fields = ['name', 'version']
    ordering_fields = ['name', 'added_at']
    ordering = ['name']
    
    def get_queryset(self):
        """Get packages from accessible repositories"""
        user = self.request.user
        
        if user.is_staff:
            return RepositoryPackage.objects.all()
        
        return RepositoryPackage.objects.filter(
            repository__project__owner=user
        ) | RepositoryPackage.objects.filter(
            repository__project__collaborators__user=user
        ).distinct()
