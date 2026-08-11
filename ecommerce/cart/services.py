"""
cart/services.py

Mutating operations on carts. All multi-row writes are wrapped in
transaction.atomic() and select_for_update() is used when touching
stock-sensitive rows, to keep concurrent add-to-cart requests safe.
"""

from decimal import Decimal

from django.db import transaction

from catalog.models import Product, ProductVariant

from .exceptions import (
    CartEmpty,
    InsufficientStock,
    ProductUnavailable,
    VariantUnavailable,
)
from .models import Cart, CartItem
from .pricing import current_unit_price


@transaction.atomic
def get_or_create_cart(user=None, guest_session=None) -> Cart:
    """Get the owner's active cart, creating one if it doesn't exist yet."""
    if user is not None:
        cart, _ = Cart.objects.get_or_create(
            user=user, defaults={"status": Cart.Status.ACTIVE}
        )
        return cart
    cart, _ = Cart.objects.get_or_create(
        guest_session=guest_session, defaults={"status": Cart.Status.ACTIVE}
    )
    return cart


def _validate_product_and_variant(product_id, variant_id):
    try:
        product = Product.objects.select_related("category").get(id=product_id)
    except Product.DoesNotExist:
        raise ProductUnavailable("Product not found.")
    if not product.is_active:
        raise ProductUnavailable("This product is no longer available.")

    variant = None
    if variant_id:
        try:
            variant = ProductVariant.objects.get(id=variant_id)
        except ProductVariant.DoesNotExist:
            raise VariantUnavailable("Product variant not found.")
        if variant.product_id != product.id:
            raise VariantUnavailable("This variant does not belong to the selected product.")
        if not variant.is_active:
            raise VariantUnavailable("This product variant is no longer available.")

    return product, variant


def _available_stock(product, variant):
    # Stock is tracked on the variant. Products without variants are
    # treated as always-available (no stock field on Product itself);
    # adjust here if/when Product gains its own stock_quantity.
    if variant is not None:
        return variant.stock_quantity
    return None  # None == not stock-tracked at the product level


@transaction.atomic
def add_item(cart: Cart, product_id, variant_id, quantity: int) -> CartItem:
    if quantity <= 0:
        from rest_framework.exceptions import ValidationError
        raise ValidationError({"quantity": ["Quantity must be greater than zero."]})

    product, variant = _validate_product_and_variant(product_id, variant_id)

    # Lock existing row (if any) to avoid a race between two concurrent
    # "add same item twice" requests.
    existing = (
        cart.items.select_for_update()
        .filter(product=product, variant=variant)
        .first()
    )

    new_quantity = quantity + (existing.quantity if existing else 0)

    available = _available_stock(product, variant)
    if available is not None and new_quantity > available:
        raise InsufficientStock(
            f"Only {available} unit(s) available for this item."
        )

    price = current_unit_price_for(product, variant)

    if existing:
        existing.quantity = new_quantity
        existing.unit_price = price
        existing.save(update_fields=["quantity", "unit_price", "updated_at"])
        return existing

    return CartItem.objects.create(
        cart=cart,
        product=product,
        variant=variant,
        quantity=quantity,
        unit_price=price,
    )


def current_unit_price_for(product, variant):
    if variant is not None:
        return Decimal(variant.effective_price)
    return Decimal(product.effective_price)


@transaction.atomic
def update_item_quantity(cart: Cart, item_id, quantity: int) -> CartItem:
    if quantity <= 0:
        from rest_framework.exceptions import ValidationError
        raise ValidationError({"quantity": ["Quantity must be greater than zero."]})

    from django.shortcuts import get_object_or_404

    item = get_object_or_404(
        cart.items.select_for_update().select_related("product", "variant"),
        id=item_id,
    )

    available = _available_stock(item.product, item.variant)
    if available is not None and quantity > available:
        raise InsufficientStock(f"Only {available} unit(s) available for this item.")

    item.quantity = quantity
    item.unit_price = current_unit_price(item)
    item.save(update_fields=["quantity", "unit_price", "updated_at"])
    return item


@transaction.atomic
def remove_item(cart: Cart, item_id):
    cart.items.filter(id=item_id).delete()


@transaction.atomic
def clear_cart(cart: Cart):
    cart.items.all().delete()
    if cart.coupon_id:
        cart.coupon = None
        cart.save(update_fields=["coupon", "updated_at"])


def ensure_not_empty(cart: Cart):
    if not cart.items.exists():
        raise CartEmpty()
