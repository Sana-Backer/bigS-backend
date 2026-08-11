from django.contrib import admin

from .models import Order, OrderItem, OrderStatusHistory


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("id", "product", "variant", "product_name", "variant_name", "sku", "unit_price", "quantity", "total_price")
    can_delete = False


class OrderStatusHistoryInline(admin.TabularInline):
    model = OrderStatusHistory
    extra = 0
    readonly_fields = ("status_type", "old_status", "new_status", "changed_by", "reason", "created_at")
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_number", "customer_email", "status", "payment_status",
        "fulfillment_status", "total_amount", "created_at",
    )
    list_filter = ("status", "payment_status", "fulfillment_status")
    search_fields = ("order_number", "customer_email", "user__email")
    readonly_fields = (
        "id", "order_number", "subtotal", "discount_amount", "shipping_amount",
        "tax_amount", "total_amount", "billing_address_snapshot",
        "shipping_address_snapshot", "created_at", "updated_at",
    )
    inlines = [OrderItemInline, OrderStatusHistoryInline]


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("order", "product_name", "variant_name", "quantity", "unit_price", "total_price")
    search_fields = ("order__order_number", "product_name", "sku")


@admin.register(OrderStatusHistory)
class OrderStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("order", "status_type", "old_status", "new_status", "changed_by", "created_at")
    list_filter = ("status_type",)
    search_fields = ("order__order_number",)
