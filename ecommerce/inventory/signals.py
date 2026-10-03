"""
inventory/signals.py

Safety net: if somebody changes stock_quantity with a plain .save() (Django
admin, the catalog API, the Excel catalog importer…) the change is still
written to the ledger, as an EXTERNAL movement. Writes made through
inventory.services use queryset.update() and never reach this code.

Disable with INVENTORY_LOG_EXTERNAL_CHANGES = False.
"""

from django.conf import settings
from django.db.models.signals import post_init, post_save
from django.dispatch import receiver

from catalog.models import Product, ProductVariant

from .models import StockMovement


def _enabled():
    return getattr(settings, "INVENTORY_LOG_EXTERNAL_CHANGES", True)


@receiver(post_init, sender=Product)
@receiver(post_init, sender=ProductVariant)
def remember_stock(sender, instance, **kwargs):
    # __dict__ lookup so deferred (.only()/.defer()) instances don't trigger a query.
    instance._inv_stock = instance.__dict__.get("stock_quantity")


@receiver(post_save, sender=Product)
@receiver(post_save, sender=ProductVariant)
def log_external_change(sender, instance, created, raw=False, **kwargs):
    if raw or not _enabled():
        return
    new = instance.stock_quantity
    old = 0 if created else getattr(instance, "_inv_stock", None)
    instance._inv_stock = new
    if old is None or old == new:
        return

    is_variant = sender is ProductVariant
    product = instance.product if is_variant else instance
    StockMovement.objects.create(
        product=product, variant=instance if is_variant else None,
        sku=instance.sku,
        item_name=f"{product.name} – {instance.name}" if is_variant else product.name,
        movement_type=StockMovement.Type.INITIAL if created else StockMovement.Type.EXTERNAL,
        quantity_change=new - old, quantity_before=old, quantity_after=new,
        note="Created with opening stock" if created else "Changed outside the inventory app",
    )
