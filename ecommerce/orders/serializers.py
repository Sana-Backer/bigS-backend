"""
orders/serializers.py
"""

from rest_framework import serializers

from .constants import FulfillmentStatus, OrderStatus, PaymentStatus
from .models import Order, OrderItem, OrderStatusHistory


class OrderItemSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = [
            "id", "product", "variant",
            "product_name", "variant_name", "sku",
            "unit_price", "quantity", "total_price", "image"
        ]
        read_only_fields = fields

    def get_image(self, obj):
        img = None
        if obj.variant:
            img = obj.variant.images.order_by("sort_order").first()
        if not img and obj.product:
            img = obj.product.images.order_by("sort_order").first()
        
        if img:
            request = self.context.get("request")
            return request.build_absolute_uri(img.image.url) if request else img.image.url
        return None


class OrderStatusHistorySerializer(serializers.ModelSerializer):
    changed_by_email = serializers.SerializerMethodField()

    class Meta:
        model = OrderStatusHistory
        fields = [
            "id", "status_type", "old_status", "new_status",
            "changed_by_email", "reason", "created_at",
        ]
        read_only_fields = fields

    def get_changed_by_email(self, obj):
        return obj.changed_by.email if obj.changed_by_id else None


class OrderSerializer(serializers.ModelSerializer):
    """Full order detail — used by both customer and admin detail views."""

    items = OrderItemSerializer(many=True, read_only=True)
    status_history = OrderStatusHistorySerializer(many=True, read_only=True)
    is_cancellable = serializers.BooleanField(read_only=True)

    class Meta:
        model = Order
        fields = [
            "id", "order_number",
            "customer_email", "customer_phone",
            "billing_address_snapshot", "shipping_address_snapshot",
            "subtotal", "discount_amount", "shipping_amount", "tax_amount", "total_amount", "currency",
            "coupon_code",
            "status", "payment_status", "fulfillment_status", "is_cancellable",
            "notes", "items", "status_history",
            "created_at", "updated_at",
        ]
        read_only_fields = fields


class OrderListItemSerializer(serializers.ModelSerializer):
    """Lighter representation for list endpoints (no items/history)."""

    item_count = serializers.SerializerMethodField()
    customer_name = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id", "order_number", "status", "payment_status", "fulfillment_status",
            "total_amount", "currency", "item_count", "created_at",
            "customer_email", "customer_phone", "customer_name",
        ]
        read_only_fields = fields

    def get_item_count(self, obj):
        return obj.items.count() if not hasattr(obj, "_prefetched_objects_cache") else len(obj.items.all())

    def get_customer_name(self, obj):
        return obj.billing_address_snapshot.get("full_name") or obj.shipping_address_snapshot.get("full_name") or "Guest"


class OrderCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)


class OrderStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=OrderStatus.choices)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)


class PaymentStatusUpdateSerializer(serializers.Serializer):
    payment_status = serializers.ChoiceField(choices=PaymentStatus.choices)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)


class FulfillmentStatusUpdateSerializer(serializers.Serializer):
    fulfillment_status = serializers.ChoiceField(choices=FulfillmentStatus.choices)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)
