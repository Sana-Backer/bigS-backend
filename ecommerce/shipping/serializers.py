"""
shipping/serializers.py
"""

from rest_framework import serializers

from .models import Shipment


class ServiceabilityQuerySerializer(serializers.Serializer):
    delivery_postcode = serializers.CharField(max_length=10)
    pickup_postcode = serializers.CharField(max_length=10, required=False, allow_blank=True)
    weight = serializers.DecimalField(max_digits=8, decimal_places=3, required=False, min_value=0)
    cod = serializers.BooleanField(required=False, default=False)


class ShipmentCreateSerializer(serializers.Serializer):
    """Optional overrides only — every price/total/item field is always
    read from the Order itself, never from this payload."""
    pickup_location = serializers.CharField(max_length=100, required=False, allow_blank=True)


class AssignAWBSerializer(serializers.Serializer):
    courier_id = serializers.CharField(max_length=32, required=False, allow_blank=True)


class ShipmentCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)


class ShipmentSerializer(serializers.ModelSerializer):
    order_id = serializers.UUIDField(source="order.id", read_only=True)
    order_number = serializers.CharField(source="order.order_number", read_only=True)

    class Meta:
        model = Shipment
        fields = [
            "id", "order_id", "order_number",
            "shiprocket_order_id", "shiprocket_shipment_id",
            "awb_code", "courier_id", "courier_name",
            "tracking_url", "label_url", "manifest_url",
            "status", "pickup_location",
            "package_weight_kg", "package_length_cm", "package_width_cm", "package_height_cm",
            "cancelled_at", "delivered_at",
            "created_at", "updated_at",
        ]
        read_only_fields = fields


class ShipmentTrackingSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)

    class Meta:
        model = Shipment
        fields = [
            "id", "order_number", "awb_code", "courier_name",
            "status", "tracking_url", "raw_tracking_response",
            "delivered_at", "updated_at",
        ]
        read_only_fields = fields
