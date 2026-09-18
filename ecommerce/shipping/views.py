"""
shipping/views.py

Public/customer-facing:
  GET  /api/shipping/serviceability/
  GET  /api/orders/<uuid:order_id>/tracking/

Public (no auth — verified via a shared Shiprocket webhook token instead,
same pattern as payments' Razorpay-signature-verified webhook):
  POST /api/shipping/webhooks/shiprocket/

Admin (reuses users.permissions.IsManagerOrAdmin, same rationale as
orders/views.py's and payments/views.py's admin surfaces):
  POST /api/admin/orders/<uuid:order_id>/shipping/create/
  POST /api/admin/shipments/<uuid:id>/assign-awb/
  POST /api/admin/shipments/<uuid:id>/label/
  POST /api/admin/shipments/<uuid:id>/manifest/
  GET  /api/admin/shipments/<uuid:id>/tracking/
  POST /api/admin/shipments/<uuid:id>/cancel/
"""

from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from cart import selectors as cart_selectors
from common.responses import created, ok
from orders import selectors as order_selectors
from users.permissions import IsAuthenticatedOrGuest, IsManagerOrAdmin

from . import selectors, services
from .exceptions import InvalidWebhookSignature
from .serializers import (
    AssignAWBSerializer,
    ServiceabilityQuerySerializer,
    ShipmentCancelSerializer,
    ShipmentCreateSerializer,
    ShipmentSerializer,
    ShipmentTrackingSerializer,
)

# ---------------------------------------------------------------------------
# Public / customer-facing
# ---------------------------------------------------------------------------


class ServiceabilityView(APIView):
    """GET /api/shipping/serviceability/"""

    permission_classes = [AllowAny]

    def get(self, request):
        serializer = ServiceabilityQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        result = services.check_serviceability(
            delivery_postcode=data["delivery_postcode"],
            weight=data.get("weight"),
            cod=data.get("cod", False),
            pickup_postcode=data.get("pickup_postcode") or None,
        )
        return ok(result, "Serviceability checked successfully.")


class OrderTrackingView(APIView):
    """GET /api/orders/<uuid:order_id>/tracking/ — the owning customer/guest only."""

    permission_classes = [IsAuthenticatedOrGuest]

    def get(self, request, order_id):
        user, guest_session = cart_selectors.resolve_owner(request)
        shipment = selectors.get_shipment_for_owner(order_id, user=user, guest_session=guest_session)
        return ok(ShipmentTrackingSerializer(shipment).data, "Tracking information retrieved successfully.")


# ---------------------------------------------------------------------------
# Webhook (public — authenticity comes from the shared Shiprocket webhook
# token, not DRF auth; see services.verify_webhook_token)
# ---------------------------------------------------------------------------


class ShiprocketWebhookView(APIView):
    """POST /api/shipping/webhooks/shiprocket/"""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.headers.get("X-Api-Key", "")
        if not services.verify_webhook_token(token):
            raise InvalidWebhookSignature()

        services.process_webhook_event(raw_body=request.body)
        return ok({}, "Webhook processed.")


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


class AdminCreateShipmentView(APIView):
    """POST /api/admin/orders/<uuid:order_id>/shipping/create/"""

    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def post(self, request, order_id):
        serializer = ShipmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order = order_selectors.get_order_for_admin(order_id)
        
        shipment = services.create_shipment_for_order(
            order,
            created_by=request.user,
            pickup_location=serializer.validated_data.get("pickup_location") or None,
        )
        return created(ShipmentSerializer(shipment).data, "Shipment created successfully.")


class AdminAssignAWBView(APIView):
    """POST /api/admin/shipments/<uuid:id>/assign-awb/"""

    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def post(self, request, id):
        serializer = AssignAWBSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        shipment = selectors.get_shipment_for_admin(id)
        shipment = services.assign_awb(
            shipment,
            courier_id=serializer.validated_data.get("courier_id") or None,
            changed_by=request.user,
        )
        return ok(ShipmentSerializer(shipment).data, "AWB assigned successfully.")


class AdminGenerateLabelView(APIView):
    """POST /api/admin/shipments/<uuid:id>/label/"""

    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def post(self, request, id):
        shipment = selectors.get_shipment_for_admin(id)
        shipment = services.generate_label(shipment)
        return ok(ShipmentSerializer(shipment).data, "Label generated successfully.")


class AdminGenerateManifestView(APIView):
    """POST /api/admin/shipments/<uuid:id>/manifest/"""

    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def post(self, request, id):
        shipment = selectors.get_shipment_for_admin(id)
        shipment = services.generate_manifest(shipment)
        return ok(ShipmentSerializer(shipment).data, "Manifest generated successfully.")


class AdminShipmentTrackingView(APIView):
    """GET /api/admin/shipments/<uuid:id>/tracking/"""

    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def get(self, request, id):
        shipment = selectors.get_shipment_for_admin(id)
        shipment = services.refresh_tracking(shipment)
        return ok(ShipmentTrackingSerializer(shipment).data, "Tracking information retrieved successfully.")


class AdminCancelShipmentView(APIView):
    """POST /api/admin/shipments/<uuid:id>/cancel/"""

    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def post(self, request, id):
        serializer = ShipmentCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        shipment = selectors.get_shipment_for_admin(id)
        shipment = services.cancel_shipment(
            shipment,
            changed_by=request.user,
            reason=serializer.validated_data.get("reason") or "Cancelled by admin.",
        )
        return ok(ShipmentSerializer(shipment).data, "Shipment cancelled successfully.")
