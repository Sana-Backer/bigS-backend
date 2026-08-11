"""
payments/views.py

Customer/guest-facing:
  POST /api/payments/razorpay/create/
  POST /api/payments/razorpay/verify/

Staff/admin-triggered (refunds are a financial action, never exposed
to a plain customer):
  POST /api/payments/razorpay/refund/

Public (no auth — verified via Razorpay's own signature instead):
  POST /api/payments/webhooks/razorpay/

Admin (reuses users.permissions.IsManagerOrAdmin, same rationale as
orders/views.py's admin surface — "viewing all orders, financial
reports" covers payments too):
  GET  /api/admin/payments/
  GET  /api/admin/payments/<uuid:id>/
  POST /api/admin/orders/<uuid:order_id>/refund/
"""

from django.conf import settings
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from cart import selectors as cart_selectors
from catalog.pagination import StandardResultsPagination
from common.responses import created, ok
from orders import selectors as order_selectors
from users.permissions import IsAuthenticatedOrGuest, IsManagerOrAdmin

from . import selectors, services
from .exceptions import WebhookEventIdMissing, WebhookSignatureMissing
from .serializers import (
    AdminOrderRefundSerializer,
    PaymentTransactionSerializer,
    RazorpayCreateOrderSerializer,
    RazorpayRefundSerializer,
    RazorpayVerifyPaymentSerializer,
)

# ---------------------------------------------------------------------------
# Customer / guest facing
# ---------------------------------------------------------------------------


class RazorpayCreateOrderView(APIView):
    """POST /api/payments/razorpay/create/"""

    permission_classes = [IsAuthenticatedOrGuest]

    def post(self, request):
        serializer = RazorpayCreateOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user, guest_session = cart_selectors.resolve_owner(request)
        order = order_selectors.get_order_for_owner(
            serializer.validated_data["order_id"], user=user, guest_session=guest_session,
        )
        txn, _created = services.get_or_create_razorpay_order(
            order=order, user=user, guest_session=guest_session,
        )

        data = {
            "razorpay_order_id": txn.razorpay_order_id,
            "amount": txn.amount_paise,
            "currency": txn.currency,
            "key_id": settings.RAZORPAY_KEY_ID,
            "order_id": str(order.id),
            "order_number": order.order_number,
        }
        return created(data, "Razorpay order created successfully.")


class RazorpayVerifyPaymentView(APIView):
    """POST /api/payments/razorpay/verify/"""

    permission_classes = [IsAuthenticatedOrGuest]

    def post(self, request):
        serializer = RazorpayVerifyPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user, guest_session = cart_selectors.resolve_owner(request)
        txn = services.verify_payment(
            razorpay_order_id=serializer.validated_data["razorpay_order_id"],
            razorpay_payment_id=serializer.validated_data["razorpay_payment_id"],
            razorpay_signature=serializer.validated_data["razorpay_signature"],
            user=user,
            guest_session=guest_session,
        )
        return ok(PaymentTransactionSerializer(txn).data, "Payment verified successfully.")


class RazorpayRefundView(APIView):
    """POST /api/payments/razorpay/refund/ — staff/admin only."""

    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def post(self, request):
        serializer = RazorpayRefundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order = order_selectors.get_order_for_admin(serializer.validated_data["order_id"])
        txn = selectors.get_active_payment_transaction_for_order(order)
        txn = services.process_refund(
            payment_transaction=txn,
            amount=serializer.validated_data.get("amount"),
            initiated_by=request.user,
            reason=serializer.validated_data.get("reason", ""),
        )
        return ok(PaymentTransactionSerializer(txn).data, "Refund processed successfully.")


# ---------------------------------------------------------------------------
# Webhook (public — authenticity comes from the Razorpay signature, not DRF auth)
# ---------------------------------------------------------------------------


class RazorpayWebhookView(APIView):
    """POST /api/payments/webhooks/razorpay/"""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        signature = request.headers.get("X-Razorpay-Signature", "")
        event_id = request.headers.get("X-Razorpay-Event-Id", "")

        if not signature:
            raise WebhookSignatureMissing()
        if not event_id:
            raise WebhookEventIdMissing()

        services.process_webhook_event(raw_body=request.body, signature=signature, event_id=event_id)
        return ok({}, "Webhook processed.")


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


class AdminPaymentListView(APIView):
    """GET /api/admin/payments/"""

    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def get(self, request):
        qs = selectors.get_admin_payment_queryset(request.query_params)
        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(PaymentTransactionSerializer(page, many=True).data)


class AdminPaymentDetailView(APIView):
    """GET /api/admin/payments/<uuid:id>/"""

    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def get(self, request, id):
        txn = selectors.get_payment_transaction_for_admin(id)
        return ok(PaymentTransactionSerializer(txn).data)


class AdminOrderRefundView(APIView):
    """POST /api/admin/orders/<uuid:order_id>/refund/"""

    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def post(self, request, order_id):
        serializer = AdminOrderRefundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order = order_selectors.get_order_for_admin(order_id)
        txn = selectors.get_active_payment_transaction_for_order(order)
        txn = services.process_refund(
            payment_transaction=txn,
            amount=serializer.validated_data.get("amount"),
            initiated_by=request.user,
            reason=serializer.validated_data.get("reason", ""),
        )
        return ok(PaymentTransactionSerializer(txn).data, "Refund processed successfully.")
