"""
cart/serializers.py
"""

from rest_framework import serializers

from .models import Cart, CartItem
from .pricing import current_unit_price


class CartItemProductSerializer(serializers.Serializer):
    """Minimal product snapshot embedded in a cart item response."""
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.SlugField()
    sku = serializers.CharField()


class CartItemVariantSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    sku = serializers.CharField()
    attributes = serializers.JSONField()
    stock_quantity = serializers.IntegerField()


class CartItemSerializer(serializers.ModelSerializer):
    product = CartItemProductSerializer(read_only=True)
    variant = CartItemVariantSerializer(read_only=True, allow_null=True)
    current_price = serializers.SerializerMethodField()
    line_total = serializers.SerializerMethodField()

    class Meta:
        model = CartItem
        fields = [
            "id", "product", "variant", "quantity",
            "unit_price", "current_price", "line_total",
            "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_current_price(self, obj):
        return str(current_unit_price(obj))

    def get_line_total(self, obj):
        return str(current_unit_price(obj) * obj.quantity)


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    coupon_code = serializers.SerializerMethodField()

    class Meta:
        model = Cart
        fields = ["id", "status", "coupon_code", "items", "created_at", "updated_at"]
        read_only_fields = fields

    def get_coupon_code(self, obj):
        return obj.coupon.code if obj.coupon_id else None


class AddCartItemSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()
    variant_id = serializers.UUIDField(required=False, allow_null=True)
    quantity = serializers.IntegerField(min_value=1)


class UpdateCartItemSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1)


class CartSummarySerializer(serializers.Serializer):
    subtotal = serializers.DecimalField(max_digits=12, decimal_places=2)
    discount = serializers.DecimalField(max_digits=12, decimal_places=2)
    shipping_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    tax_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    grand_total = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_quantity = serializers.IntegerField()
    item_count = serializers.IntegerField()
