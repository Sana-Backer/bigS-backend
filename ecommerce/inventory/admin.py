"""inventory/admin.py"""

from django.contrib import admin

from .models import PurchaseOrder, PurchaseOrderItem, StockMovement, StockPolicy, Supplier


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    """Read-only: the ledger is append-only. Use the API/services to change stock."""
    list_display = ["created_at", "sku", "item_name", "movement_type", "quantity_change",
                    "quantity_before", "quantity_after", "reference", "created_by"]
    list_filter = ["movement_type", "created_at"]
    search_fields = ["sku", "item_name", "reference", "note"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StockPolicy)
class StockPolicyAdmin(admin.ModelAdmin):
    list_display = ["__str__", "low_stock_threshold", "reorder_quantity", "preferred_supplier"]
    autocomplete_fields = ["product", "variant"]
    raw_id_fields = ["product", "variant"]


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ["name", "contact_name", "email", "phone", "lead_time_days", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "contact_name", "email"]


class PurchaseOrderItemInline(admin.TabularInline):
    model = PurchaseOrderItem
    extra = 0
    raw_id_fields = ["product", "variant"]
    readonly_fields = ["quantity_received"]


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    """Receive stock through the API (it writes ledger rows); status is read-only here."""
    list_display = ["po_number", "supplier", "status", "expected_date", "created_at"]
    list_filter = ["status", "supplier"]
    search_fields = ["po_number", "supplier__name"]
    readonly_fields = ["po_number", "status", "ordered_at", "received_at"]
    inlines = [PurchaseOrderItemInline]
