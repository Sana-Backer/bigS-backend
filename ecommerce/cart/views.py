"""
cart/views.py

APIView-based cart endpoints. Permission reused from the existing
users.permissions module: IsAuthenticatedOrGuest already implements
"authenticated user OR valid X-Guest-Token" exactly as required here.
"""

from django.db import transaction
from rest_framework.views import APIView

from common.responses import created, no_content, ok
from users.permissions import IsAuthenticatedOrGuest

from . import selectors, services
from .pricing import calculate_cart_totals
from .serializers import (
    AddCartItemSerializer,
    CartItemSerializer,
    CartSerializer,
    CartSummarySerializer,
    UpdateCartItemSerializer,
)


class CartMixin:
    """Resolves request -> (cart) once, shared by every cart view."""

    permission_classes = [IsAuthenticatedOrGuest]

    def get_cart(self, request):
        user, guest_session = selectors.resolve_owner(request)
        return services.get_or_create_cart(user=user, guest_session=guest_session)


class CartDetailView(CartMixin, APIView):
    """GET /api/cart/ — return the current cart."""

    def get(self, request):
        cart = self.get_cart(request)
        cart = selectors.get_cart_queryset().get(pk=cart.pk)  # reload w/ prefetches
        return ok(CartSerializer(cart, context={"request": request}).data, "Cart retrieved successfully.")


class CartItemListCreateView(CartMixin, APIView):
    """POST /api/cart/items/ — add an item (merges into existing line if present)."""

    @transaction.atomic
    def post(self, request):
        serializer = AddCartItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cart = self.get_cart(request)
        item = services.add_item(
            cart,
            product_id=serializer.validated_data["product_id"],
            variant_id=serializer.validated_data.get("variant_id"),
            quantity=serializer.validated_data["quantity"],
        )
        return created(CartItemSerializer(item, context={"request": request}).data, "Item added to cart.")


class CartItemDetailView(CartMixin, APIView):
    """
    PATCH  /api/cart/items/<uuid:id>/ — update quantity.
    DELETE /api/cart/items/<uuid:id>/ — remove item.
    """

    @transaction.atomic
    def patch(self, request, id):
        serializer = UpdateCartItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cart = self.get_cart(request)
        item = services.update_item_quantity(cart, id, serializer.validated_data["quantity"])
        return ok(CartItemSerializer(item, context={"request": request}).data, "Cart item updated.")

    @transaction.atomic
    def delete(self, request, id):
        cart = self.get_cart(request)
        services.remove_item(cart, id)
        return no_content("Item removed from cart.")


class CartClearView(CartMixin, APIView):
    """DELETE /api/cart/clear/ — remove all items (and any applied coupon)."""

    @transaction.atomic
    def delete(self, request):
        cart = self.get_cart(request)
        services.clear_cart(cart)
        return no_content("Cart cleared.")


class CartSummaryView(CartMixin, APIView):
    """GET /api/cart/summary/ — totals for the current cart."""

    def get(self, request):
        cart = self.get_cart(request)
        totals = calculate_cart_totals(cart)
        return ok(CartSummarySerializer(totals).data, "Cart summary retrieved successfully.")
