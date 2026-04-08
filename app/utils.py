import random, string
import base64
import requests
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import OrganizationPayment


@ensure_csrf_cookie
def get_csrf(request):
    return JsonResponse({'detail': 'CSRF cookie set'})


def generate_payment_code(length=6):
    characters = string.ascii_uppercase + string.digits
    return ''.join(random.choices(characters, k=length))


def calculate_next_billing_date(today=None):
    today = today or date.today()
    return today + timedelta(days=30)


class AuditViewSetMixin:
    def perform_create(self, serializer):
        serializer.save(
            created_by=self.request.user,
            updated_by=self.request.user
        )

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class DeleteMixin:
    @action(detail=False, methods=["POST"], url_path="bulk-delete")
    def bulk_delete(self, request):
        ids = request.data.get("ids", [])

        if not isinstance(ids, list) or not ids:
            return Response({"error": "Provide a list of IDs."}, status=400)

        queryset = self.filter_queryset(self.get_queryset()).filter(id__in=ids)
        deleted_count = queryset.count()

        queryset.delete()

        return Response(
            {
                "deleted": deleted_count,
                "requested": len(ids),
                "skipped": len(ids) - deleted_count,
            },
            status=status.HTTP_200_OK
        )


def generate_payment_ref():
    while True:
        ref = ''.join(random.choices(string.digits, k=8))
        if not OrganizationPayment.objects.filter(payment_ref=ref).exists():
            return ref


def send_stk_push(self, phone_number, amount, account_reference, transaction_desc):
    try:
        consumer_key = settings.MPESA_CONSUMER_KEY
        consumer_secret = settings.MPESA_CONSUMER_SECRET

        api_base = ("https://api.safaricom.co.ke" if settings.MPESA_ENV == "production" else "https://sandbox.safaricom.co.ke")
        oauth_url = f"{api_base}/oauth/v1/generate?grant_type=client_credentials"

        r = requests.get(oauth_url, auth=(consumer_key, consumer_secret))
        r.raise_for_status()
        access_token = r.json().get("access_token")

        if not access_token:
            return {"success": False, "error": "Unable to obtain access token"}

        shortcode = settings.MPESA_SHORTCODE
        passkey = settings.MPESA_PASSKEY
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

        data_to_encode = f"{shortcode}{passkey}{timestamp}"
        encoded_password = base64.b64encode(data_to_encode.encode()).decode()

        stk_url = f"{api_base}/mpesa/stkpush/v1/processrequest"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        payload = {
            "BusinessShortCode": shortcode,
            "Password": encoded_password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": int(amount),
            "PartyA": phone_number,
            "PartyB": shortcode,
            "PhoneNumber": phone_number,
            "CallBackURL": settings.MPESA_CALLBACK_URL,
            "AccountReference": account_reference,
            "TransactionDesc": transaction_desc
        }

        stk_response = requests.post(stk_url, json=payload, headers=headers)
        
        try:
            response_data = stk_response.json()
        except:
            return {"success": False, "error": "Invalid JSON response from M-Pesa"}

        if response_data.get("ResponseCode") != "0":
            return {"success": False, "error": response_data.get("ResponseDescription", "STK Push failed"), **response_data}

        return {"success": True, **response_data}

    except requests.exceptions.RequestException as e:
        return {"success": False, "error": f"Network error: {str(e)}"}

    except Exception as e:
        return {"success": False, "error": str(e)}