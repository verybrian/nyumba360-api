from rest_framework import status, permissions
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import permission_classes

from app.models import Plan, SMSMessageTemplate
from app.utils import AuditViewSetMixin, DeleteMixin
from .serializers import PlanSerializer, SMSMessageTemplateSerializer


class PlanViewset(AuditViewSetMixin, DeleteMixin, ModelViewSet):
    queryset = Plan.objects.all()
    serializer_class = PlanSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return Plan.objects.all()
        return Response({'detail': 'You do not have permission to view plans.'}, status=status.HTTP_403_FORBIDDEN)

    def perform_create(self, serializer):
        if not request.user.is_superuser:
            return Response({'detail': 'You do not have permission to create plans.'}, status=status.HTTP_403_FORBIDDEN)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan = serializer.save()
        return Response({'message': 'Plan created successfully', 'plan': PlanSerializer(plan).data}, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        instance = serializer.instance
        if not request.user.is_superuser:
            return Response({'detail': 'You do not have permission to edit plans.'}, status=status.HTTP_403_FORBIDDEN)

        serializer.save()


class SMSMessageTemplateViewSet(AuditViewSetMixin, DeleteMixin, ModelViewSet):
    queryset = SMSMessageTemplate.objects.all()
    serializer_class = SMSMessageTemplateSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if not self.request.user.is_staff:
            raise PermissionDenied("You are not allowed to access system templates.")
        return queryset

    def perform_create(self, serializer):
        if not self.request.user.is_staff:
            raise PermissionDenied("You cannot create system templates.")
        serializer.save()

    def perform_update(self, serializer):
        if not self.request.user.is_staff:
            raise PermissionDenied("You cannot edit system templates.")
        serializer.save()
