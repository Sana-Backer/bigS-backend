from django.contrib import admin

from .models import Cart, CartItem


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ("id", "owner_display", "status", "coupon", "updated_at")
    list_filter = ("status",)
    search_fields = ("user__email", "guest_session__email", "id")
    readonly_fields = ("id", "created_at", "updated_at")
    inlines = [CartItemInline]

    def owner_display(self, obj):
        return obj.user.email if obj.user_id else f"Guest: {obj.guest_session.email}"
    owner_display.short_description = "Owner"


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ("id", "cart", "product", "variant", "quantity", "unit_price")
    search_fields = ("product__name", "cart__id")
