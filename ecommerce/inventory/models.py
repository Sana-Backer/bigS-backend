"""
inventory/models.py

Design
------
Stock itself still lives where the rest of the project already reads it:

  * ProductVariant.stock_quantity  – for products that have variants
  * Product.stock_quantity         – for products without variants

This app does NOT move that data (cart, checkout, orders and the dashboard
keep working untouched). It adds everything around it:

  StockMovement      – immutable ledger: every change, who/why/when
  StockPolicy        – per-item low-stock threshold, reorder qty, supplier
  Supplier           – who you buy from
  PurchaseOrder(+Item) – restock orders; receiving one writes ledger rows
"""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from catalog.models import Product, ProductVariant


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


def _exactly_one(product, variant, label):
    if bool(product) == bool(variant):
        raise ValidationError(f"{label} must be linked to exactly one of product or variant.")


# ---------------------------------------------------------------------------
# Supplier
# ---------------------------------------------------------------------------

class Supplier(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, unique=True)
    contact_name = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    lead_time_days = models.PositiveSmallIntegerField(
        default=7, help_text="Typical days from placing a purchase order to receiving it."
    )
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# StockPolicy
# ---------------------------------------------------------------------------

class StockPolicy(TimeStampedModel):
    """Thresholds for one stock unit (a variant, or a variant-less product)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.OneToOneField(
        Product, null=True, blank=True, on_delete=models.CASCADE, related_name="stock_policy"
    )
    variant = models.OneToOneField(
        ProductVariant, null=True, blank=True, on_delete=models.CASCADE, related_name="stock_policy"
    )
    low_stock_threshold = models.PositiveIntegerField(
        default=10, help_text="At or below this quantity the item is flagged as low stock."
    )
    reorder_quantity = models.PositiveIntegerField(
        default=0, help_text="Suggested quantity to order when restocking (0 = no suggestion)."
    )
    preferred_supplier = models.ForeignKey(
        Supplier, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "Stock policy"
        verbose_name_plural = "Stock policies"
        constraints = [
            models.CheckConstraint(
                condition=(Q(product__isnull=False, variant__isnull=True)
                           | Q(product__isnull=True, variant__isnull=False)),
                name="inv_policy_exactly_one_target",
            ),
        ]

    def clean(self):
        _exactly_one(self.product_id, self.variant_id, "A stock policy")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Policy for {self.variant or self.product}"


# ---------------------------------------------------------------------------
# StockMovement  (append-only ledger)
# ---------------------------------------------------------------------------

class StockMovement(models.Model):
    class Type(models.TextChoices):
        INITIAL = "initial", "Initial stock"
        PURCHASE_RECEIPT = "purchase_receipt", "Purchase receipt"
        SALE = "sale", "Sale"
        ORDER_CANCEL = "order_cancel", "Order cancelled (restock)"
        RETURN = "return", "Customer return"
        ADJUSTMENT = "adjustment", "Manual adjustment"
        DAMAGE = "damage", "Damaged / expired / lost"
        STOCKTAKE = "stocktake", "Stocktake correction"
        EXTERNAL = "external", "Edited outside inventory (admin/API/import)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Nullable + SET_NULL so deleting a product never erases history; the
    # sku/item_name snapshots keep old rows readable.
    product = models.ForeignKey(
        Product, null=True, blank=True, on_delete=models.SET_NULL, related_name="stock_movements"
    )
    variant = models.ForeignKey(
        ProductVariant, null=True, blank=True, on_delete=models.SET_NULL, related_name="stock_movements"
    )
    sku = models.CharField(max_length=100, db_index=True)
    item_name = models.CharField(max_length=620)

    movement_type = models.CharField(max_length=20, choices=Type.choices, db_index=True)
    quantity_change = models.IntegerField(help_text="Positive = stock in, negative = stock out.")
    quantity_before = models.PositiveIntegerField()
    quantity_after = models.PositiveIntegerField()

    reference = models.CharField(
        max_length=100, blank=True, db_index=True,
        help_text="Order number, purchase order number, etc.",
    )
    note = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["variant", "-created_at"]),
            models.Index(fields=["product", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.sku} {self.quantity_change:+d} ({self.movement_type})"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Stock movements are immutable.")
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Purchase orders
# ---------------------------------------------------------------------------

class PurchaseOrder(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ORDERED = "ordered", "Ordered"
        PARTIAL = "partially_received", "Partially received"
        RECEIVED = "received", "Received"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    po_number = models.CharField(max_length=30, unique=True, blank=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchase_orders")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    expected_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    ordered_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.po_number or str(self.id)

    def save(self, *args, **kwargs):
        if not self.po_number:
            from django.utils import timezone
            stamp = timezone.now().strftime("%Y%m%d")
            self.po_number = f"PO-{stamp}-{uuid.uuid4().hex[:6].upper()}"
        super().save(*args, **kwargs)

    @property
    def total_cost(self):
        return sum((i.quantity_ordered * i.unit_cost for i in self.items.all()), 0)


class PurchaseOrderItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    variant = models.ForeignKey(ProductVariant, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    sku = models.CharField(max_length=100)
    item_name = models.CharField(max_length=620)
    quantity_ordered = models.PositiveIntegerField()
    quantity_received = models.PositiveIntegerField(default=0)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(Q(product__isnull=False, variant__isnull=True)
                           | Q(product__isnull=True, variant__isnull=False)),
                name="inv_poitem_exactly_one_target",
            ),
        ]

    def clean(self):
        _exactly_one(self.product_id, self.variant_id, "A purchase order line")
        if self.quantity_received > self.quantity_ordered:
            raise ValidationError("quantity_received cannot exceed quantity_ordered.")

    @property
    def quantity_outstanding(self):
        return self.quantity_ordered - self.quantity_received

    def __str__(self):
        return f"{self.sku} x{self.quantity_ordered}"
