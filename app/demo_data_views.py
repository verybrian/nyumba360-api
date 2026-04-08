from rest_framework import permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db import transaction

from .models import Organization
from .demo_org_utils import clear_demo_data


class ClearDemoDataView(APIView):
    """
    API endpoint for users to clear their demo organization data.
    Only works if the user's organization is marked as demo.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        user = request.user
        organization = user.organization

        if not organization:
            return Response(
                {'error': 'No organization associated with this user'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not organization.is_demo:
            return Response(
                {'error': 'Organization is not a demo organization'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            delete_stats = clear_demo_data(organization)
            
            return Response({
                'message': 'Demo data cleared successfully',
                'organization_id': str(organization.id),
                'records_deleted': delete_stats,
                'is_demo': organization.is_demo,  # Should now be False
            }, status=status.HTTP_200_OK)
            
        except ValueError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {'error': f'Failed to clear demo data: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class OrganizationStatusView(APIView):
    """
    Get the current status of the user's organization including demo status.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        organization = user.organization

        if not organization:
            return Response(
                {'error': 'No organization associated with this user'},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response({
            'organization_id': str(organization.id),
            'name': organization.name,
            'status': organization.status,
            'is_demo': organization.is_demo,
            'is_template': organization.is_template,
            'demo_expires_at': organization.demo_expires_at.isoformat() if organization.demo_expires_at else None,
            'created_at': organization.created_at.isoformat(),
        }, status=status.HTTP_200_OK)