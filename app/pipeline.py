from .models import Organization, Plan
from .utils import calculate_next_billing_date


def setup_sso_user(backend, user, response, is_new=False, *args, **kwargs):
    if not is_new:
        return

    if not user.name:
        user.name = (
            response.get('name') # Facebook
            or f"{response.get('given_name', '')} {response.get('family_name', '')}".strip() # Google
            or ''
        )

    user.role = 'admin'

    plan = Plan.objects.filter(name='basic').first()
    org = Organization.objects.create(
        plan=plan,
        next_billing_date=calculate_next_billing_date()
    )

    user.organization = org
    user.save(update_fields=['name', 'role', 'organization_id'])