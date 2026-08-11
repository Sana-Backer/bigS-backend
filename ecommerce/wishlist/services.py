"""
wishlist/services.py
"""

from django.db import transaction
from django.shortcuts import get_object_or_404

from catalog.models import Product
from cart import services as cart_services

from .exceptions import ProductAlreadyInWishlist, ProductNotAvailable
from .models import Wishlist, WishlistItem


def get_or_create_wishlist(user) -> Wishlist:
    wishlist, _ = Wishlist.objects.get_or_create(user=user)
    return wishlist


@transaction.atomic
def add_item(wishlist: Wishlist, product_id) -> WishlistItem:
    product = get_object_or_404(Product, id=product_id)
    if not product.is_active:
        raise ProductNotAvailable()
    if WishlistItem.objects.filter(wishlist=wishlist, product=product).exists():
        raise ProductAlreadyInWishlist()
    return WishlistItem.objects.create(wishlist=wishlist, product=product)


def remove_item(wishlist: Wishlist, item_id):
    wishlist.items.filter(id=item_id).delete()


@transaction.atomic
def move_to_cart(wishlist: Wishlist, item_id, user, variant_id=None, quantity=1):
    """
    Validates availability, adds the product to the user's cart via the
    shared cart service (so pricing/stock rules are enforced in exactly
    one place), then removes it from the wishlist.
    """
    item = get_object_or_404(wishlist.items.select_related("product"), id=item_id)
    product = item.product

    if not product.is_active:
        raise ProductNotAvailable()

    cart = cart_services.get_or_create_cart(user=user)
    cart_item = cart_services.add_item(
        cart, product_id=product.id, variant_id=variant_id, quantity=quantity
    )
    item.delete()
    return cart_item
