"""
shipping/constants.py

Named values for the shipping app. Views/services must go through
these rather than writing status strings inline, mirroring the
convention already used in orders/constants.py and payments/constants.py.
"""

from django.db import models

from orders.constants import FulfillmentStatus, OrderStatus


class ShipmentStatus(models.TextChoices):
    PENDING = "pending", "Pending"                      # Shipment row created, not yet sent to Shiprocket
    CREATED = "created", "Created"                       # Shiprocket order/shipment created, no AWB yet
    AWB_ASSIGNED = "awb_assigned", "AWB Assigned"
    PICKED_UP = "picked_up", "Picked Up"
    IN_TRANSIT = "in_transit", "In Transit"
    OUT_FOR_DELIVERY = "out_for_delivery", "Out for Delivery"
    DELIVERED = "delivered", "Delivered"
    RTO = "rto", "Return to Origin"
    CANCELLED = "cancelled", "Cancelled"
    FAILED = "failed", "Failed"


# Shipment statuses a cancellation may be initiated from.
CANCELLABLE_SHIPMENT_STATUSES = {
    ShipmentStatus.PENDING,
    ShipmentStatus.CREATED,
    ShipmentStatus.AWB_ASSIGNED,
    ShipmentStatus.PICKED_UP,
    ShipmentStatus.IN_TRANSIT,
}

# ---------------------------------------------------------------------------
# Shiprocket status string -> internal ShipmentStatus
# ---------------------------------------------------------------------------
# Shiprocket's tracking/webhook payloads report status as free-text
# (`current_status`, `shipment_status`, or `status`) rather than a single
# stable enum. This project matches on a normalised (upper, no punctuation)
# form of that string against known keywords, longest/most-specific first,
# rather than relying on any specific field name — Shiprocket has changed
# the exact field name across API versions/webhook payloads.
SHIPROCKET_STATUS_KEYWORDS = [
    # (keyword, ShipmentStatus) — order matters, first match wins.
    ("RTO", ShipmentStatus.RTO),
    ("RETURN TO ORIGIN", ShipmentStatus.RTO),
    ("CANCEL", ShipmentStatus.CANCELLED),
    ("DELIVERED", ShipmentStatus.DELIVERED),
    ("OUT FOR DELIVERY", ShipmentStatus.OUT_FOR_DELIVERY),
    ("OFD", ShipmentStatus.OUT_FOR_DELIVERY),
    ("IN TRANSIT", ShipmentStatus.IN_TRANSIT),
    ("TRANSIT", ShipmentStatus.IN_TRANSIT),
    ("SHIPPED", ShipmentStatus.IN_TRANSIT),
    ("PICKED UP", ShipmentStatus.PICKED_UP),
    ("PICKUP GENERATED", ShipmentStatus.CREATED),
    ("PICKUP SCHEDULED", ShipmentStatus.CREATED),
    ("AWB ASSIGNED", ShipmentStatus.AWB_ASSIGNED),
    ("MANIFEST", ShipmentStatus.AWB_ASSIGNED),
    ("FAILED", ShipmentStatus.FAILED),
    ("UNDELIVERED", ShipmentStatus.FAILED),
    ("NEW", ShipmentStatus.CREATED),
]


def map_shiprocket_status(raw_status: str):
    """
    Normalises a free-text Shiprocket status string and maps it to a
    ShipmentStatus. Returns None if nothing matches — callers must treat
    None as "ignore, unrecognised status" rather than guessing.
    """
    if not raw_status:
        return None
    normalised = str(raw_status).strip().upper().replace("_", " ").replace("-", " ")
    for keyword, mapped in SHIPROCKET_STATUS_KEYWORDS:
        if keyword in normalised:
            return mapped
    return None


# ---------------------------------------------------------------------------
# ShipmentStatus -> Order / Fulfillment status propagation
# ---------------------------------------------------------------------------
# Only shipment statuses with a direct, always-valid equivalent in
# orders.constants are listed. Anything not listed here (e.g. IN_TRANSIT,
# which has no dedicated OrderStatus) updates the Shipment row only — the
# order's own status transition rules (orders.constants) are never
# bypassed or duplicated in this app; change_order_status()/
# change_fulfillment_status() are always the ones enforcing them, and an
# InvalidStatusTransition (e.g. order already DELIVERED) is swallowed as a
# no-op exactly like payments.services does for payment-status sync.
SHIPMENT_STATUS_TO_ORDER_STATUS = {
    ShipmentStatus.PICKED_UP: OrderStatus.SHIPPED,
    ShipmentStatus.OUT_FOR_DELIVERY: OrderStatus.OUT_FOR_DELIVERY,
    ShipmentStatus.DELIVERED: OrderStatus.DELIVERED,
}

SHIPMENT_STATUS_TO_FULFILLMENT_STATUS = {
    ShipmentStatus.PICKED_UP: FulfillmentStatus.SHIPPED,
    ShipmentStatus.OUT_FOR_DELIVERY: FulfillmentStatus.OUT_FOR_DELIVERY,
    ShipmentStatus.DELIVERED: FulfillmentStatus.DELIVERED,
    ShipmentStatus.CANCELLED: FulfillmentStatus.CANCELLED,
}
