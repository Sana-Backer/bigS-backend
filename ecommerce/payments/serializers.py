"""
payments/serializers.py

NOTE: PaymentTransactionSerializer deliberately never exposes
razorpay_signature or processed_refund_ids (internal bookkeeping),
and no serializer here ever touches RAZORPAY_KEY_SECRET /
RAZORPAY_WEBHOOK_SECRET — those never leave payments/providers/razorpay_provider.py.
"""

from decimal import Decimal

from rest_framework import serializers

from .models import PaymentTransaction


class RazorpayCreateOrderSerializer(serializers.Serializer):
    order_id = serializers.UUIDField()


class RazorpayVerifyPaymentSerializer(serializers.Serializer):
    razorpay_order_id = serializers.CharField(max_length=64)
    razorpay_payment_id = serializers.CharField(max_length=64)
    razorpay_signature = serializers.CharField(max_length=512)


class RazorpayRefundSerializer(serializers.Serializer):
    """Body for the general-purpose POST /api/payments/razorpay/refund/."""

    order_id = serializers.UUIDField()
    amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, min_value=Decimal("0.01")
    )
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class AdminOrderRefundSerializer(serializers.Serializer):
    """Body for POST /api/admin/orders/<uuid:order_id>/refund/ — order comes from the URL."""

    amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, min_value=Decimal("0.01")
    )
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class PaymentTransactionSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    refundable_amount = serializers.SerializerMethodField()

    class Meta:
        model = PaymentTransaction
        fields = [
            "id", "order", "order_number",
            "provider", "status",
            "razorpay_order_id", "razorpay_payment_id",
            "amount", "amount_paise", "currency",
            "refunded_amount", "refundable_amount",
            "receipt", "failure_reason",
            "verified_at", "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_refundable_amount(self, obj):
        return str(obj.refundable_amount)
