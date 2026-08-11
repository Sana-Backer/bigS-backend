"""
orders/views.py

Customer-facing:
  GET  /api/orders/
  GET  /api/orders/<uuid:id>/
  POST /api/orders/<uuid:id>/cancel/

Admin (reuses users.permissions.IsManagerOrAdmin — its own docstring
says "Use for: user management, viewing all orders, financial
reports.", which is exactly this surface):
  GET   /api/admin/orders/
  GET   /api/admin/orders/<uuid:id>/
  PATCH /api/admin/orders/<uuid:id>/status/
  PATCH /api/admin/orders/<uuid:id>/payment-status/
  PATCH /api/admin/orders/<uuid:id>/fulfillment-status/
  POST  /api/admin/orders/<uuid:id>/cancel/
"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from cart import selectors as cart_selectors
from catalog.pagination import StandardResultsPagination
from common.responses import ok
from users.permissions import IsAuthenticatedOrGuest, IsManagerOrAdmin

from . import selectors, services
from .serializers import (
    FulfillmentStatusUpdateSerializer,
    OrderCancelSerializer,
    OrderListItemSerializer,
    OrderSerializer,
    OrderStatusUpdateSerializer,
    PaymentStatusUpdateSerializer,
)


# ---------------------------------------------------------------------------
# Customer-facing
# ---------------------------------------------------------------------------

class OrderListView(APIView):
    """GET /api/orders/ — the current user/guest's own orders."""

    permission_classes = [IsAuthenticatedOrGuest]

    def get(self, request):
        user, guest_session = cart_selectors.resolve_owner(request)
        qs = selectors.get_orders_for_owner(user=user, guest_session=guest_session)
        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(OrderListItemSerializer(page, many=True).data)


class OrderDetailView(APIView):
    """GET /api/orders/<uuid:id>/"""

    permission_classes = [IsAuthenticatedOrGuest]

    def get(self, request, id):
        user, guest_session = cart_selectors.resolve_owner(request)
        order = selectors.get_order_for_owner(id, user=user, guest_session=guest_session)
        return ok(OrderSerializer(order).data, "Order retrieved successfully.")


class OrderCancelView(APIView):
    """POST /api/orders/<uuid:id>/cancel/"""

    permission_classes = [IsAuthenticatedOrGuest]

    def post(self, request, id):
        serializer = OrderCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user, guest_session = cart_selectors.resolve_owner(request)
        order = selectors.get_order_for_owner(id, user=user, guest_session=guest_session)
        order = services.cancel_order(
            order,
            changed_by=user,
            reason=serializer.validated_data.get("reason") or "Cancelled by customer.",
        )
        return ok(OrderSerializer(order).data, "Order cancelled successfully.")


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

class AdminOrderListView(APIView):
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def get(self, request):
        qs = selectors.get_admin_order_queryset(request.query_params)
        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(OrderListItemSerializer(page, many=True).data)


class AdminOrderDetailView(APIView):
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def get(self, request, id):
        order = selectors.get_order_for_admin(id)
        return ok(OrderSerializer(order).data)


class AdminOrderStatusUpdateView(APIView):
    """PATCH /api/admin/orders/<uuid:id>/status/"""

    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def patch(self, request, id):
        serializer = OrderStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = selectors.get_order_for_admin(id)
        order = services.change_order_status(
            order,
            serializer.validated_data["status"],
            changed_by=request.user,
            reason=serializer.validated_data.get("reason", ""),
        )
        return ok(OrderSerializer(order).data, "Order status updated.")


class AdminOrderPaymentStatusUpdateView(APIView):
    """PATCH /api/admin/orders/<uuid:id>/payment-status/"""

    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def patch(self, request, id):
        serializer = PaymentStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = selectors.get_order_for_admin(id)
        order = services.change_payment_status(
            order,
            serializer.validated_data["payment_status"],
            changed_by=request.user,
            reason=serializer.validated_data.get("reason", ""),
        )
        return ok(OrderSerializer(order).data, "Payment status updated.")


class AdminOrderFulfillmentStatusUpdateView(APIView):
    """PATCH /api/admin/orders/<uuid:id>/fulfillment-status/"""

    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def patch(self, request, id):
        serializer = FulfillmentStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = selectors.get_order_for_admin(id)
        order = services.change_fulfillment_status(
            order,
            serializer.validated_data["fulfillment_status"],
            changed_by=request.user,
            reason=serializer.validated_data.get("reason", ""),
        )
        return ok(OrderSerializer(order).data, "Fulfillment status updated.")


class AdminOrderCancelView(APIView):
    """POST /api/admin/orders/<uuid:id>/cancel/"""

    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def post(self, request, id):
        serializer = OrderCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = selectors.get_order_for_admin(id)
        order = services.cancel_order(
            order,
            changed_by=request.user,
            reason=serializer.validated_data.get("reason") or "Cancelled by admin.",
        )
        return ok(OrderSerializer(order).data, "Order cancelled successfully.")
