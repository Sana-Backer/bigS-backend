"""
checkout/views.py
"""

from rest_framework.views import APIView

from cart import selectors as cart_selectors
from cart import services as cart_services
from common.responses import created, ok
from orders.serializers import OrderSerializer
from users.permissions import IsAuthenticatedOrGuest

from . import services
from .serializers import (
    CheckoutQuoteSerializer,
    CheckoutValidateSerializer,
    CreateOrderSerializer,
)


class CheckoutMixin:
    permission_classes = [IsAuthenticatedOrGuest]

    def get_owner_and_cart(self, request):
        user, guest_session = cart_selectors.resolve_owner(request)
        cart = cart_services.get_or_create_cart(user=user, guest_session=guest_session)
        return user, guest_session, cart


class CheckoutValidateView(CheckoutMixin, APIView):
    """POST /api/checkout/validate/"""

    def post(self, request):
        serializer = CheckoutValidateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _, _, cart = self.get_owner_and_cart(request)
        result = services.validate_cart_for_checkout(cart)
        message = "Checkout validation successful." if result["is_valid"] else "Checkout validation failed."
        return ok(result, message)


class CheckoutQuoteView(CheckoutMixin, APIView):
    """POST /api/checkout/quote/"""

    def post(self, request):
        serializer = CheckoutQuoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _, _, cart = self.get_owner_and_cart(request)
        totals = services.quote(cart, coupon_code=serializer.validated_data.get("coupon_code"))
        return ok(totals, "Quote calculated successfully.")


class CreateOrderView(CheckoutMixin, APIView):
    """POST /api/checkout/create-order/"""

    def post(self, request):
        serializer = CreateOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, guest_session, cart = self.get_owner_and_cart(request)
        order = services.create_order(
            user=user, guest_session=guest_session, cart=cart,
            data=serializer.validated_data,
        )
        return created(OrderSerializer(order).data, "Order created successfully.")
