import uuid
import random
from django.db import models
from django.core.validators import RegexValidator
from django.utils import timezone
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin


class UserManager(BaseUserManager):
    def create_user(self, phone, password=None, **extra_fields):
        if not phone:
            raise ValueError('Phone is required')
        user = self.model(phone=phone, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, phone, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(phone, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=30, null=True, blank=True)
    phone = models.CharField(max_length=15, unique=True)
    email = models.EmailField(unique=True, null=True, blank=True)
    assumed_country = models.CharField(max_length=30, null=True)
    country = models.CharField(max_length=20, null=True, blank=True)
    currency = models.CharField(max_length=5, null=True, default='KES')
    organization = models.ForeignKey('Organization', null=True, blank=True, on_delete=models.SET_NULL, related_name='members')
    role = models.CharField(max_length=10, choices=[
        ('manager', 'Manager'),
        ('staff', 'Staff'),
    ], null=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_paused = models.BooleanField(default=False)
    paused_at = models.DateTimeField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = 'phone'
    REQUIRED_FIELDS = []

    pin_validator = RegexValidator(
        regex=r'^\d{4}$',
        message='PIN must be exactly 4 digits.'
    )

    def __str__(self):
        return self.phone


class Organization(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=50, null=True)
    unique_ref = models.CharField(unique=True, null=True, blank=True)
    status = models.CharField(max_length=20, choices=[
        ('active', 'Active'),
        ('limited', 'Limited Access'),
        ('paused', 'Paused'),
    ], default='active')
    is_demo = models.BooleanField(default=False)
    demo_expires_at = models.DateTimeField(null=True)
    is_template = models.BooleanField(
        default=False, 
        help_text='Template organizations are used as source for demo data'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class PaymentsConfiguration(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.SET_NULL, null=True)
    paybill_no = models.CharField(unique=True, null=True, blank=True)
    allow_unmatched_payments = models.BooleanField(default=True)


class Plan(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=50)
    base_rate = models.DecimalField(max_digits=10, decimal_places=2)


class Subscription(models.Model):
    organization = models.OneToOneField('Organization', on_delete=models.CASCADE, related_name='subscription')
    plan = models.ForeignKey('Plan', on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=[
        ('trial', 'Trial'),
        ('active', 'Active'),
        ('limited', 'Limited'),
        ('cancelled', 'Cancelled'),
    ], default='trial')
    trial_ends_at = models.DateField(null=True, blank=True)
    current_period_start = models.DateField(null=True, blank=True)
    current_period_end = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class UsageEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.SET_NULL, null=True)
    type = models.CharField(max_length=20, choices=[('sms', 'SMS')])
    unit_cost = models.DecimalField(max_digits=10, decimal_places=4)
    timestamp = models.DateTimeField(auto_now_add=True)

    @staticmethod
    def log_sms(organization):
        from decimal import Decimal
        SMS_COST = Decimal('1.0000')

        return UsageEvent.objects.create(organization=organization, type='sms', unit_cost=SMS_COST)


class Receipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.ForeignKey('OrganizationPayment', on_delete=models.SET_NULL, null=True)
    receipt_number = models.CharField(max_length=50, unique=True)
    organization = models.ForeignKey(Organization, on_delete=models.SET_NULL, null=True)
    generated_on = models.DateField(auto_now_add=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True, null=True)


class AuditModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='%(class)s_created')
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='%(class)s_updated')

    class Meta:
        abstract = True


class SMSMessageTemplate(AuditModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    label = models.CharField(max_length=100)
    text = models.TextField()

    class Meta:
        verbose_name = 'SMS Template'
        verbose_name_plural = 'SMS Templates'

    def __str__(self):
        return f'{self.label}'


# Customer-related Models Start


class Property(AuditModel):
    PROPERTY_TYPES = [
        ('home', 'Home'),
        ('apartment', 'Apartment Complex'),
        ('office', 'Office Space'),
        ('estate', 'Estate'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    notes = models.TextField(null=True, blank=True)
    property_type = models.CharField(max_length=20, choices=PROPERTY_TYPES)
    location = models.CharField(max_length=255, null=True, blank=True)
    organization = models.ForeignKey(Organization, on_delete=models.SET_NULL, null=True, related_name='properties')

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['-created_at']


class Block(AuditModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    property = models.ForeignKey(Property, on_delete=models.SET_NULL, null=True, related_name='blocks')
    name_or_code = models.CharField(max_length=50)
    notes = models.TextField(null=True, blank=True)

    def __str__(self):
        return f'{self.property.name} - {self.name_or_code}'


class Unit(AuditModel):
    CONDITION_CHOICES=[
        ('excellent', 'Excellent'),
        ('good', 'Good'),
        ('fair', 'Fair'),
        ('needs_repair', 'Needs Repair'),
        ('uninhabitable', 'Uninhabitable'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    property = models.ForeignKey(Property, on_delete=models.SET_NULL, null=True, related_name='units')
    block = models.ForeignKey(Block, on_delete=models.SET_NULL, null=True, related_name='units', blank=True)
    code = models.CharField(max_length=50, null=True)
    unique_ref = models.CharField(max_length=50, unique=True, null=True)
    rooms = models.IntegerField(null=True, blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    is_available = models.BooleanField(default=True)
    condition = models.CharField(max_length=20, choices=CONDITION_CHOICES, default='good')
    last_inspection_date = models.DateField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)

    def __str__(self):
        if self.block:
            return f'{self.property.name} - {self.block.name} - {self.code}'
        return f'{self.property.name} - {self.code}'


class Tenant(AuditModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    unit = models.ForeignKey(Unit, related_name='tenant', on_delete=models.SET_NULL, null=True, blank=True)
    name = models.CharField(max_length=100)
    phone_number = models.CharField(max_length=15, null=True)
    alt_phone_number = models.CharField(max_length=15, null=True, blank=True)
    id_number = models.CharField(max_length=10, null=True, blank=True)
    move_in_date = models.DateField(null=True, blank=True)
    move_out_date = models.DateField(null=True, blank=True)
    monthly_due_day = models.PositiveSmallIntegerField(default=1, help_text='Day of the month rent is due')
    is_active = models.BooleanField(default=True)
    notes = models.TextField(null=True, blank=True)

    def __str__(self):
        return f'{self.name} - {self.unit}'


class Report(AuditModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    property = models.ForeignKey(Property, on_delete=models.SET_NULL, null=True, related_name='property_reports')
    unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True, blank=True)
    title = models.CharField(max_length=255, null=True)
    occurred_at = models.DateField(null=True, blank=True)
    reporter = models.CharField(max_length=30, null=True, blank=True)
    reporter_phone = models.CharField(max_length=15, null=True, blank=True)
    relationship = models.CharField(max_length=100, null=True, blank=True)
    attachment = models.ImageField(upload_to='report_attachments/', null=True, blank=True)
    priority_level = models.CharField(max_length=20, choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High')], null=True)
    status = models.CharField(max_length=20, choices=[('open', 'Open'), ('resolved', 'Resolved')], null=True)


class Expense(AuditModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(Report, on_delete=models.SET_NULL, related_name='expenses', null=True, blank=True)
    property = models.ForeignKey(Property, on_delete=models.SET_NULL, null=True, related_name='property_expenses')
    description = models.CharField(max_length=150, null=True, blank=True)
    category = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        choices=[
            ('repair', 'Repair'),
            ('maintenance', 'Maintenance'),
            ('utility', 'Utility'),
            ('security', 'Security'),
            ('cleaning', 'Cleaning'),
            ('other', 'Other'),
        ]
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date_incurred = models.DateField()
    attachment = models.FileField(upload_to='expense_attachments/', null=True, blank=True)

    def save(self, *args, **kwargs):
        if self.report and not self.property:
            self.property = self.report.property
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Expense {self.id} - {self.amount}'


class TenantPayment(AuditModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    custom_id = models.CharField(max_length=6, blank=True, default='')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, null=True, blank=True)
    tenant = models.ForeignKey(Tenant, on_delete=models.SET_NULL, null=True, blank=True)
    unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True, blank=True)
    amount = models.DecimalField(decimal_places=2, max_digits=10, null=True)
    payment_date = models.DateTimeField(null=True)
    payment_method = models.CharField(choices=[('mpesa', 'Mpesa'), ('cash', 'Cash'), ('bank', 'Bank')], null=True)
    payment_ref = models.CharField(max_length=30, null=True, blank=True)
    currency = models.CharField(max_length=10, default='KES')
    purpose = models.CharField(max_length=15, choices=[('rent', 'Rent'), ('fine', 'Fine'), ('repairs', 'Repairs')], null=True)
    status = models.CharField(max_length=20, choices=[('pending', 'Pending'), ('success', 'Success'), ('failed', 'Failed')], default='pending')
    notes = models.TextField(null=True, blank=True)

    class Meta:
        verbose_name_plural = 'Tenant Payments'
        ordering = ['-payment_date']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'custom_id'], name='unique_payment_code_per_org')
        ]

    def save(self, *args, **kwargs):
        from app.utils import generate_payment_code

        if not self.custom_id:
            for _ in range(10):
                code = generate_payment_code()
                if not TenantPayment.objects.filter(
                    organization=self.organization,
                    custom_id=code
                ).exists():
                    self.custom_id = code
                    break
            else:
                raise ValueError("Could not generate a unique payment code.")

        super().save(*args, **kwargs)

    def __str__(self):
        tenant_name = self.tenant.name if self.tenant else 'Unknown Tenant'
        unit_code = self.unit.code if self.unit else 'Unknown Unit'
        amount_str = f'Ksh {self.amount}' if self.amount else 'Amount N/A'
        date_str = self.payment_date.strftime('%Y-%m-%d') if self.payment_date else 'Date N/A'
        return f'[{self.custom_id}] {amount_str} paid by {tenant_name}'


class TenantTransaction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.ForeignKey(TenantPayment, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    phone_number = models.CharField(max_length=15, null=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    mpesa_code = models.CharField(max_length=20, null=True, blank=True)
    transaction_date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=[('pending', 'Pending'), ('success', 'Success'), ('failed', 'Failed')], default='pending')
    notes = models.TextField(null=True, blank=True)
    
    class Meta:
        verbose_name_plural = 'Tenant Transactions'
        ordering = ['-transaction_date']
    
    def __str__(self):
        return f"{self.amount} via M-pesa on {self.transaction_date.strftime('%Y-%m-%d %H:%M')}"


class SMSMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.SET_NULL, null=True)
    label = models.CharField(max_length=100)  # e.g. 'Rent Reminder'
    text = models.TextField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.label}'


class SMSLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.SET_NULL, null=True)
    tenant = models.ForeignKey(Tenant, on_delete=models.SET_NULL, null=True, blank=True)
    phone = models.CharField(max_length=20)
    template = models.ForeignKey(SMSMessage, on_delete=models.SET_NULL, null=True, blank=True)  # Null when it's an ad-hoc message (bulk announcements)
    text = models.TextField()
    status = models.CharField(max_length=20, choices=[('pending', 'Pending'), ('sent', 'Sent'), ('failed', 'Failed')], default='pending')
    provider_message_id = models.CharField(max_length=100, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class OrganizationPayment(AuditModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.SET_NULL, null=True)
    initiated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    amount = models.DecimalField(decimal_places=2, max_digits=10, null=True)
    payment_method = models.CharField(choices=[('mpesa', 'Mpesa'), ('cash', 'Cash'), ('bank', 'Bank')], null=True)
    payment_ref = models.CharField(max_length=30, null=True, blank=True)
    currency = models.CharField(max_length=10, default='KES')
    purpose = models.CharField(max_length=20, choices = [('subscription', 'subscription'), ('tokens', 'tokens')], null=True)
    status = models.CharField(max_length=20, choices=[('pending', 'Pending'), ('success', 'Success'), ('failed', 'Failed')], default='pending')
    notes = models.TextField(null=True, blank=True)

    class Meta:
        verbose_name_plural = 'Organization Payments'
        ordering = ['-created_at']


class OrganizationTransaction(AuditModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.ForeignKey(OrganizationPayment, on_delete=models.SET_NULL, null=True)
    phone_number = models.CharField(max_length=15, null=True)
    mpesa_code = models.CharField(max_length=20, null=True, blank=True, unique=True)
    idempotency_key = models.CharField(max_length=100, unique=True, null=True, blank=True)
    status = models.CharField(max_length=20, choices=[('pending', 'Pending'), ('success', 'Success'), ('failed', 'Failed')], default='pending')
    failure_reason = models.TextField(null=True, blank=True)
    callback_data = models.JSONField(null=True, blank=True)
    
    class Meta:
        verbose_name_plural = 'Organization Transactions'
        ordering = ['-created_at']