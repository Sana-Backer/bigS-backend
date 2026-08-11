from django.contrib import admin

from .models import Coupon, CouponUsage


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = (
        "code", "discount_type", "discount_value",
        "used_count", "usage_limit", "is_active", "valid_from", "valid_until",
    )
    list_filter = ("discount_type", "is_active")
    search_fields = ("code", "description")
    readonly_fields = ("id", "used_count", "created_at", "updated_at")


@admin.register(CouponUsage)
class CouponUsageAdmin(admin.ModelAdmin):
    list_display = ("coupon", "user", "guest_session", "confirmed", "used_at")
    list_filter = ("confirmed",)
    search_fields = ("coupon__code", "user__email")
    readonly_fields = ("id", "created_at", "updated_at")
