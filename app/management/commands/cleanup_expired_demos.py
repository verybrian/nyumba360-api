"""
Management command to clean up expired demo organizations.
This should be run periodically (e.g., daily via cron or celery beat).

Usage:
    python manage.py cleanup_expired_demos
    python manage.py cleanup_expired_demos --dry-run
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction

from app.models import Organization
from app.demo_org_utils import clear_demo_data


class Command(BaseCommand):
    help = 'Clean up expired demo organizations by clearing their data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting',
        )
        parser.add_argument(
            '--delete-org',
            action='store_true',
            help='Delete the entire organization instead of just clearing data (use with caution)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        delete_org = options['delete_org']
        
        now = timezone.now()
        
        # Find all expired demo organizations
        expired_demos = Organization.objects.filter(
            is_demo=True,
            demo_expires_at__lte=now
        )
        
        count = expired_demos.count()
        
        if count == 0:
            self.stdout.write(self.style.SUCCESS('No expired demo organizations found'))
            return
        
        self.stdout.write(f'Found {count} expired demo organization(s)')
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN - No changes will be made'))
            for org in expired_demos:
                self.stdout.write(f'  - {org.name} (ID: {org.id}, Expired: {org.demo_expires_at})')
            return
        
        success_count = 0
        error_count = 0
        
        for org in expired_demos:
            try:
                if delete_org:
                    # Delete the entire organization and all related data
                    org_name = org.name
                    org_id = org.id
                    org.delete()
                    self.stdout.write(
                        self.style.SUCCESS(f'Deleted organization: {org_name} (ID: {org_id})')
                    )
                else:
                    # Clear demo data but keep the organization
                    delete_stats = clear_demo_data(org)
                    total_deleted = sum(delete_stats.values())
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'Cleared demo data for: {org.name} (ID: {org.id}) - {total_deleted} records deleted'
                        )
                    )
                success_count += 1
                
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'Error processing {org.name} (ID: {org.id}): {str(e)}')
                )
                error_count += 1
        
        self.stdout.write(
            self.style.SUCCESS(
                f'\nCompleted: {success_count} successful, {error_count} errors'
            )
        )