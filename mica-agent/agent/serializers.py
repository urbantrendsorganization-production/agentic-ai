from rest_framework import serializers

from .models import Message, Session


class MessageInSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=4000, trim_whitespace=True)


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ["id", "role", "text", "created_at"]


class SessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Session
        fields = ["id", "customer_ref", "created_at"]
