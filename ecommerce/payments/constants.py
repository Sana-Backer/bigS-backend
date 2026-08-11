"""
payments/constants.py

Named values for the payments app. Views/services must go through
these rather than writing status/event strings inline, mirroring the
convention already used in orders/constants.py.
"""

from django.db import models


class PaymentProvider(models.TextChoices):
    RAZORPAY = "razorpay", "Razorpay"


class PaymentTransactionStatus(models.TextChoices):
    CREATED = "created", "Created"                        # Razorpay order created, awaiting payment
    AUTHORIZED = "authorized", "Authorized"                # payment authorized, not yet captured
    PAID = "paid", "Paid"                                  # captured / fully paid
    FAILED = "failed", "Failed"
    PARTIALLY_REFUNDED = "partially_refunded", "Partially Refunded"
    REFUNDED = "refunded", "Refunded"


# Transitions a PaymentTransaction may move through. Mirrors the shape of
# orders.constants transition maps for consistency; enforced in services.py.
PAYMENT_TRANSACTION_TRANSITIONS = {
    PaymentTransactionStatus.CREATED: {
        PaymentTransactionStatus.AUTHORIZED,
        PaymentTransactionStatus.PAID,
        PaymentTransactionStatus.FAILED,
    },
    PaymentTransactionStatus.AUTHORIZED: {
        PaymentTransactionStatus.PAID,
        PaymentTransactionStatus.FAILED,
    },
    PaymentTransactionStatus.PAID: {
        PaymentTransactionStatus.PARTIALLY_REFUNDED,
        PaymentTransactionStatus.REFUNDED,
    },
    PaymentTransactionStatus.FAILED: set(),
    PaymentTransactionStatus.PARTIALLY_REFUNDED: {PaymentTransactionStatus.REFUNDED},
    PaymentTransactionStatus.REFUNDED: set(),
}

# Transaction statuses that still count as "live" — i.e. an order that
# already has one of these should not have a second Razorpay order created
# for it; the existing transaction is reused instead (idempotent /create/).
LIVE_TRANSACTION_STATUSES = {
    PaymentTransactionStatus.CREATED,
    PaymentTransactionStatus.AUTHORIZED,
}

# Transaction statuses a refund may be initiated from.
REFUNDABLE_TRANSACTION_STATUSES = {
    PaymentTransactionStatus.PAID,
    PaymentTransactionStatus.PARTIALLY_REFUNDED,
}


class WebhookEventType(models.TextChoices):
    PAYMENT_AUTHORIZED = "payment.authorized", "Payment Authorized"
    PAYMENT_CAPTURED = "payment.captured", "Payment Captured"
    PAYMENT_FAILED = "payment.failed", "Payment Failed"
    ORDER_PAID = "order.paid", "Order Paid"
    REFUND_PROCESSED = "refund.processed", "Refund Processed"
    REFUND_FAILED = "refund.failed", "Refund Failed"


HANDLED_WEBHOOK_EVENTS = {
    WebhookEventType.PAYMENT_AUTHORIZED,
    WebhookEventType.PAYMENT_CAPTURED,
    WebhookEventType.PAYMENT_FAILED,
    WebhookEventType.ORDER_PAID,
    WebhookEventType.REFUND_PROCESSED,
    WebhookEventType.REFUND_FAILED,
}

RAZORPAY_RECEIPT_MAX_LENGTH = 40  # hard limit enforced by Razorpay's Orders API
