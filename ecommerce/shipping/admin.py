from django.contrib import admin

from .models import Shipment, ShiprocketWebhookEvent


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = (
        "order", "status", "awb_code", "courier_name",
        "shiprocket_order_id", "created_at",
    )
    list_filter = ("status",)
    search_fields = (
        "order__order_number", "awb_code", "shiprocket_order_id", "shiprocket_shipment_id",
    )
    readonly_fields = (
        "id", "raw_create_response", "raw_tracking_response",
        "created_at", "updated_at",
    )


@admin.register(ShiprocketWebhookEvent)
class ShiprocketWebhookEventAdmin(admin.ModelAdmin):
    list_display = ("current_status", "awb_code", "shipment", "is_processed", "created_at")
    list_filter = ("is_processed",)
    search_fields = ("awb_code", "shiprocket_order_id", "dedup_key")
    readonly_fields = ("id", "dedup_key", "payload", "processed_at", "created_at", "updated_at")
