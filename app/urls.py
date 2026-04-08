from django.urls import path, include
from rest_framework.routers import DefaultRouter
from app import views, utils, gemini, demo_data_views

router = DefaultRouter()

router.register(r'user', views.UserViewSet, basename='user_profile')

router.register(r'properties', views.PropertyViewSet, basename='property')
router.register(r'blocks', views.BlockViewSet, basename='property_block')
router.register(r'units', views.UnitViewSet, basename='property_unit')
router.register(r'tenants', views.TenantViewset, basename='tenant')
router.register(r'reports', views.ReportViewset, basename='report')
router.register(r'expenses', views.ExpenseViewset, basename='expense')
router.register(r'payments', views.TenantPaymentViewset, basename='payment')
router.register(r'transactions', views.TenantTransactionViewset, basename='transactions')


urlpatterns = [
    path('me/', views.AuthView.as_view(), name='get_user'),
    path('billing/', views.OrganizationPlanViewset.as_view(), name='billing_info'),
    path('auth/csrf/', utils.get_csrf, name='get_csrf'),

    path('auth/sso/', include('social_django.urls', namespace='social')),
    path('register/', views.RegisterView.as_view(), name='register'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),

    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
    path('tenants/import/', views.TenantBulkImportView.as_view(), name='bulk_tenant_import'),
    path('subscription/payment/initiate/', views.InitiateSubscriptionPaymentView.as_view(), name='mpesa_subscription_initiation'),
    path('subscription/payment/status/<str:payment_ref>/', views.PaymentStatusView.as_view(), name='mpesa_payment_status'),
    path('subscription/mpesa/callback/', views.MpesaSubscriptionCallbackView.as_view(), name='mpesa_subscription_callback'),
    path('payments/mpesa/callback/', views.RentPaymentCallbackView.as_view(), name='rent_payment_callback'),

    path('units/ai-generate/', gemini.AIGenerateUnitsView.as_view(), name='gemini_generate'),
    path('units/bulk-create/', views.BulkCreateUnitsView.as_view(), name='bulk_create_units'),

    path('organization/status/', demo_data_views.OrganizationStatusView.as_view(), name='organization-status'),
    path('organization/clear-demo/', demo_data_views.ClearDemoDataView.as_view(), name='clear-demo-data'),

    path('', include(router.urls)),
]