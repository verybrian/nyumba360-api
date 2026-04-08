import random
import string
import re
import json
import pandas as pd
import logging
from decimal import Decimal
from django.contrib.auth import login, logout, authenticate
from django.shortcuts import get_object_or_404
from django.db.models import Sum, Count, Q
from django.db import transaction
from django.utils import timezone
from django.utils.timezone import make_aware
from datetime import datetime, timedelta
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework import status, generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import permission_classes, action
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from .serializers import UserSerializer, RegisterSerializer, LoginSerializer, PropertySerializer, BlockSerializer, UnitSerializer, TenantSerializer, ReportSerializer, ExpenseSerializer, TenantPaymentSerializer, TenantTransactionSerializer, SMSMessageSerializer, OrganizationPaymentSerializer, OrganizationTransactionSerializer
from .models import User, Organization, Plan, Subscription, Property, Block, Unit, Tenant, Report, Expense, TenantPayment, TenantTransaction, SMSMessage, Receipt, OrganizationPayment, OrganizationTransaction
from .utils import calculate_next_billing_date, AuditViewSetMixin, DeleteMixin, generate_payment_ref, send_stk_push
from .demo_org_utils import create_demo_organization

logger = logging.getLogger(__name__)

class AuthView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user

        return Response({
            'id': user.id,
            'name': user.name,
        })


class UserViewSet(ModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return User.objects.filter(id=self.request.user.id)

    def get_object(self):
        return self.request.user

    def list(self, request):
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)

    def partial_update(self, request, *args, **kwargs):
        serializer = self.get_serializer(request.user, data=request.data, partial=True)

        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        user = request.user
        user.is_deleted = True
        user.deleted_at = timezone.now()
        user.is_active = False
        user.save()
        return Response({"message": "Account deleted"}, status=200)

    @action(detail=False, methods=['post'], url_path='pause')
    def pause(self, request):
        user = request.user
        user.is_paused = True
        user.paused_at = timezone.now()
        user.save()
        return Response({"message": "Account paused"})

    @action(detail=False, methods=['post'], url_path='change-pin')
    def change_pin(self, request):
        user = request.user
        current_pin = request.data.get('current_pin')
        new_pin = request.data.get('new_pin')

        if not current_pin or not new_pin:
            return Response({'detail': 'Both current and new PIN are required.'}, status=400)

        if not re.match(r'^\d{4}$', new_pin):
            return Response({'new_pin': ['PIN must be exactly 4 digits.']}, status=400)

        if not user.check_password(current_pin):
            return Response({'current_pin': ['Current PIN is incorrect.']}, status=400)

        user.set_password(new_pin)
        user.save()
        return Response({'message': 'PIN updated successfully.'})


@method_decorator(csrf_exempt, name='dispatch')
class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [permissions.AllowAny]
    serializer_class = RegisterSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        plan_id = request.data.get('plan_id')
        plan = (
            Plan.objects.filter(id=plan_id).first()
            if plan_id
            else Plan.objects.filter(name='basic').first()
        )

        with transaction.atomic():
            user = serializer.save(role='manager')

            try:
                org, copy_stats = create_demo_organization(user)
            except ValueError as e:
                org = Organization.objects.create(
                    name=f"Demo - {user.phone}",
                    status='active',
                    is_demo=True,
                    demo_expires_at=timezone.now() + timedelta(days=7)
                )
                copy_stats = {}

            Subscription.objects.create(
                organization=org,
                plan=plan,
                status='trialing',
                trial_ends_at=calculate_next_billing_date(),
            )

            user.organization = org
            user.save(update_fields=['organization_id'])

        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        
        response_data = {
            'message': 'User registered successfully',
            'is_demo': True,
            'demo_expires_at': org.demo_expires_at.isoformat() if org.demo_expires_at else None,
        }
        
        if copy_stats:
            response_data['demo_data_copied'] = copy_stats
        
        return Response(response_data, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = LoginSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']

        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        return Response({'message': 'Login successful'}, status=status.HTTP_200_OK)


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response({'message': 'Logout successful'}, status=status.HTTP_200_OK)


class DashboardView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')

        org = user.organization
        demo_days_left = None
        if org and org.is_demo and org.demo_expires_at:
            delta = org.demo_expires_at - timezone.now()
            demo_days_left = max(0, delta.days)

        properties = Property.objects.filter(organization=org) if not user.is_staff else Property.objects.all()
        tenants = Tenant.objects.filter(unit__property__organization=org) if not user.is_staff else Tenant.objects.all()
        payments = TenantPayment.objects.filter(unit__property__organization=org) if not user.is_staff else TenantPayment.objects.all()
        expenses = Expense.objects.filter(property__organization=org) if not user.is_staff else Expense.objects.all()

        if date_from:
            payments = payments.filter(payment_date__gte=make_aware(datetime.strptime(date_from, '%Y-%m-%d')))
            expenses = expenses.filter(date_incurred__gte=date_from)
        if date_to:
            payments = payments.filter(payment_date__lte=make_aware(datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)))
            expenses = expenses.filter(date_incurred__lte=date_to)

        if date_from and date_to:
            d_from = datetime.strptime(date_from, '%Y-%m-%d')
            d_to   = datetime.strptime(date_to,   '%Y-%m-%d')
            delta  = d_to - d_from
            prev_from = d_from - timedelta(days=delta.days + 1)
            prev_to   = d_from - timedelta(days=1)
        else:
            today     = datetime.today()
            prev_from = today.replace(day=1) - relativedelta(months=1)
            prev_to   = today.replace(day=1) - timedelta(days=1)

        base_payments = TenantPayment.objects.filter(unit__property__organization=org) \
            if not user.is_staff else TenantPayment.objects.all()
        base_expenses = Expense.objects.filter(property__organization=org) \
            if not user.is_staff else Expense.objects.all()

        prev_payments = base_payments.filter(
            payment_date__gte=make_aware(prev_from),
            payment_date__lte=make_aware(prev_to.replace(hour=23, minute=59, second=59))
        )
        prev_expenses = base_expenses.filter(
            date_incurred__gte=prev_from.date(),
            date_incurred__lte=prev_to.date()
        )

        prev_income   = prev_payments.filter(status='success', purpose='rent') \
                            .aggregate(total=Sum('amount'))['total'] or 0
        prev_expenses_total = prev_expenses.aggregate(total=Sum('amount'))['total'] or 0

        prev_tenants = Tenant.objects.filter(
            unit__property__organization=org,
            move_in_date__gte=prev_from.date(),
            move_in_date__lte=prev_to.date()
        ).count() if not user.is_staff else Tenant.objects.filter(
            move_in_date__gte=prev_from.date(),
            move_in_date__lte=prev_to.date()
        ).count()

        current_new_tenants = tenants.filter(
            move_in_date__gte=date_from or prev_to.date(),
            move_in_date__lte=date_to or datetime.today().date()
        ).count()

        income = payments.filter(status='success', purpose='rent').aggregate(total=Sum('amount'))['total'] or 0
        total_expenses = expenses.aggregate(total=Sum('amount'))['total'] or 0

        recent_payments = payments.order_by('-payment_date')[:20].values(
            'id', 'custom_id', 'tenant__name', 'unit', 'amount', 'payment_date', 'payment_method',
            'purpose', 'status', 'payment_ref'
        )
        recent_expenses = expenses.order_by('-date_incurred')[:20].values(
            'id', 'property', 'property__name', 'category',
            'description', 'amount', 'date_incurred'
        )

        return Response({
            'stats': {
                'properties': properties.count(),
                'tenants': tenants.filter(is_active=True).count(),
                'income': income,
                'expenses': total_expenses,
                'prev_income': prev_income,
                'prev_expenses': prev_expenses_total,
                'new_tenants_this_period': current_new_tenants,
                'new_tenants_prev_period': prev_tenants,
            },
            'payments': list(recent_payments),
            'expenses': list(recent_expenses),
            'organization': {
                'is_demo': org.is_demo if org else False,
                'demo_days_left': demo_days_left,
            }
        })


class PropertyViewSet(AuditViewSetMixin, DeleteMixin, ModelViewSet):
    queryset = Property.objects.all()
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        return PropertySerializer

    def get_queryset(self):
        user = self.request.user
        org = user.organization

        if user.is_staff:
            return Property.objects.all()
        return Property.objects.filter(organization=org)

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)

    def perform_update(self, serializer):
        serializer.save()

    @action(detail=True, methods=['get'])
    def blocks(self, request, pk=None):
        property_obj = self.get_object()
        blocks = property_obj.blocks.all()
        serializer = BlockSerializer(blocks, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def units(self, request, pk=None):
        property_obj = self.get_object()
        units = property_obj.units.all()
        serializer = UnitSerializer(units, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def tenants(self, request, pk=None):
        property_obj = self.get_object()
        tenants = Tenant.objects.filter(unit__property=property_obj)
        serializer = TenantSerializer(tenants, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def reports(self, request, pk=None):
        property_obj = self.get_object()
        reports = property_obj.property_reports.all()
        serializer = ReportSerializer(reports, many=True)
        return Response(serializer.data)


class BlockViewSet(AuditViewSetMixin, DeleteMixin, ModelViewSet):
    queryset = Block.objects.all()
    serializer_class = BlockSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        org = self.request.user.organization
        qs = Block.objects.filter(property__organization=org)
        
        property_id = self.request.query_params.get('property')
        if property_id:
            qs = qs.filter(property__id=property_id)
        
        return qs

    def perform_create(self, serializer):
        property_id = self.request.data.get('property')
        if not property_id:
            raise PermissionDenied('You must specify a property for this block.')

        property_obj = get_object_or_404(Property, id=property_id)
        serializer.save(property=property_obj)

    def perform_update(self, serializer):
        instance = serializer.instance
        if 'property' in serializer.validated_data and serializer.validated_data['property'] != instance.property:
            raise PermissionDenied('You cannot change the property this block belongs to.')

        serializer.save()


class UnitViewSet(AuditViewSetMixin, DeleteMixin, ModelViewSet):
    serializer_class = UnitSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        org = user.organization
        queryset = Unit.objects.all()
        is_available = self.request.query_params.get('is_available')
        if is_available is not None:
            queryset = queryset.filter(is_available=is_available.lower() == 'true')

        if not user.is_staff:
            queryset = queryset.filter(property__organization=org)

        property_id = self.request.query_params.get('property')
        block_id = self.request.query_params.get('block')

        if property_id:
            queryset = queryset.filter(property_id=property_id)

        if block_id:
            queryset = queryset.filter(block_id=block_id)

        return queryset

    def perform_create(self, serializer):
        property_id = self.request.data.get('property')
        if not property_id:
            raise PermissionDenied('You must specify a property for this unit.')

        property_obj = get_object_or_404(Property, id=property_id)
        if not (property_obj.organization == self.request.user.organization):
            raise PermissionDenied('You do not manage this property.')

        serializer.save(property=property_obj)

    def perform_update(self, serializer):
        instance = serializer.instance
        if 'property' in serializer.validated_data and serializer.validated_data['property'] != instance.property:
            raise PermissionDenied('You cannot change the property this unit belongs to.')

        new_availability = serializer.validated_data.get('is_available')
        if new_availability is True and not instance.is_available:
            Tenant.objects.filter(unit=instance, is_active=True).update(unit=None)

        serializer.save()


class BulkCreateUnitsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        units_data = request.data.get('units', [])
        property_id = request.data.get('property_id')
        block_id = request.data.get('block_id') or None

        if not units_data or not property_id:
            return Response(
                {'detail': 'property_id and units are required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                created = []
                for u in units_data:
                    unit = Unit.objects.create(
                        property_id=property_id,
                        block_id=block_id,
                        code=u.get('code'),
                        rooms=u.get('rooms'),
                        price=u['price'],
                        condition=u.get('condition', 'good'),
                        is_available=u.get('is_available', True),
                        last_inspection_date=u.get('last_inspection_date') or None,
                        notes=u.get('notes') or None,
                    )
                    created.append(str(unit.id))

        except Exception as e:
            return Response(
                {'detail': 'Failed to save units. No changes were made.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response({'created': len(created), 'ids': created}, status=status.HTTP_201_CREATED)


class TenantViewset(AuditViewSetMixin, DeleteMixin, ModelViewSet):
    serializer_class = TenantSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        org = user.organization
        queryset = Tenant.objects.all()

        if not user.is_staff:
            queryset = queryset.filter(
                Q(unit__property__organization=org) |
                Q(unit__isnull=True)
            )

        property_id = self.request.query_params.get('property')
        block_id = self.request.query_params.get('block')
        unit_id = self.request.query_params.get('unit')

        if property_id:
            queryset = queryset.filter(unit__property_id=property_id)

        if block_id:
            queryset = queryset.filter(unit__block_id=block_id)

        if unit_id:
            queryset = queryset.filter(unit_id=unit_id)

        return queryset

    def perform_create(self, serializer):
        unit_id = self.request.data.get('unit')

        if not unit_id:
            serializer.save(unit=None)
            return

        unit_obj = get_object_or_404(Unit, id=unit_id)
        serializer.save(unit=unit_obj)

        unit_obj.is_available = False
        unit_obj.save(update_fields=['is_available'])

    def perform_update(self, serializer):
        instance = serializer.instance
        old_unit = instance.unit
        new_unit = serializer.validated_data.get('unit', old_unit)

        if new_unit and not (new_unit.property.organization == self.request.user.organization):
            raise PermissionDenied('You do not manage the property for this unit.')

        serializer.save()

        if new_unit != old_unit:
            if old_unit:
                old_unit.is_available = True
                old_unit.save(update_fields=['is_available'])
            if new_unit:
                new_unit.is_available = False
                new_unit.save(update_fields=['is_available'])

    def perform_destroy(self, instance):
        unit = instance.unit
        instance.delete()
        if unit:
            unit.is_available = True
            unit.save(update_fields=['is_available'])


class TenantBulkImportView(APIView):
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        file = request.FILES.get('file')
        if not file:
            return Response({'error': 'No file uploaded.'}, status=400)

        try:
            if file.name.endswith('.csv'):
                df = pd.read_csv(file)
            elif file.name.endswith(('.xls', '.xlsx')):
                df = pd.read_excel(file)
            else:
                return Response({'error': 'Unsupported file format. Use CSV or XLSX.'}, status=400)
        except Exception as e:
            return Response({'error': f'Failed to read file: {str(e)}'}, status=400)

        df = df.where(pd.notnull(df), None)

        created, updated, errors = [], [], []

        for idx, row in df.iterrows():
            data = row.to_dict()

            tenant = Tenant.objects.filter(phone_number=data.get('phone_number')).first()
            serializer = TenantSerializer(instance=tenant, data=data)

            if serializer.is_valid():
                obj = serializer.save()
                if tenant:
                    updated.append(str(obj.id))
                else:
                    created.append(str(obj.id))
            else:
                errors.append({'row': idx + 1, 'errors': serializer.errors})

        return Response({'created': len(created), 'updated': len(updated), 'errors': errors}, status=status.HTTP_200_OK)


class ReportViewset(AuditViewSetMixin, DeleteMixin, ModelViewSet):
    serializer_class = ReportSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        org = user.organization
        queryset = Report.objects.all()

        if not user.is_staff:
            queryset = queryset.filter(property__organization=org)

        property_id = self.request.query_params.get('property')
        unit_id = self.request.query_params.get('unit')
        status_param = self.request.query_params.get('status')
        priority = self.request.query_params.get('priority')

        if property_id:
            queryset = queryset.filter(property_id=property_id)

        if unit_id:
            queryset = queryset.filter(unit_id=unit_id)

        if status_param:
            queryset = queryset.filter(status=status_param)

        if priority:
            queryset = queryset.filter(priority_level=priority)

        return queryset

    def perform_create(self, serializer):
        property_id = self.request.data.get('property')
        unit_id = self.request.data.get('unit')

        if not property_id:
            raise ValidationError('Property is required.')

        property_obj = get_object_or_404(Property, id=property_id)
        if not (property_obj.organization == self.request.user.organization):
            raise PermissionDenied('You do not manage this property.')

        unit_obj = None
        if unit_id:
            unit_obj = get_object_or_404(Unit, id=unit_id)
            if unit_obj.property_id != property_obj.id:
                raise ValidationError('Unit does not belong to the selected property.')

        serializer.save(property=property_obj, unit=unit_obj)

    def perform_update(self, serializer):
        instance = serializer.instance
        property_obj = serializer.validated_data.get('property', instance.property)
        unit_obj = serializer.validated_data.get('unit', instance.unit)

        if not (property_obj.organization == self.request.user.organization):
            raise PermissionDenied('You do not manage the property for this report.')

        if unit_obj and unit_obj.property != property_obj:
            raise ValidationError('Unit does not belong to the selected property.')

        serializer.save()


class ExpenseViewset(AuditViewSetMixin, DeleteMixin, ModelViewSet):
    serializer_class = ExpenseSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        org = user.organization
        queryset = Expense.objects.all()

        if not user.is_staff:
            queryset = queryset.filter(property__organization=org)

        property_id = self.request.query_params.get("property")
        report_id = self.request.query_params.get("report")
        category = self.request.query_params.get("category")
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")

        if property_id:
            queryset = queryset.filter(property_id=property_id)

        if report_id:
            queryset = queryset.filter(report_id=report_id)

        if category:
            queryset = queryset.filter(category=category)

        if date_from:
            queryset = queryset.filter(date_incurred__gte=date_from)

        if date_to:
            queryset = queryset.filter(date_incurred__lte=date_to)

        return queryset

    def perform_create(self, serializer):
        property_id = self.request.data.get("property")
        report_id = self.request.data.get("report")

        if not property_id and not report_id:
            raise ValidationError("Either 'property' or 'report' must be provided.")

        property_obj = None
        if property_id:
            property_obj = get_object_or_404(Property, id=property_id)

        report_obj = None
        if report_id:
            report_obj = get_object_or_404(Report, id=report_id)

            if not property_obj:
                property_obj = report_obj.property

            if property_obj.id != report_obj.property_id:
                raise ValidationError("The selected report does not belong to the provided property.")

        serializer.save(property=property_obj, report=report_obj)

    def perform_update(self, serializer):
        instance = serializer.instance

        property_obj = serializer.validated_data.get("property", instance.property)
        report_obj = serializer.validated_data.get("report", instance.report)

        if not (property_obj.manager == self.request.user):
            raise PermissionDenied("You do not manage this property.")

        if report_obj and report_obj.property != property_obj:
            raise ValidationError("The selected report does not belong to the chosen property.")

        serializer.save()


class TenantPaymentViewset(AuditViewSetMixin, DeleteMixin, ModelViewSet):
    serializer_class = TenantPaymentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        org = user.organization
        queryset = TenantPayment.objects.all()

        if user.is_staff:
            return queryset
        return queryset.filter(Q(unit__property__organization=org))

    def perform_create(self, serializer):
        user = self.request.user
        org = user.organization
        unit_id = self.request.data.get('unit')

        if not unit_id:
            raise PermissionDenied('A unit must be specified for a payment.')

        unit_obj = get_object_or_404(Unit, id=unit_id)

        if unit_obj.property.organization != org:
            raise PermissionDenied("You do not manage this unit’s organization.")

        serializer.save(unit=unit_obj)

    def perform_update(self, serializer):
        user = self.request.user
        instance = serializer.instance

        new_unit = serializer.validated_data.get('unit', instance.unit)

        if new_unit.property.manager != user:
            raise PermissionDenied("You do not manage this unit’s property.")

        serializer.save()


class TenantTransactionViewset(AuditViewSetMixin, ModelViewSet):
    serializer_class = TenantTransactionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        org = user.organization
        queryset = TenantTransaction.objects.select_related('payment__unit__property')

        if not user.is_staff:
            queryset = queryset.filter(payment__unit__property__organization=org)

        status = self.request.query_params.get('status')
        if status:
            queryset = queryset.filter(status=status)

        return queryset


class OrganizationPlanViewset(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user
        org = user.organization

        if user.role != 'manager':
            return Response({'detail': 'Access restricted to managers.'}, status=status.HTTP_403_FORBIDDEN)

        if not org:
            return Response({'detail': 'No organization found.'}, status=status.HTTP_404_NOT_FOUND)

        subscription = getattr(org, 'subscription', None)
        if not subscription:
            return Response({'detail': 'No subscription found.'}, status=status.HTTP_404_NOT_FOUND)

        receipts = Receipt.objects.filter(organization=org).order_by('-created_at').values('id', 'amount', 'created_at')

        data = {
            'plan': {
                'name': subscription.plan.name,
                'price': subscription.plan.base_rate,
                'status': subscription.status,
                'trial_ends_at': subscription.trial_ends_at,
                'next_billing_date': subscription.current_period_end,
            },
            'receipts': list(receipts),
        }

        return Response(data, status=status.HTTP_200_OK)


class SMSMessageSettingsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def put(self, request, *args, **kwargs):
        user = request.user
        account = user.account

        templates_payload = request.data.get('templates', [])
        saved_templates = []

        for item in templates_payload:
            template_id = item.get('id')
            is_active = item.get('is_active', True)
            new_text = item.get('text')
            new_label = item.get('label')

            try:
                customer_template = SMSMessage.objects.get(id=template_id, account=account)
                serializer = SMSMessageSerializer(customer_template, data=item, partial=True)
                serializer.is_valid(raise_exception=True)
                serializer.save()
                saved_templates.append(serializer.data)
                continue
            except SMSMessage.DoesNotExist:
                pass

            try:
                system_template = SMSMessageTemplate.objects.get(id=template_id)
                cloned = SMSMessage.objects.create(
                    account=account,
                    label=new_label or system_template.label,
                    text=new_text or system_template.text,
                    is_active=is_active,
                )
                saved_templates.append(SMSMessageSerializer(cloned).data)
                continue
            except SMSMessageTemplate.DoesNotExist:
                pass

            serializer = SMSMessageSerializer(data=item)
            serializer.is_valid(raise_exception=True)
            serializer.save(account=account)

            saved_templates.append(serializer.data)

        return Response({'message': 'SMS template settings updated successfully.', 'templates': saved_templates})


class InitiateSubscriptionPaymentView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        receipt_id = request.data.get('receipt_id')
        phone_number = request.data.get('phone_number')
        
        if not receipt_id or not phone_number:
            return Response({'error': 'receipt_id and phone_number are required'}, status=status.HTTP_400_BAD_REQUEST)
        
        phone_number = phone_number.strip().replace('+', '')
        if not phone_number.startswith('254') or len(phone_number) != 12:
            return Response({'error': 'Invalid phone number format. Use 254XXXXXXXXX'}, status=status.HTTP_400_BAD_REQUEST)
        
        receipt = get_object_or_404(Receipt, id=receipt_id)
        if receipt.account.user != request.user:
            return Response({'error': 'You do not have permission to pay this receipt'}, status=status.HTTP_403_FORBIDDEN)
        
        if receipt.status == 'paid':
            return Response({'error': 'This receipt has already been paid'}, status=status.HTTP_400_BAD_REQUEST)
        
        existing_payment = SubscriptionPayment.objects.filter(receipt=receipt, status='pending').first()
        
        if existing_payment:
            return Response({'error': 'There is already a pending payment for this receipt', 'payment_ref': existing_payment.payment_ref}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            with transaction.atomic():
                payment_ref = generate_payment_ref()
                
                payment = SubscriptionPayment.objects.create(
                    account=receipt.account,
                    initiated_by=request.user,
                    amount=receipt.total_amount,
                    payment_method='mpesa',
                    payment_ref=payment_ref,
                    currency='KES',
                    status='pending',
                    receipt=receipt,
                    notes=f'Payment initiated for receipt {receipt.receipt_number}'
                )
                
                idempotency_key = f"SUB_{payment_ref}"
                
                mpesa_transaction = MpesaSubscriptionTransaction.objects.create(
                    payment=payment,
                    phone_number=phone_number,
                    amount=receipt.total_amount,
                    idempotency_key=idempotency_key,
                    status='pending'
                )
                
                try:
                    stk_response = self.send_stk_push(
                        phone_number=phone_number,
                        amount=receipt.total_amount,
                        account_reference=payment_ref,
                        transaction_desc=f'Subscription payment for {receipt.receipt_number}'
                    )
                    
                    mpesa_transaction.callback_data = {
                        'stk_push_request': stk_response,
                        'timestamp': timezone.now().isoformat()
                    }
                    mpesa_transaction.save()
                    
                    if not stk_response.get('success'):
                        payment.status = 'failed'
                        payment.notes = f"STK push failed: {stk_response.get('error')}"
                        payment.save()
                        
                        mpesa_transaction.status = 'failed'
                        mpesa_transaction.failure_reason = stk_response.get('error')
                        mpesa_transaction.save()
                        
                        return Response({'error': 'Failed to initiate M-Pesa payment', 'details': stk_response.get('error')}, status=status.HTTP_400_BAD_REQUEST)
                    
                except Exception as e:
                    payment.status = 'failed'
                    payment.notes = f"STK push error: {str(e)}"
                    payment.save()
                    
                    mpesa_transaction.status = 'failed'
                    mpesa_transaction.failure_reason = str(e)
                    mpesa_transaction.save()
                    
                    return Response({'error': 'Failed to initiate M-Pesa payment', 'details': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
                return Response(
                    {
                        'success': True,
                        'message': 'Payment initiated successfully. Please check your phone for M-Pesa prompt.',
                        'payment_ref': payment_ref,
                        'amount': float(receipt.total_amount),
                        'phone_number': phone_number,
                        'receipt_number': receipt.receipt_number
                    },
                    status=status.HTTP_201_CREATED
                )
                
        except Exception as e:
            return Response({'error': 'An error occurred while processing your request', 'details': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PaymentStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, payment_ref):
        payment = get_object_or_404(SubscriptionPayment, payment_ref=payment_ref)
        
        if payment.account.user != request.user:
            return Response({'error': 'You do not have permission to view this payment'}, status=status.HTTP_403_FORBIDDEN)
        
        mpesa_transaction = MpesaSubscriptionTransaction.objects.filter(payment=payment).first()
        
        return Response({'status': payment.status,})


class MpesaSubscriptionCallbackView(APIView):
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
        try:
            logger.info(f"M-Pesa callback received: {request.data}")
            callback_body = request.data.get('Body', {})
            stk_callback = callback_body.get('stkCallback', {})
            
            if not stk_callback:
                logger.error("Invalid callback structure - missing stkCallback")
                return Response({'ResultCode': 1, 'ResultDesc': 'Invalid callback structure'}, status=status.HTTP_400_BAD_REQUEST)
            
            merchant_request_id = stk_callback.get('MerchantRequestID')
            checkout_request_id = stk_callback.get('CheckoutRequestID')
            result_code = stk_callback.get('ResultCode')
            result_desc = stk_callback.get('ResultDesc')
            callback_metadata = stk_callback.get('CallbackMetadata', {})
            
            idempotency_key = f"{merchant_request_id}_{checkout_request_id}"
            
            existing_transaction = MpesaSubscriptionTransaction.objects.filter(
                callback_data__stkCallback__MerchantRequestID=merchant_request_id,
                callback_data__stkCallback__CheckoutRequestID=checkout_request_id,
                processed_at__isnull=False
            ).first()
            
            if existing_transaction:
                logger.info(f"Duplicate callback detected for {checkout_request_id}, ignoring")
                return Response({'ResultCode': 0, 'ResultDesc': 'Duplicate callback, already processed'}, status=status.HTTP_200_OK)
            
            mpesa_transaction = MpesaSubscriptionTransaction.objects.filter(callback_data__stk_push_request__CheckoutRequestID=checkout_request_id).first()
            if not mpesa_transaction:
                logger.error(f"Transaction not found for CheckoutRequestID: {checkout_request_id}")
                return Response({'ResultCode': 1, 'ResultDesc': 'Transaction not found'}, status=status.HTTP_404_NOT_FOUND)
            
            with transaction.atomic():
                mpesa_transaction.callback_data = request.data
                mpesa_transaction.processed_at = timezone.now()
                
                if result_code == 0:
                    metadata_items = callback_metadata.get('Item', [])
                    metadata_dict = {item['Name']: item.get('Value') for item in metadata_items}
                    
                    mpesa_receipt = metadata_dict.get('MpesaReceiptNumber')
                    amount_paid = Decimal(str(metadata_dict.get('Amount', 0)))
                    phone_number = str(metadata_dict.get('PhoneNumber', ''))
                    transaction_date = metadata_dict.get('TransactionDate')
                    
                    mpesa_transaction.mpesa_code = mpesa_receipt
                    mpesa_transaction.amount = amount_paid
                    mpesa_transaction.phone_number = phone_number
                    mpesa_transaction.status = 'success'
                    mpesa_transaction.save()
                    
                    payment = mpesa_transaction.payment
                    if payment:
                        payment.status = 'success'
                        payment.payment_date = timezone.now()
                        payment.notes = f"Payment successful. M-Pesa Code: {mpesa_receipt}"
                        payment.save()
                        
                        receipt = payment.receipt
                        if receipt:
                            receipt.status = 'paid'
                            receipt.paid_date = timezone.now().date()
                            receipt.save()
                            
                            account = receipt.account
                            if account:
                                from dateutil.relativedelta import relativedelta
                                account.next_billing_date = account.next_billing_date + relativedelta(months=1)
                                account.save()
                            
                            logger.info(f"Payment successful: {mpesa_receipt} for receipt {receipt.receipt_number}")
                    
                else:
                    mpesa_transaction.status = 'failed'
                    mpesa_transaction.failure_reason = result_desc
                    mpesa_transaction.save()
                    
                    payment = mpesa_transaction.payment
                    if payment:
                        payment.status = 'failed'
                        payment.notes = f"Payment failed: {result_desc}"
                        payment.save()
                    
                    logger.warning(f"Payment failed: {result_desc} for CheckoutRequestID: {checkout_request_id}")
            
            return Response({'ResultCode': 0, 'ResultDesc': 'Callback processed successfully'}, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error processing M-Pesa callback: {str(e)}", exc_info=True)
            return Response({'ResultCode': 1, 'ResultDesc': f'Internal server error: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class RentPaymentCallbackView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        data = request.data

        paybill = data.get("BusinessShortCode")
        amount = data.get("TransAmount")
        mpesa_code = data.get("TransID")
        msisdn = data.get("MSISDN")
        account_reference = data.get("BillRefNumber")   # This is Unit.unique_ref
        trans_time = data.get("TransTime")

        try:
            pay_config = PaymentsConfiguration.objects.get(paybill_no=paybill)
        except PaymentsConfiguration.DoesNotExist:
            return Response({"ResultCode": 1, "ResultDesc": "Unknown Paybill"}, status=status.HTTP_400_BAD_REQUEST)

        account = pay_config.account

        unit = Unit.objects.filter(unique_ref=account_reference).first()

        if not unit:
            if not pay_config.allow_unmatched_payments:
                return Response({"ResultCode": 1, "ResultDesc": "Invalid Reference"}, status=status.HTTP_400_BAD_REQUEST)

            payment = TenantPayment.objects.create(
                tenant=None,
                unit=None,
                amount=Decimal(amount),
                payment_date=timezone.now(),
                payment_method="mpesa",
                payment_ref=mpesa_code,
                currency="KES",
                purpose="rent",
                status="pending",
                notes=f"Unmatched Mpesa payment. Reference used: {account_reference}"
            )

            TenantTransaction.objects.create(
                payment=payment,
                phone_number=msisdn,
                amount=Decimal(amount),
                mpesa_code=mpesa_code,
                status="pending",
            )

            return Response({"ResultCode": 0, "ResultDesc": "Accepted"}, status=200)

        tenant = Tenant.objects.filter(unit=unit, is_active=True).first()

        payment = TenantPayment.objects.create(
            tenant=tenant,
            unit=unit,
            amount=Decimal(amount),
            payment_date=timezone.now(),
            payment_method="mpesa",
            payment_ref=mpesa_code,
            currency="KES",
            purpose="rent",
            status="success",
            notes=f"C2B payment received via Paybill {paybill}"
        )

        TenantTransaction.objects.create(
            payment=payment,
            phone_number=msisdn,
            amount=Decimal(amount),
            mpesa_code=mpesa_code,
            status="success",
        )

        return Response({"ResultCode": 0, "ResultDesc": "Accepted"}, status=200)