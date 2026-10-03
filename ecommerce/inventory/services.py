"""
inventory/services.py

All stock writes go through here so the ledger can never drift from the
stock_quantity columns.

    record_movement(target, change, movement_type, ...)  – relative change
    set_stock(target, quantity, ...)                     – absolute (stocktake)
    receive_purchase_order(po, lines, user)              – restock from a PO

`target` is a ProductVariant, or a Product that has no variants.
"""

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from catalog.models import Product, ProductVariant

from .exceptions import InsufficientStockError, InventoryError
from .models import PurchaseOrder, PurchaseOrderItem, StockMovement

M = StockMovement.Type


def default_low_stock_threshold() -> int:
    return getattr(settings, "INVENTORY_DEFAULT_LOW_STOCK_THRESHOLD", 10)


# ---------------------------------------------------------------------------
# Target helpers
# ---------------------------------------------------------------------------

def resolve_target(*, product_id=None, variant_id=None):
    """Return the ProductVariant or Product (variant-less) the caller means."""
    if bool(product_id) == bool(variant_id):
        raise InventoryError("Provide exactly one of product_id or variant_id.")
    if variant_id:
        try:
            return ProductVariant.objects.select_related("product").get(pk=variant_id)
        except ProductVariant.DoesNotExist:
            raise InventoryError("Variant not found.")
    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        raise InventoryError("Product not found.")
    if product.variants.exists():
        raise InventoryError(
            f"'{product.name}' has variants – stock is tracked per variant. "
            "Use variant_id instead."
        )
    return product


def _snapshot(target):
    if isinstance(target, ProductVariant):
        return {
            "variant": target, "product": target.product,
            "sku": target.sku, "item_name": f"{target.product.name} – {target.name}",
        }
    return {"variant": None, "product": target, "sku": target.sku, "item_name": target.name}


def _lock(target):
    model = type(target)
    return model.objects.select_for_update().get(pk=target.pk)


# ---------------------------------------------------------------------------
# Core writers
# ---------------------------------------------------------------------------

@transaction.atomic
def record_movement(target, change: int, movement_type: str, *, reference="", note="",
                    user=None, allow_negative=False) -> StockMovement:
    """Apply `change` (+in / -out) to the target's stock and log it atomically."""
    if not isinstance(change, int) or isinstance(change, bool):
        raise InventoryError("change must be an integer.")
    if change == 0:
        raise InventoryError("change must not be zero.")

    locked = _lock(target)
    before = locked.stock_quantity
    after = before + change
    if after < 0 and not allow_negative:
        raise InsufficientStockError(
            f"Cannot remove {-change} unit(s) of '{_snapshot(locked)['item_name']}': "
            f"only {before} on hand."
        )
    after = max(after, 0)

    # queryset.update(): skips model.save()/full_clean and our own post_save
    # signal (which would otherwise log this change a second time).
    type(locked).objects.filter(pk=locked.pk).update(stock_quantity=after, updated_at=timezone.now())
    target.stock_quantity = after
    if hasattr(target, "_inv_stock"):
        target._inv_stock = after

    return StockMovement.objects.create(
        movement_type=movement_type, quantity_change=after - before,
        quantity_before=before, quantity_after=after,
        reference=reference, note=note, created_by=user, **_snapshot(locked),
    )


@transaction.atomic
def set_stock(target, quantity: int, *, note="", reference="", user=None,
              movement_type=M.STOCKTAKE):
    """Set an absolute on-hand quantity (stocktake). Returns None if unchanged."""
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 0:
        raise InventoryError("quantity must be a non-negative integer.")
    locked = _lock(target)
    delta = quantity - locked.stock_quantity
    if delta == 0:
        return None
    return record_movement(target, delta, movement_type, reference=reference, note=note, user=user)


@transaction.atomic
def bulk_adjust(items, *, user=None):
    """
    items: list of dicts {target, change, movement_type, note, reference}.
    All-or-nothing: one bad line rolls the whole batch back.
    """
    return [
        record_movement(
            i["target"], i["change"], i["movement_type"],
            reference=i.get("reference", ""), note=i.get("note", ""), user=user,
        )
        for i in items
    ]


# ---------------------------------------------------------------------------
# Purchase orders
# ---------------------------------------------------------------------------

@transaction.atomic
def mark_ordered(po: PurchaseOrder) -> PurchaseOrder:
    po = PurchaseOrder.objects.select_for_update().get(pk=po.pk)
    if po.status != PurchaseOrder.Status.DRAFT:
        raise InventoryError("Only draft purchase orders can be marked as ordered.")
    if not po.items.exists():
        raise InventoryError("Add at least one line before ordering.")
    po.status = PurchaseOrder.Status.ORDERED
    po.ordered_at = timezone.now()
    po.save(update_fields=["status", "ordered_at", "updated_at"])
    return po


@transaction.atomic
def cancel_purchase_order(po: PurchaseOrder) -> PurchaseOrder:
    po = PurchaseOrder.objects.select_for_update().get(pk=po.pk)
    if po.status in (PurchaseOrder.Status.RECEIVED, PurchaseOrder.Status.CANCELLED):
        raise InventoryError(f"A {po.status} purchase order cannot be cancelled.")
    if po.status == PurchaseOrder.Status.PARTIAL:
        raise InventoryError("Partially received orders cannot be cancelled; receive the rest or adjust stock.")
    po.status = PurchaseOrder.Status.CANCELLED
    po.save(update_fields=["status", "updated_at"])
    return po


@transaction.atomic
def receive_purchase_order(po: PurchaseOrder, lines, *, user=None) -> PurchaseOrder:
    """
    lines: [{"item_id": <uuid>, "quantity": int}, ...]; pass None to receive
    everything still outstanding. Each line adds stock and writes a ledger row.
    """
    po = PurchaseOrder.objects.select_for_update().get(pk=po.pk)
    if po.status not in (PurchaseOrder.Status.ORDERED, PurchaseOrder.Status.PARTIAL):
        raise InventoryError("Only ordered / partially received purchase orders can receive stock.")

    items = {str(i.id): i for i in
             PurchaseOrderItem.objects.select_for_update()
             .select_related("product", "variant", "variant__product").filter(purchase_order=po)}

    if lines is None:
        lines = [{"item_id": k, "quantity": i.quantity_outstanding}
                 for k, i in items.items() if i.quantity_outstanding > 0]
    if not lines:
        raise InventoryError("Nothing to receive.")

    for line in lines:
        item = items.get(str(line["item_id"]))
        if item is None:
            raise InventoryError(f"Line {line['item_id']} does not belong to this purchase order.")
        qty = line["quantity"]
        if not isinstance(qty, int) or qty <= 0:
            raise InventoryError("Received quantity must be a positive integer.")
        if qty > item.quantity_outstanding:
            raise InventoryError(
                f"{item.sku}: receiving {qty} but only {item.quantity_outstanding} outstanding."
            )
        record_movement(item.variant or item.product, qty, M.PURCHASE_RECEIPT,
                        reference=po.po_number, note=f"Received from {po.supplier.name}", user=user)
        item.quantity_received += qty
        item.save(update_fields=["quantity_received"])

    done = all(i.quantity_received >= i.quantity_ordered for i in items.values())
    po.status = PurchaseOrder.Status.RECEIVED if done else PurchaseOrder.Status.PARTIAL
    if done:
        po.received_at = timezone.now()
    po.save(update_fields=["status", "received_at", "updated_at"])
    return po
