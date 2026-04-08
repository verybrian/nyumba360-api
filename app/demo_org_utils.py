import uuid
from django.db import transaction
from django.apps import apps
from django.utils import timezone
from datetime import timedelta
from typing import Dict, Any, Optional

from app.models import Organization, Property, Block, Unit, Tenant, Report, Expense, TenantPayment, TenantTransaction, Receipt

def get_template_organization():
    Organization = apps.get_model('app', 'Organization')
    return Organization.objects.filter(is_template=True).first()


def copy_organization_data(template_org, target_org, user):
    """
    Copy all data from a template organization to a target organization.
    """
    id_mapping = {}
    copy_stats = {}
    
    models_to_copy = [
        'Property',
        'Block',
        'Unit',
        'Tenant',
        'TenantPayment',
        'TenantTransaction',
        'Report',
        'Expense',
        'Receipt',
    ]
    
    with transaction.atomic():
        for model_name in models_to_copy:
            try:
                Model = apps.get_model('app', model_name)
            except LookupError:
                continue
            
            if model_name == 'Block':
                property_ids = list(id_mapping.get('Property', {}).keys())
                records = Model.objects.filter(property_id__in=property_ids)

            elif model_name == 'Unit':
                property_ids = list(id_mapping.get('Property', {}).keys())
                records = Model.objects.filter(property_id__in=property_ids)

            elif model_name == 'Tenant':
                unit_ids = list(id_mapping.get('Unit', {}).keys())
                records = Model.objects.filter(unit_id__in=unit_ids)

            elif model_name == 'Report':
                property_ids = list(id_mapping.get('Property', {}).keys())
                records = Model.objects.filter(property_id__in=property_ids)

            elif model_name == 'Expense':
                property_ids = list(id_mapping.get('Property', {}).keys())
                records = Model.objects.filter(property_id__in=property_ids)

            elif model_name in ['TenantPayment', 'TenantTransaction']:
                if hasattr(Model, 'tenant'):
                    tenant_ids = list(id_mapping.get('Tenant', {}).keys())
                    records = Model.objects.filter(tenant_id__in=tenant_ids)
                elif hasattr(Model, 'unit'):
                    unit_ids = list(id_mapping.get('Unit', {}).keys())
                    records = Model.objects.filter(unit_id__in=unit_ids)
                else:
                    records = Model.objects.none()

            elif model_name == 'Receipt':
                records = Model.objects.filter(organization=template_org) if hasattr(Model, 'organization') else Model.objects.none()

            elif hasattr(Model, 'organization'):
                records = Model.objects.filter(organization=template_org)

            else:
                records = Model.objects.none()
            
            copied_count = 0
            model_id_mapping = {}
            
            for record in records:
                old_id = record.id
                
                record.pk = None
                record.id = uuid.uuid4()
                
                if hasattr(record, 'organization'):
                    record.organization = target_org
                
                if model_name == 'Block' and record.property_id:
                    record.property_id = id_mapping.get('Property', {}).get(record.property_id)
                
                if model_name == 'Unit':
                    if record.property_id:
                        record.property_id = id_mapping.get('Property', {}).get(record.property_id)
                    if record.block_id:
                        record.block_id = id_mapping.get('Block', {}).get(record.block_id)
                
                if model_name == 'Tenant' and record.unit_id:
                    record.unit_id = id_mapping.get('Unit', {}).get(record.unit_id)
                
                if hasattr(record, 'tenant_id') and record.tenant_id:
                    record.tenant_id = id_mapping.get('Tenant', {}).get(record.tenant_id)
                
                if hasattr(record, 'unit_id') and record.unit_id and model_name != 'Tenant':
                    record.unit_id = id_mapping.get('Unit', {}).get(record.unit_id)
                
                if hasattr(record, 'property_id') and record.property_id and model_name not in ['Block', 'Unit']:
                    record.property_id = id_mapping.get('Property', {}).get(record.property_id)

                if model_name == 'Expense' and hasattr(record, 'report_id') and record.report_id:
                    record.report_id = id_mapping.get('Report', {}).get(record.report_id)
                
                if hasattr(record, 'unique_ref'):
                    record.unique_ref = None

                if hasattr(record, 'custom_id'):
                    record.custom_id = ''
                
                if hasattr(record, 'created_by'):
                    record.created_by = None
                if hasattr(record, 'updated_by'):
                    record.updated_by = None
                
                if hasattr(record, 'created_at'):
                    record.created_at = timezone.now()
                if hasattr(record, 'updated_at'):
                    record.updated_at = timezone.now()
                
                record.save()
                
                model_id_mapping[old_id] = record.id
                copied_count += 1
            
            id_mapping[model_name] = model_id_mapping
            copy_stats[model_name] = copied_count
    
    return copy_stats


def clear_demo_data(organization):
    """
    Clear all demo data from an organization and set is_demo to False.
    """
    if not organization.is_demo:
        raise ValueError("Organization is not a demo organization")

    delete_stats = {}

    with transaction.atomic():
        Property = apps.get_model('app', 'Property')
        Unit = apps.get_model('app', 'Unit')
        Tenant = apps.get_model('app', 'Tenant')
        Report = apps.get_model('app', 'Report')

        property_ids = Property.objects.filter(organization=organization).values_list('id', flat=True)
        unit_ids = Unit.objects.filter(property_id__in=property_ids).values_list('id', flat=True)
        tenant_ids = Tenant.objects.filter(unit_id__in=unit_ids).values_list('id', flat=True)
        report_ids = Report.objects.filter(property_id__in=property_ids).values_list('id', flat=True)
        payment_ids = TenantPayment.objects.filter(tenant_id__in=tenant_ids).values_list('id', flat=True)

        deletion_plan = [
            ('Receipt',           {'organization': organization}),
            ('TenantTransaction', {'payment_id__in': payment_ids}),
            ('TenantPayment',     {'tenant_id__in': tenant_ids}),
            ('Expense',           {'property_id__in': property_ids}),
            ('Report',            {'property_id__in': property_ids}),
            ('Tenant',            {'unit_id__in': unit_ids}),
            ('Unit',              {'property_id__in': property_ids}),
            ('Block',             {'property_id__in': property_ids}),
            ('Property',          {'organization': organization}),
        ]

        for model_name, filters in deletion_plan:
            try:
                Model = apps.get_model('app', model_name)
            except LookupError:
                continue

            deleted_count, _ = Model.objects.filter(**filters).delete()
            delete_stats[model_name] = deleted_count

        organization.is_demo = False
        organization.demo_expires_at = None
        organization.save(update_fields=['is_demo', 'demo_expires_at'])

    return delete_stats


def create_demo_organization(user, template_org=None):
    """
    Create a new demo organization with copied data from a template.
    """
    Organization = apps.get_model('app', 'Organization')
    
    if template_org is None:
        template_org = get_template_organization()
    
    if not template_org:
        raise ValueError("No template organization available")
    
    demo_org = Organization.objects.create(
        status='active',
        is_demo=True,
        demo_expires_at=timezone.now() + timedelta(days=7)
    )
    
    copy_stats = copy_organization_data(template_org, demo_org, user)
    
    return demo_org, copy_stats