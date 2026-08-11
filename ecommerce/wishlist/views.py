"""
wishlist/views.py

Authenticated users only — reuses DRF's built-in IsAuthenticated
(no custom wishlist-specific permission needed, since every view scopes
strictly to request.user's own wishlist).
"""

from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from cart.serializers import CartItemSerializer
from common.responses import created, no_content, ok

from . import services
from .serializers import (
    AddWishlistItemSerializer,
    MoveToCartSerializer,
    WishlistSerializer,
)


class WishlistMixin:
    permission_classes = [IsAuthenticated]

    def get_wishlist(self, request):
        return services.get_or_create_wishlist(request.user)


class WishlistDetailView(WishlistMixin, APIView):
    """GET /api/wishlist/"""

    def get(self, request):
        wishlist = self.get_wishlist(request)
        return ok(WishlistSerializer(wishlist, context={"request": request}).data, "Wishlist retrieved successfully.")


class WishlistItemCreateView(WishlistMixin, APIView):
    """POST /api/wishlist/items/  Body: {"product_id": "uuid"}"""

    @transaction.atomic
    def post(self, request):
        serializer = AddWishlistItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        wishlist = self.get_wishlist(request)
        item = services.add_item(wishlist, serializer.validated_data["product_id"])
        from .serializers import WishlistItemSerializer
        return created(WishlistItemSerializer(item, context={"request": request}).data, "Product added to wishlist.")


class WishlistItemDestroyView(WishlistMixin, APIView):
    """DELETE /api/wishlist/items/<uuid:id>/"""

    def delete(self, request, id):
        wishlist = self.get_wishlist(request)
        services.remove_item(wishlist, id)
        return no_content("Item removed from wishlist.")


class WishlistItemMoveToCartView(WishlistMixin, APIView):
    """POST /api/wishlist/items/<uuid:id>/move-to-cart/"""

    @transaction.atomic
    def post(self, request, id):
        serializer = MoveToCartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        wishlist = self.get_wishlist(request)
        cart_item = services.move_to_cart(
            wishlist, id, request.user,
            variant_id=serializer.validated_data.get("variant_id"),
            quantity=serializer.validated_data["quantity"],
        )
        return ok(CartItemSerializer(cart_item, context={"request": request}).data, "Item moved to cart.")
