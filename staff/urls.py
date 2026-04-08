from django.urls import path
from rest_framework.routers import DefaultRouter
from staff import views

router = DefaultRouter()

router.register(r'plans', views.PlanViewset, basename='plan')
router.register(r'sms-templates', views.SMSMessageTemplateViewSet, basename='sms-template')

urlpatterns = [] + router.urls