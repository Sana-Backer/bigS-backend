from django.contrib import admin

from .models import PaymentTransaction, PaymentWebhookEvent


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "razorpay_order_id", "order", "status", "amount", "refunded_amount",
        "currency", "created_at",
    )
    list_filter = ("status", "provider", "currency")
    search_fields = ("razorpay_order_id", "razorpay_payment_id", "order__order_number")
    readonly_fields = (
        "id", "amount_paise", "processed_refund_ids", "verified_at",
        "created_at", "updated_at",
    )


@admin.register(PaymentWebhookEvent)
class PaymentWebhookEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "event_id", "is_processed", "payment_transaction", "created_at")
    list_filter = ("event_type", "is_processed", "provider")
    search_fields = ("event_id", "payment_transaction__razorpay_order_id")
    readonly_fields = ("id", "payload", "processed_at", "created_at", "updated_at")
