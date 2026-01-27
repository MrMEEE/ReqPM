"""
System health check views
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from backend.plugins.builders import get_builder


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def system_health(request):
    """
    Check system health and builder availability
    """
    builder = get_builder('mock')
    mock_available = builder and builder.is_available()
    
    health = {
        'builders': {
            'mock': {
                'available': mock_available,
                'version': builder.version if mock_available else None,
                'message': (
                    'Mock is installed and ready' if mock_available else
                    'Mock is not installed. Install with: sudo dnf install mock. '
                    'See docs/MOCK_SETUP.md for setup instructions.'
                )
            }
        }
    }
    
    # Add available targets if mock is available
    if mock_available:
        health['builders']['mock']['targets'] = builder.get_available_targets()
    
    return Response(health)
