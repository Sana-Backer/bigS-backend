"""
coupons/serializers.py
"""

from rest_framework import serializers

from .models import Coupon


class CouponSerializer(serializers.ModelSerializer):
    """Full read representation — used by admin endpoints."""

    class Meta:
        model = Coupon
        fields = [
            "id", "code", "description",
            "discount_type", "discount_value",
            "minimum_order_amount", "maximum_discount_amount",
            "usage_limit", "usage_limit_per_user", "used_count",
            "valid_from", "valid_until", "is_active",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "used_count", "created_at", "updated_at"]


class CouponCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Coupon
        fields = [
            "code", "description",
            "discount_type", "discount_value",
            "minimum_order_amount", "maximum_discount_amount",
            "usage_limit", "usage_limit_per_user",
            "valid_from", "valid_until", "is_active",
        ]

    def validate(self, attrs):
        valid_from = attrs.get("valid_from", getattr(self.instance, "valid_from", None))
        valid_until = attrs.get("valid_until", getattr(self.instance, "valid_until", None))
        if valid_from and valid_until and valid_from >= valid_until:
            raise serializers.ValidationError(
                {"valid_until": "valid_until must be after valid_from."}
            )
        discount_type = attrs.get("discount_type", getattr(self.instance, "discount_type", None))
        discount_value = attrs.get("discount_value", getattr(self.instance, "discount_value", None))
        if discount_type == Coupon.DiscountType.PERCENTAGE and discount_value and discount_value > 100:
            raise serializers.ValidationError(
                {"discount_value": "Percentage discount cannot exceed 100."}
            )
        return attrs


class ApplyCouponSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=50)
