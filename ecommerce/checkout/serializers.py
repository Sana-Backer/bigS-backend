"""
checkout/serializers.py
"""

from rest_framework import serializers
from orders.constants import PaymentMethod


class AddressInputSerializer(serializers.Serializer):
    """New address data — used for guests, or for a user checking out
    with an address they haven't saved yet."""
    full_name = serializers.CharField(max_length=200)
    phone = serializers.CharField(max_length=17, required=False, allow_blank=True)
    line1 = serializers.CharField(max_length=255)
    line2 = serializers.CharField(max_length=255, required=False, allow_blank=True)
    city = serializers.CharField(max_length=100)
    state = serializers.CharField(max_length=100)
    postal_code = serializers.CharField(max_length=20)
    country = serializers.CharField(max_length=100, required=False, default="India")


class CheckoutValidateSerializer(serializers.Serializer):
    """No input required — validates the caller's current cart as-is."""
    pass


class CheckoutQuoteSerializer(serializers.Serializer):
    coupon_code = serializers.CharField(max_length=50, required=False, allow_blank=True)
    shipping_address = AddressInputSerializer(required=False)


class CreateOrderSerializer(serializers.Serializer):
    # Authenticated users may reference an existing saved address...
    billing_address_id = serializers.UUIDField(required=False)
    shipping_address_id = serializers.UUIDField(required=False)
    # ...or supply new address data (required path for guests).
    billing_address = AddressInputSerializer(required=False)
    shipping_address = AddressInputSerializer(required=False)

    guest_email = serializers.EmailField(required=False)
    guest_phone = serializers.CharField(max_length=17, required=False, allow_blank=True)
    payment_method = serializers.CharField(required=False, default=PaymentMethod.RAZORPAY)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=1000)

    def validate(self, attrs):
        if not attrs.get("shipping_address_id") and not attrs.get("shipping_address"):
            raise serializers.ValidationError(
                {"shipping_address": ["Provide either shipping_address_id or shipping_address."]}
            )
        normalized = str(attrs.get("payment_method") or PaymentMethod.RAZORPAY).strip().lower()
        if normalized not in PaymentMethod.values:
            raise serializers.ValidationError(
                {"payment_method": [f"'{attrs.get('payment_method')}' is not a valid payment method."]}
            )
        attrs["payment_method"] = normalized
        # Billing defaults to shipping if neither billing field is supplied —
        # enforced in the service layer, not here, since that's a business
        # rule rather than a shape validation.
        return attrs
