from rest_framework import serializers
from .models import Advertisement


class AdvertisementSerializer(serializers.ModelSerializer):
    ctr = serializers.FloatField(read_only=True)

    class Meta:
        model = Advertisement
        fields = [
            "id", "title", "image", "target_url", "placement",
            "status", "starts_at", "ends_at", "impressions", "clicks", "ctr",
            "created_at",
        ]
        read_only_fields = ["id", "status", "impressions", "clicks", "ctr", "created_at"]


class AdvertisementWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Advertisement
        fields = ["title", "image", "target_url", "placement", "starts_at", "ends_at"]

    def validate(self, attrs):
        if attrs["ends_at"] <= attrs["starts_at"]:
            raise serializers.ValidationError({"ends_at": "End date must be after start date."})
        return attrs
