from rest_framework import serializers
from app.models import Plan, SMSMessageTemplate


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = '__all__'
        read_only_fields = ['id']


class SMSMessageTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SMSMessageTemplate
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']