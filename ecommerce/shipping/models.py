"""
shipping/models.py

Shipment                – one Shiprocket shipment for exactly one Order.
ShiprocketWebhookEvent  – audit trail + idempotency guard for every
                          Shiprocket webhook delivery received.

Design notes
------------
- Reuses orders.models.Order as-is (OneToOneField, PROTECT). The
  OneToOne relationship is what actually prevents duplicate shipments
  at the database level — "one Order has at most one Shipment" is
  enforced the same way Django enforces any other 1:1, rather than by
  an application-level uniqueness check that could race. services.py
  additionally checks for an existing shipment up front so the error
  the API returns is a clean 409 (DuplicateShipment) instead of a raw
  IntegrityError.
- PROTECT (not CASCADE/SET_NULL) mirrors payments.models.PaymentTransaction's
  choice for the same reason: a shipment record is financial/operational
  history and must never silently disappear because an Order row was
  deleted.
- raw_create_response / raw_tracking_response are JSONField snapshots
  of the exact Shiprocket API responses — kept for support/debugging
  without ever needing to re-derive them from parsed fields.
"""

import uuid

from django.db import models

from orders.models import Order

from .constants import ShipmentStatus


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Shipment(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # One-to-one: the DB itself prevents a second Shipment row for the
    # same Order. PROTECT: a shipment must never vanish because the
    # Order was deleted.
    order = models.OneToOneField(Order, on_delete=models.PROTECT, related_name="shipment")

    # Shiprocket identifiers
    shiprocket_order_id = models.CharField(max_length=64, blank=True, db_index=True)
    shiprocket_shipment_id = models.CharField(max_length=64, blank=True, db_index=True)
    awb_code = models.CharField(max_length=64, blank=True, db_index=True)
    courier_id = models.CharField(max_length=32, blank=True)
    courier_name = models.CharField(max_length=200, blank=True)

    tracking_url = models.URLField(max_length=500, blank=True)
    label_url = models.URLField(max_length=500, blank=True)
    manifest_url = models.URLField(max_length=500, blank=True)

    status = models.CharField(
        max_length=20, choices=ShipmentStatus.choices, default=ShipmentStatus.PENDING, db_index=True,
    )

    pickup_location = models.CharField(max_length=100, blank=True)

    # Package details actually sent to Shiprocket at order-creation time —
    # kept for support/reconciliation, computed server-side only (see
    # services.create_shipment_for_order), never accepted from the client.
    package_weight_kg = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    package_length_cm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    package_width_cm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    package_height_cm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    raw_create_response = models.JSONField(default=dict, blank=True)
    raw_tracking_response = models.JSONField(default=dict, blank=True)

    cancelled_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Shipment"
        verbose_name_plural = "Shipments"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["awb_code"]),
            models.Index(fields=["shiprocket_order_id"]),
        ]

    def __str__(self):
        return f"Shipment for {self.order.order_number} ({self.status})"

    @property
    def has_awb(self):
        return bool(self.awb_code)


class ShiprocketWebhookEvent(TimeStampedModel):
    """
    Idempotency guard for Shiprocket webhook deliveries.

    Shiprocket's webhook payloads do not carry a documented, stable
    unique event-id header the way Razorpay's do (X-Razorpay-Event-Id).
    Instead, `dedup_key` is a SHA-256 hash of the exact raw request body
    computed by services.process_webhook_event() — an identical retried
    delivery hashes to the same value, so the unique constraint below
    guarantees the handler logic below only ever runs once per distinct
    payload, mirroring payments.models.PaymentWebhookEvent's role.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    dedup_key = models.CharField(max_length=64, unique=True, db_index=True)
    awb_code = models.CharField(max_length=64, blank=True, db_index=True)
    shiprocket_order_id = models.CharField(max_length=64, blank=True, db_index=True)
    current_status = models.CharField(max_length=100, blank=True)

    shipment = models.ForeignKey(
        Shipment, null=True, blank=True, on_delete=models.SET_NULL, related_name="webhook_events"
    )

    payload = models.JSONField(default=dict)
    is_processed = models.BooleanField(default=False)
    processed_at = models.DateTimeField(null=True, blank=True)
    processing_error = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name = "Shiprocket Webhook Event"
        verbose_name_plural = "Shiprocket Webhook Events"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["awb_code"]),
        ]

    def __str__(self):
        return f"{self.current_status or 'event'} [{self.dedup_key[:12]}...]"
