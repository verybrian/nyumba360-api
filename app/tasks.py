"""
Celery tasks for demo organization management.
Configure celery beat to run cleanup_expired_demos_task daily.
"""
from celery import shared_task
from django.utils import timezone
from django.db import transaction
import logging

from .models import Organization
from .demo_org_utils import clear_demo_data

logger = logging.getLogger(__name__)


@shared_task
def cleanup_expired_demos_task():
    """
    Celery task to clean up expired demo organizations.
    Should be scheduled to run daily via celery beat.
    
    Example celery beat configuration:
    
    CELERY_BEAT_SCHEDULE = {
        'cleanup-expired-demos': {
            'task': 'your_app.tasks.cleanup_expired_demos_task',
            'schedule': crontab(hour=2, minute=0),  # Run at 2 AM daily
        },
    }
    """
    now = timezone.now()
    
    # Find all expired demo organizations
    expired_demos = Organization.objects.filter(
        is_demo=True,
        demo_expires_at__lte=now
    )
    
    count = expired_demos.count()
    
    if count == 0:
        logger.info('No expired demo organizations found')
        return {'processed': 0, 'success': 0, 'errors': 0}
    
    logger.info(f'Found {count} expired demo organization(s) to clean up')
    
    success_count = 0
    error_count = 0
    
    for org in expired_demos:
        try:
            delete_stats = clear_demo_data(org)
            total_deleted = sum(delete_stats.values())
            logger.info(
                f'Cleared demo data for: {org.name} (ID: {org.id}) - {total_deleted} records deleted'
            )
            success_count += 1
            
        except Exception as e:
            logger.error(f'Error processing {org.name} (ID: {org.id}): {str(e)}', exc_info=True)
            error_count += 1
    
    result = {
        'processed': count,
        'success': success_count,
        'errors': error_count,
        'timestamp': now.isoformat()
    }
    
    logger.info(f'Cleanup completed: {success_count} successful, {error_count} errors')
    
    return result


@shared_task
def send_demo_expiry_reminder(organization_id):
    """
    Send a reminder email to users when their demo is about to expire.
    Call this 1-2 days before expiry.
    """
    try:
        org = Organization.objects.get(id=organization_id, is_demo=True)
        
        # Get all users in this organization
        users = org.user_set.all()  # Adjust based on your User model relationship
        
        for user in users:
            # Send email notification
            # You'll need to implement your email sending logic here
            # send_mail(
            #     subject='Your demo will expire soon',
            #     message=f'Hi {user.name}, your demo organization will expire on {org.demo_expires_at}',
            #     from_email='noreply@yourapp.com',
            #     recipient_list=[user.email],
            # )
            pass
        
        logger.info(f'Sent expiry reminders for organization {org.id} to {users.count()} users')
        
    except Organization.DoesNotExist:
        logger.warning(f'Organization {organization_id} not found or not a demo')
    except Exception as e:
        logger.error(f'Error sending expiry reminder for org {organization_id}: {str(e)}', exc_info=True)


@shared_task
def schedule_demo_expiry_reminders():
    """
    Schedule reminder emails for demos expiring soon.
    Run this daily to check for demos expiring in 2 days.
    """
    from datetime import timedelta
    
    now = timezone.now()
    reminder_date = now + timedelta(days=2)
    
    # Find demos expiring in approximately 2 days
    demos_expiring_soon = Organization.objects.filter(
        is_demo=True,
        demo_expires_at__gte=reminder_date,
        demo_expires_at__lt=reminder_date + timedelta(days=1)
    )
    
    count = 0
    for org in demos_expiring_soon:
        send_demo_expiry_reminder.delay(str(org.id))
        count += 1
    
    logger.info(f'Scheduled {count} demo expiry reminder(s)')
    return {'scheduled': count}