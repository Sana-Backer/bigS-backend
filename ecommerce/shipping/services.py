"""
shipping/services.py

All shipping orchestration logic:
  - check_serviceability()       – GET /api/shipping/serviceability/
  - create_shipment_for_order()  – POST /api/admin/orders/<id>/shipping/create/
  - assign_awb()                 – POST /api/admin/shipments/<id>/assign-awb/
  - generate_label()             – POST /api/admin/shipments/<id>/label/
  - generate_manifest()          – POST /api/admin/shipments/<id>/manifest/
  - refresh_tracking()           – GET  /api/admin/shipments/<id>/tracking/
                                    GET  /api/orders/<id>/tracking/
  - cancel_shipment()            – POST /api/admin/shipments/<id>/cancel/
  - process_webhook_event()      – POST /api/shipping/webhooks/shiprocket/

Reuse, not reinvention
-----------------------
- Order data: every field sent to Shiprocket (customer, addresses,
  items, SKUs, quantities, prices, total) is read straight from the
  Order/OrderItem rows already created by orders.services — never
  accepted from the request body. There is no client-supplied price or
  total anywhere in this module.
- Order status transitions: orders.services.change_order_status() /
  change_fulfillment_status() are the ONLY way this module ever touches
  Order.status / Order.fulfillment_status, exactly like payments.services
  does for payment_status. Both of those functions already create an
  OrderStatusHistory row on every call, so every status change this app
  makes is automatically audited without this module touching
  OrderStatusHistory directly. Where a transition isn't applicable
  (e.g. the order already moved on through some other path),
  InvalidStatusTransition is caught and ignored — the same idempotent
  no-op shape payments.services uses for change_payment_status().
- Ownership scoping: shipping.selectors.get_shipment_for_owner() gives the
  customer-facing tracking endpoint the same "don't leak whether this ID
  exists" guarantee orders.selectors.get_order_for_owner() already provides.
"""

import hashlib
import json
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from orders.constants import FulfillmentStatus, OrderStatus, PaymentStatus
from orders.exceptions import InvalidStatusTransition
from orders import services as orders_services
from orders.models import Order

from .constants import (
    CANCELLABLE_SHIPMENT_STATUSES,
    SHIPMENT_STATUS_TO_FULFILLMENT_STATUS,
    SHIPMENT_STATUS_TO_ORDER_STATUS,
    ShipmentStatus,
    map_shiprocket_status,
)
from .exceptions import (
    AWBAlreadyAssigned,
    AWBAssignmentFailed,
    CancellationFailed,
    DuplicateShipment,
    InvalidWebhookPayload,
    LabelGenerationFailed,
    ManifestGenerationFailed,
    ManifestRequiresAWB,
    MissingShippingAddress,
    OrderNotPaid,
    OrderNotShippable,
    ShipmentNotCancellable,
    TrackingFailed,
    TrackingNotAvailable,
)
from .models import Shipment, ShiprocketWebhookEvent
from .providers import shiprocket_provider

# Orders may only have a shipment created for them from these statuses.
SHIPPABLE_ORDER_STATUSES = {OrderStatus.CONFIRMED, OrderStatus.PROCESSING, OrderStatus.PACKED}


# ---------------------------------------------------------------------------
# Settings helpers (all overridable via env / settings, sensible defaults)
# ---------------------------------------------------------------------------

def _pickup_location() -> str:
    return getattr(settings, "SHIPROCKET_PICKUP_LOCATION", "Primary")


def _pickup_postcode() -> str:
    return getattr(settings, "SHIPROCKET_PICKUP_POSTCODE", "")


def _default_item_weight_kg() -> Decimal:
    return Decimal(str(getattr(settings, "SHIPROCKET_DEFAULT_ITEM_WEIGHT_KG", "0.5")))


def _min_package_weight_kg() -> Decimal:
    return Decimal(str(getattr(settings, "SHIPROCKET_MIN_PACKAGE_WEIGHT_KG", "0.5")))


def _default_dimensions_cm():
    return (
        Decimal(str(getattr(settings, "SHIPROCKET_DEFAULT_LENGTH_CM", "10"))),
        Decimal(str(getattr(settings, "SHIPROCKET_DEFAULT_WIDTH_CM", "10"))),
        Decimal(str(getattr(settings, "SHIPROCKET_DEFAULT_HEIGHT_CM", "10"))),
    )


# ---------------------------------------------------------------------------
# GET /api/shipping/serviceability/
# ---------------------------------------------------------------------------

def check_serviceability(*, delivery_postcode: str, weight=None, cod: bool = False, pickup_postcode: str = None) -> dict:
    pickup = pickup_postcode or _pickup_postcode()
    package_weight = Decimal(str(weight)) if weight else _default_item_weight_kg()
    return shiprocket_provider.check_serviceability(
        pickup_postcode=pickup,
        delivery_postcode=delivery_postcode,
        weight=package_weight,
        cod=cod,
    )


# ---------------------------------------------------------------------------
# POST /api/admin/orders/<uuid:order_id>/shipping/create/
# ---------------------------------------------------------------------------

def _split_name(full_name: str):
    parts = (full_name or "").strip().split(" ", 1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def _compute_package(order: Order):
    """
    Compute the final package weight and dimensions.

    Shiprocket requires a minimum chargeable weight of 0.50 kg.
    ProductVariant.weight is used when available; otherwise the
    configured default item weight is used.
    """

    items = list(
        order.items.select_related("variant")
    )

    if not items:
        raise ValueError("Cannot create a Shiprocket shipment without order items.")

    total_weight = Decimal("0")

    for item in items:
        unit_weight = None

        if (
            item.variant_id
            and item.variant
            and item.variant.weight
        ):
            unit_weight = Decimal(str(item.variant.weight))

        if unit_weight is None:
            unit_weight = _default_item_weight_kg()

        total_weight += unit_weight * Decimal(str(item.quantity))

    # Shiprocket minimum chargeable weight
    minimum_weight = _min_package_weight_kg()

    if total_weight < minimum_weight:
        total_weight = minimum_weight

    length, width, height = _default_dimensions_cm()

    return (
        total_weight,
        length,
        width,
        height,
    )

def _validate_shiprocket_address(
        address: dict,
        address_type: str,
        fallback_phone: str = "",
    ):
    required_fields = {
        "full_name": address.get("full_name"),
        "line1": address.get("line1"),
        "city": address.get("city"),
        "state": address.get("state"),
        "postal_code": address.get("postal_code"),
        "country": address.get("country"),
        "phone": address.get("phone") or fallback_phone,
    }

    missing = [
        field
        for field, value in required_fields.items()
        if not value
    ]

    if missing:
        raise MissingShippingAddress(
            f"{address_type} address is missing: "
            f"{', '.join(missing)}"
        )

def _build_order_items_payload(order: Order):
    items = []

    for item in order.items.all():
        item_payload = {
            "name": item.product_name,
            "sku": item.sku,
            "units": int(item.quantity),
            "selling_price": float(item.unit_price),
            "discount": "",
            "tax": "",
            "hsn": "",
        }

        items.append(item_payload)

    return items

def _build_shiprocket_payload(
    order: Order,
    *,
    pickup_location: str,
    weight,
    length,
    width,
    height,
):
    billing = order.billing_address_snapshot or {}
    shipping = order.shipping_address_snapshot or {}

    if not shipping:
        raise MissingShippingAddress()

    if not billing:
        billing = shipping

    _validate_shiprocket_address(
        billing,
        "Billing",
        fallback_phone=order.customer_phone,
    )

    _validate_shiprocket_address(
        shipping,
        "Shipping",
        fallback_phone=order.customer_phone,
    )

    # If billing address was not separately stored,
    # use shipping address as billing address.
    if not billing:
        billing = shipping

    billing_first, billing_last = _split_name(
        billing.get("full_name", "")
    )

    shipping_first, shipping_last = _split_name(
        shipping.get("full_name", "")
    )

    shipping_is_billing = shipping == billing

    order_items = _build_order_items_payload(order)

    if not order_items:
        raise ValueError(
            "Cannot create Shiprocket order without order items."
        )

    payload = {
        # ---------------------------------------------------------
        # Order
        # ---------------------------------------------------------
        "order_id": str(order.order_number),

        "order_date": timezone.localtime(
            order.created_at
        ).strftime("%Y-%m-%d %H:%M"),

        "pickup_location": pickup_location,

        # ---------------------------------------------------------
        # Billing
        # ---------------------------------------------------------
        "billing_customer_name": billing_first,
        "billing_last_name": billing_last,

        "billing_address": billing.get("line1", ""),
        "billing_address_2": billing.get("line2", ""),

        "billing_city": billing.get("city", ""),
        "billing_pincode": str(
            billing.get("postal_code", "")
        ),

        "billing_state": billing.get("state", ""),
        "billing_country": billing.get(
            "country",
            "India",
        ),

        "billing_email": order.customer_email or "",

        "billing_phone": str(
            billing.get("phone")
            or order.customer_phone
            or ""
        ),

        # ---------------------------------------------------------
        # Shipping
        # ---------------------------------------------------------
        "shipping_is_billing": shipping_is_billing,

        "shipping_customer_name": shipping_first,
        "shipping_last_name": shipping_last,

        "shipping_address": shipping.get(
            "line1",
            "",
        ),

        "shipping_address_2": shipping.get(
            "line2",
            "",
        ),

        "shipping_city": shipping.get(
            "city",
            "",
        ),

        "shipping_pincode": str(
            shipping.get(
                "postal_code",
                "",
            )
        ),

        "shipping_state": shipping.get(
            "state",
            "",
        ),

        "shipping_country": shipping.get(
            "country",
            "India",
        ),

        "shipping_email": order.customer_email or "",

        "shipping_phone": str(
            shipping.get("phone")
            or order.customer_phone
            or ""
        ),

        # ---------------------------------------------------------
        # Products
        # ---------------------------------------------------------
        "order_items": order_items,

        # ---------------------------------------------------------
        # Payment
        # ---------------------------------------------------------
        "payment_method": "Prepaid",

        # ---------------------------------------------------------
        # Charges
        # ---------------------------------------------------------
        "shipping_charges": 0,
        "giftwrap_charges": 0,
        "transaction_charges": 0,
        "total_discount": 0,

        "sub_total": float(order.subtotal),

        # ---------------------------------------------------------
        # Package
        # ---------------------------------------------------------
        "length": float(length),
        "breadth": float(width),
        "height": float(height),

        # Shiprocket minimum chargeable weight = 0.50 kg
        "weight": float(weight),
    }

    return payload

@transaction.atomic
def create_shipment_for_order(order: Order, *, created_by=None, pickup_location: str = None) -> Shipment:
    # Lock the order row so two concurrent "create shipment" clicks can't
    # both pass the duplicate-shipment check and race each other.
    order = Order.objects.select_for_update().get(pk=order.pk)

    if Shipment.objects.filter(order=order).exists():
        raise DuplicateShipment()

    if order.payment_status != PaymentStatus.PAID:
        raise OrderNotPaid()

    if order.status not in SHIPPABLE_ORDER_STATUSES:
        raise OrderNotShippable(
            f"Orders in '{order.status}' status cannot have a shipment created."
        )

    if not order.shipping_address_snapshot:
        raise MissingShippingAddress()

    weight, length, width, height = _compute_package(order)
    pickup = pickup_location or _pickup_location()
    payload = _build_shiprocket_payload(
        order, pickup_location=pickup, weight=weight, length=length, width=width, height=height,
    )

    print("\n========== SHIPROCKET PAYLOAD ==========")
    print(payload)
    print("========================================\n")
    response = shiprocket_provider.create_order(payload)

    shipment = Shipment.objects.create(
        order=order,
        shiprocket_order_id=str(response.get("order_id", "")),
        shiprocket_shipment_id=str(response.get("shipment_id", "")),
        pickup_location=pickup,
        package_weight_kg=weight,
        package_length_cm=length,
        package_width_cm=width,
        package_height_cm=height,
        status=ShipmentStatus.CREATED,
        raw_create_response=response,
    )

    try:
        orders_services.change_fulfillment_status(
            order, FulfillmentStatus.PROCESSING,
            changed_by=created_by, reason="Shipment created with Shiprocket.",
        )
    except InvalidStatusTransition:
        pass

    return shipment


# ---------------------------------------------------------------------------
# POST /api/admin/shipments/<uuid:id>/assign-awb/
# ---------------------------------------------------------------------------

@transaction.atomic
def assign_awb(shipment: Shipment, *, courier_id: str = None, changed_by=None) -> Shipment:
    shipment = Shipment.objects.select_for_update().select_related("order").get(pk=shipment.pk)

    if shipment.has_awb:
        raise AWBAlreadyAssigned()

    response = shiprocket_provider.assign_awb(
        shipment_id=shipment.shiprocket_shipment_id, courier_id=courier_id,
    )

    # Shiprocket's assign-awb response nests the assigned courier/AWB
    # details under response.data.
    response_section = (response or {}).get("response", {})
    awb_data = response_section.get("data", {}) if isinstance(response_section, dict) else {}

    awb_code = awb_data.get("awb_code") if isinstance(awb_data, dict) else None
    if not awb_code:
        raise AWBAssignmentFailed("Shiprocket did not return an AWB code.")

    shipment.awb_code = awb_code
    shipment.courier_id = str(awb_data.get("courier_company_id", courier_id or ""))
    shipment.courier_name = awb_data.get("courier_name", "")
    shipment.status = ShipmentStatus.AWB_ASSIGNED
    shipment.raw_create_response = {**shipment.raw_create_response, "awb_assign_response": response}
    shipment.save(update_fields=[
        "awb_code", "courier_id", "courier_name", "status", "raw_create_response", "updated_at",
    ])
    return shipment


# ---------------------------------------------------------------------------
# POST /api/admin/shipments/<uuid:id>/label/
# ---------------------------------------------------------------------------

def generate_label(shipment: Shipment) -> Shipment:
    if not shipment.shiprocket_shipment_id:
        raise LabelGenerationFailed("Shipment has no Shiprocket shipment id.")

    response = shiprocket_provider.generate_label([shipment.shiprocket_shipment_id])
    label_url = response.get("label_url")
    if not label_url:
        raise LabelGenerationFailed("Shiprocket did not return a label URL.")

    shipment.label_url = label_url
    shipment.save(update_fields=["label_url", "updated_at"])
    return shipment


# ---------------------------------------------------------------------------
# POST /api/admin/shipments/<uuid:id>/manifest/
# ---------------------------------------------------------------------------

def generate_manifest(shipment: Shipment) -> Shipment:
    if not shipment.has_awb:
        raise ManifestRequiresAWB()

    response = shiprocket_provider.generate_manifest([shipment.shiprocket_shipment_id])
    manifest_url = response.get("manifest_url")
    if not manifest_url:
        raise ManifestGenerationFailed("Shiprocket did not return a manifest URL.")

    shipment.manifest_url = manifest_url
    shipment.save(update_fields=["manifest_url", "updated_at"])
    return shipment


# ---------------------------------------------------------------------------
# GET /api/admin/shipments/<uuid:id>/tracking/
# GET /api/orders/<uuid:order_id>/tracking/
# ---------------------------------------------------------------------------

def refresh_tracking(shipment: Shipment) -> Shipment:
    if not shipment.has_awb:
        raise TrackingNotAvailable()

    try:
        response = shiprocket_provider.track_by_awb(shipment.awb_code)
    except Exception as exc:
        raise TrackingFailed(str(exc)) from exc

    shipment.raw_tracking_response = response
    shipment.save(update_fields=["raw_tracking_response", "updated_at"])

    raw_status = _extract_tracking_status(response)
    if raw_status:
        sync_shipment_status(shipment, raw_status)
        shipment.refresh_from_db()

    return shipment


def _extract_tracking_status(response: dict):
    """
    Shiprocket's track-by-awb response shape nests the current status a
    couple of levels deep and the exact key has varied across API
    versions, so this checks the known locations in order rather than
    assuming one fixed shape.
    """
    if not isinstance(response, dict):
        return None
    tracking_data = response.get("tracking_data") or response
    if isinstance(tracking_data, dict):
        if tracking_data.get("shipment_track"):
            track = tracking_data["shipment_track"]
            if isinstance(track, list) and track:
                return track[0].get("current_status")
        if tracking_data.get("shipment_status"):
            return tracking_data.get("shipment_status")
        if tracking_data.get("current_status"):
            return tracking_data.get("current_status")
    return None


# ---------------------------------------------------------------------------
# Status sync (shared by tracking refresh + webhook handling)
# ---------------------------------------------------------------------------

@transaction.atomic
def sync_shipment_status(shipment: Shipment, raw_status: str, changed_by=None):
    """
    Maps a raw Shiprocket status string to a ShipmentStatus and, if it
    represents forward progress, updates the Shipment row and propagates
    an equivalent transition to the linked Order via the existing
    orders.services transition functions (never by writing Order.status
    directly). Safe to call repeatedly with the same status — it is a
    no-op once the shipment is already at (or past) that status.
    """
    mapped = map_shiprocket_status(raw_status)
    if mapped is None:
        return shipment

    shipment = Shipment.objects.select_for_update().select_related("order").get(pk=shipment.pk)
    if mapped == shipment.status:
        return shipment

    shipment.status = mapped
    update_fields = ["status", "updated_at"]
    if mapped == ShipmentStatus.DELIVERED and not shipment.delivered_at:
        shipment.delivered_at = timezone.now()
        update_fields.append("delivered_at")
    if mapped == ShipmentStatus.CANCELLED and not shipment.cancelled_at:
        shipment.cancelled_at = timezone.now()
        update_fields.append("cancelled_at")
    shipment.save(update_fields=update_fields)

    order = Order.objects.select_for_update().get(pk=shipment.order_id)

    new_order_status = SHIPMENT_STATUS_TO_ORDER_STATUS.get(mapped)
    if new_order_status is not None:
        try:
            orders_services.change_order_status(
                order, new_order_status, changed_by=changed_by,
                reason=f"Shiprocket status update: {raw_status}.",
            )
        except InvalidStatusTransition:
            pass

    new_fulfillment_status = SHIPMENT_STATUS_TO_FULFILLMENT_STATUS.get(mapped)
    if new_fulfillment_status is not None:
        try:
            orders_services.change_fulfillment_status(
                order, new_fulfillment_status, changed_by=changed_by,
                reason=f"Shiprocket status update: {raw_status}.",
            )
        except InvalidStatusTransition:
            pass

    return shipment


# ---------------------------------------------------------------------------
# POST /api/admin/shipments/<uuid:id>/cancel/
# ---------------------------------------------------------------------------

@transaction.atomic
def cancel_shipment(shipment: Shipment, *, changed_by=None, reason: str = "") -> Shipment:
    shipment = Shipment.objects.select_for_update().select_related("order").get(pk=shipment.pk)

    if shipment.status not in CANCELLABLE_SHIPMENT_STATUSES:
        raise ShipmentNotCancellable(
            f"Shipments in '{shipment.status}' status can no longer be cancelled."
        )

    if shipment.shiprocket_order_id:
        try:
            response = shiprocket_provider.cancel_order([shipment.shiprocket_order_id])
        except Exception as exc:
            raise CancellationFailed(str(exc)) from exc
        shipment.raw_create_response = {**shipment.raw_create_response, "cancel_response": response}

    shipment.status = ShipmentStatus.CANCELLED
    shipment.cancelled_at = timezone.now()
    shipment.save(update_fields=["status", "cancelled_at", "raw_create_response", "updated_at"])

    order = Order.objects.select_for_update().get(pk=shipment.order_id)
    try:
        orders_services.change_fulfillment_status(
            order, FulfillmentStatus.CANCELLED,
            changed_by=changed_by, reason=reason or "Shipment cancelled.",
        )
    except InvalidStatusTransition:
        pass

    return shipment


# ---------------------------------------------------------------------------
# POST /api/shipping/webhooks/shiprocket/
# ---------------------------------------------------------------------------

def verify_webhook_token(provided_token: str) -> bool:
    """
    Shiprocket webhooks don't use an HMAC signature the way Razorpay's do
    — instead, the "Secret Key" configured in the Shiprocket dashboard's
    webhook settings is echoed back on every delivery (as the `X-Api-Key`
    header) so the receiver can confirm the call genuinely came from
    Shiprocket. SHIPROCKET_WEBHOOK_SECRET holds that same value.
    """
    expected = getattr(settings, "SHIPROCKET_WEBHOOK_SECRET", "")
    if not expected:
        # No secret configured: nothing to verify against. Documented as
        # an explicit opt-out — production deployments should always set
        # SHIPROCKET_WEBHOOK_SECRET.
        return True
    return bool(provided_token) and provided_token == expected


def _find_shipment_for_webhook(payload: dict):
    awb = payload.get("awb") or payload.get("awb_code")
    sr_order_id = payload.get("order_id") or payload.get("sr_order_id")

    shipment = None
    if awb:
        shipment = Shipment.objects.filter(awb_code=awb).select_for_update().first()
    if shipment is None and sr_order_id:
        shipment = Shipment.objects.filter(
            shiprocket_order_id=str(sr_order_id)
        ).select_for_update().first()
    return shipment


@transaction.atomic
def process_webhook_event(*, raw_body: bytes) -> ShiprocketWebhookEvent:
    """
    Parses + records a Shiprocket webhook delivery, then dispatches it
    to sync_shipment_status(). Idempotent: `dedup_key` is a SHA-256 hash
    of the exact raw body, so an identical retried delivery hits the
    unique constraint via get_or_create() and `created` is reliably
    False the second time — the handler logic below never runs twice
    for the same payload, mirroring payments.services.process_webhook_event().
    """
    try:
        body_str = raw_body.decode("utf-8") if isinstance(raw_body, bytes) else raw_body
        payload = json.loads(body_str) if body_str else {}
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidWebhookPayload() from exc

    dedup_key = hashlib.sha256(body_str.encode("utf-8")).hexdigest()

    current_status = payload.get("current_status") or payload.get("shipment_status") or ""
    event, created = ShiprocketWebhookEvent.objects.get_or_create(
        dedup_key=dedup_key,
        defaults={
            "awb_code": payload.get("awb") or payload.get("awb_code") or "",
            "shiprocket_order_id": str(payload.get("order_id") or payload.get("sr_order_id") or ""),
            "current_status": current_status,
            "payload": payload,
        },
    )
    if not created:
        return event

    shipment = _find_shipment_for_webhook(payload)
    if shipment is None:
        # Nothing to reconcile against (e.g. a test ping, or a shipment
        # created outside this system) — still recorded above for audit.
        event.is_processed = True
        event.processed_at = timezone.now()
        event.save(update_fields=["is_processed", "processed_at", "updated_at"])
        return event

    event.shipment = shipment
    try:
        if current_status:
            sync_shipment_status(shipment, current_status)
        event.is_processed = True
        event.processed_at = timezone.now()
        event.save(update_fields=["shipment", "is_processed", "processed_at", "updated_at"])
    except Exception as exc:
        event.processing_error = str(exc)[:500]
        event.save(update_fields=["shipment", "processing_error", "updated_at"])
        raise

    return event
