import re
from rest_framework import serializers
from django.contrib.auth import authenticate
from .models import User, Organization, Property, Block, Unit, Tenant, Report, Expense, TenantPayment, TenantTransaction, SMSMessage, OrganizationPayment, OrganizationTransaction


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'name', 'email', 'phone', 'country', 'is_active']
        read_only_fields = ['id', 'phone']


class RegisterSerializer(serializers.ModelSerializer):
    pin = serializers.CharField(
        write_only=True,
        required=True,
        validators=[User.pin_validator]
    )

    class Meta:
        model = User
        fields = ['name', 'phone', 'assumed_country', 'pin']

    def normalize_phone(phone):
        p = re.sub(r'[^\d]', '', phone)
        
        if not p.startswith('0'):
            match = re.search(r'0\d+', p)
            if match:
                p = p[match.start():]
        
        return p

    def validate_phone(self, value):
        normalized = RegisterSerializer.normalize_phone(value)
        if User.objects.filter(phone=normalized).exists():
            raise serializers.ValidationError('A user with this phone already exists.')
        return normalized

    def create(self, validated_data):
        return User.objects.create_user(
            phone=validated_data['phone'],
            password=validated_data['pin'],
            name=validated_data.get('name'),
            assumed_country=validated_data.get('assumed_country'),
        )


class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField(required=True)
    pin = serializers.CharField(write_only=True, validators=[User.pin_validator])

    def normalize_phone(phone):
        p = re.sub(r'[^\d]', '', phone)
        
        if not p.startswith('0'):
            match = re.search(r'0\d+', p)
            if match:
                p = p[match.start():]
        
        return p

    def validate(self, attrs):
        identifier = attrs.get("identifier")
        pin = attrs.get("pin")

        if '@' in identifier:
            user = User.objects.filter(email=identifier).first()
        else:
            user = User.objects.filter(phone=LoginSerializer.normalize_phone(identifier)).first()

        if not user:
            raise serializers.ValidationError({'identifier': 'No account found with this phone or email.'})

        if not user.check_password(pin):
            raise serializers.ValidationError({'pin': 'Incorrect PIN.'})

        if not user.is_active:
            raise serializers.ValidationError({'identifier': 'This account has been disabled.'})

        attrs['user'] = user
        return attrs


class OrganizationStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = [
            'id',
            'name',
            'status',
            'is_demo',
            'is_template',
            'demo_expires_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields
 
 
class ClearDemoDataResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    organization_id = serializers.UUIDField()
    records_deleted = serializers.DictField(
        child=serializers.IntegerField(),
        help_text="Count of deleted records per model"
    )
    is_demo = serializers.BooleanField()
 


class PropertySerializer(serializers.ModelSerializer):
    block_count = serializers.IntegerField(source='blocks.count', read_only=True)
    unit_count = serializers.IntegerField(source='units.count', read_only=True)
    tenant_count = serializers.SerializerMethodField()

    def get_tenant_count(self, obj):
        return Tenant.objects.filter(unit__property=obj).count()

    class Meta:
        model = Property
        fields = ['id', 'name', 'notes', 'property_type', 'location', 'organization', 'block_count', 'unit_count', 'tenant_count', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class BlockSerializer(serializers.ModelSerializer):
    unit_count = serializers.IntegerField(source='units.count', read_only=True)
    vacant_count = serializers.SerializerMethodField()

    def get_vacant_count(self, obj):
        return obj.units.filter(is_available=True).count()

    class Meta:
        model = Block
        fields = ['id', 'name_or_code', 'unit_count', 'vacant_count', 'notes', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class UnitSerializer(serializers.ModelSerializer):
    property = serializers.PrimaryKeyRelatedField(queryset=Property.objects.all())
    block = serializers.PrimaryKeyRelatedField(queryset=Block.objects.all(), required=False, allow_null=True)

    class Meta:
        model = Unit
        fields = ['id', 'property', 'block', 'code', 'rooms', 'price', 'is_available', 'condition', 'last_inspection_date', 'notes', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class TenantSerializer(serializers.ModelSerializer):
    unit = serializers.PrimaryKeyRelatedField(queryset=Unit.objects.all(), required=False, allow_null=True)
    unit_code = serializers.CharField(source='unit.code', read_only=True)
    property_name = serializers.CharField(source='unit.property.name', read_only=True)

    class Meta:
        model = Tenant
        fields = ['id', 'unit', 'unit_code', 'property_name', 'name', 'id_number', 'phone_number',
                  'alt_phone_number', 'move_in_date', 'move_out_date', 'monthly_due_day',
                  'is_active', 'notes', 'created_at', 'updated_at']
        read_only_fields = ['id', 'unit_code', 'property_name', 'created_at', 'updated_at']


class ReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Report
        fields = '__all__'
        read_only_fields = ['id']


class ExpenseSerializer(serializers.ModelSerializer):
    property_name = serializers.CharField(source='property.name', read_only=True)

    class Meta:
        model = Expense
        fields = ['id', 'property', 'property_name', 'report', 'description', 'category',
                  'amount', 'date_incurred', 'attachment']
        read_only_fields = ['id', 'property_name']


class TenantTransactionSerializer(serializers.ModelSerializer):
    payment_ref = serializers.CharField(source='payment.payment_ref', read_only=True)
    payment_id = serializers.UUIDField(source='payment.id', read_only=True)

    class Meta:
        model = TenantTransaction
        fields = ['id', 'payment_id', 'payment_ref', 'phone_number', 'amount',
                  'payment_method', 'mpesa_code', 'transaction_date', 'status', 'notes']
        read_only_fields = ['id', 'payment_id', 'payment_ref']


class TenantPaymentSerializer(serializers.ModelSerializer):
    tenant_name = serializers.CharField(source='tenant.name', read_only=True)
    unit_code = serializers.CharField(source='unit.code', read_only=True)
    property_name = serializers.CharField(source='unit.property.name', read_only=True)

    class Meta:
        model = TenantPayment
        fields = ['id', 'custom_id', 'unit', 'tenant', 'unit_code', 'tenant_name', 'property_name', 'amount',
                  'payment_date', 'payment_method', 'purpose', 'status', 'payment_ref', 'created_at', 'updated_at']
        read_only_fields = ['id', 'unit_code', 'tenant_name', 'property_name', 'created_at', 'updated_at']


class SMSMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = SMSMessage
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']


class OrganizationPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationPayment
        fields = '__all__'
        read_only_fields = ['id', 'payment_date', 'payment_ref']


class OrganizationTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationTransaction
        fields = '__all__'
        read_only_fields = ['id', 'mpesa_code', 'idempotency_key', 'timestamp', 'status', 'processed_at']