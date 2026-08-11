"""
payments/models.py

PaymentTransaction  – one row per Razorpay order attempt against an
                      Order. Tracks amount, refund progress, and the
                      Razorpay identifiers involved.
PaymentWebhookEvent – audit trail + idempotency guard for every
                      Razorpay webhook delivery received.

Design notes
------------
- Reuses orders.models.Order as-is (FK, PROTECT — a paid/refunded
  transaction must never disappear because an Order row was deleted).
- Money is always stored as Decimal INR (`amount`, `refunded_amount`)
  — `amount_paise` is kept alongside only because that's the exact
  integer value Razorpay was asked to charge/refund, useful for
  reconciliation and for comparing against Razorpay API responses
  without re-deriving rounding.
- `processed_refund_ids` is a small JSON list of Razorpay refund IDs
  already folded into `refunded_amount`. Both the synchronous refund
  API call and the async `refund.processed` webhook funnel through
  the same services._apply_refund() helper, which checks this list
  first — so the same Razorpay refund is never double-counted no
  matter which path (or both) delivers it.
- No secrets (RAZORPAY_KEY_SECRET / RAZORPAY_WEBHOOK_SECRET) are ever
  stored on these models — only public identifiers and amounts.
"""

import uuid
from decimal import Decimal

from django.db import models

from orders.models import Order
from users.models import User

from .constants import PaymentProvider, PaymentTransactionStatus


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class PaymentTransaction(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="payment_transactions")

    provider = models.CharField(max_length=20, choices=PaymentProvider.choices, default=PaymentProvider.RAZORPAY)
    status = models.CharField(
        max_length=20, choices=PaymentTransactionStatus.choices,
        default=PaymentTransactionStatus.CREATED, db_index=True,
    )

    razorpay_order_id = models.CharField(max_length=64, unique=True, db_index=True)
    razorpay_payment_id = models.CharField(max_length=64, blank=True, db_index=True)
    razorpay_signature = models.CharField(max_length=255, blank=True)

    # Money — Decimal INR is the source of truth; paise is the exact
    # integer value sent to / received from Razorpay.
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    amount_paise = models.BigIntegerField()
    currency = models.CharField(max_length=10, default="INR")

    refunded_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    processed_refund_ids = models.JSONField(default=list, blank=True)

    receipt = models.CharField(max_length=64, blank=True)
    failure_reason = models.CharField(max_length=500, blank=True)

    initiated_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="payment_transactions"
    )
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Payment Transaction"
        verbose_name_plural = "Payment Transactions"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["order", "status"]),
            models.Index(fields=["razorpay_order_id"]),
            models.Index(fields=["razorpay_payment_id"]),
        ]

    def __str__(self):
        return f"{self.razorpay_order_id} ({self.status}) for {self.order.order_number}"

    @property
    def is_paid(self):
        return self.status in (
            PaymentTransactionStatus.PAID,
            PaymentTransactionStatus.PARTIALLY_REFUNDED,
        )

    @property
    def refundable_amount(self) -> Decimal:
        if self.status not in (
            PaymentTransactionStatus.PAID,
            PaymentTransactionStatus.PARTIALLY_REFUNDED,
        ):
            return Decimal("0.00")
        return (self.amount - self.refunded_amount).quantize(Decimal("0.01"))


class PaymentWebhookEvent(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    provider = models.CharField(max_length=20, choices=PaymentProvider.choices, default=PaymentProvider.RAZORPAY)
    event_id = models.CharField(max_length=128, unique=True, db_index=True)  # X-Razorpay-Event-Id header
    event_type = models.CharField(max_length=50, db_index=True)

    payment_transaction = models.ForeignKey(
        PaymentTransaction, null=True, blank=True, on_delete=models.SET_NULL, related_name="webhook_events"
    )

    payload = models.JSONField(default=dict)
    is_processed = models.BooleanField(default=False)
    processed_at = models.DateTimeField(null=True, blank=True)
    processing_error = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name = "Payment Webhook Event"
        verbose_name_plural = "Payment Webhook Events"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["event_type"]),
        ]

    def __str__(self):
        return f"{self.event_type} [{self.event_id}]"
