"""
catalog/admin.py

Django admin configuration for the catalog models.
"""

from django.contrib import admin
from django.utils.html import format_html
from .models import Category, Product, ProductVariant, ProductImage


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ["image", "alt_text", "sort_order", "variant"]
    readonly_fields = []


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0
    fields = [
        "name", "sku", "attributes",
        "price", "sale_price", "stock_quantity",
        "is_default", "is_active",
    ]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "parent", "is_active", "created_at"]
    list_filter = ["is_active", "parent"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}
    ordering = ["name"]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = [
        "name", "sku", "category", "brand",
        "base_price", "sale_price", "is_featured", "is_active",
    ]
    list_filter = ["is_active", "is_featured", "category", "brand"]
    search_fields = ["name", "sku", "brand", "slug"]
    prepopulated_fields = {"slug": ("name",)}
    inlines = [ProductVariantInline, ProductImageInline]
    ordering = ["-created_at"]


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = [
        "name", "product", "sku",
        "price", "sale_price", "stock_quantity",
        "is_default", "is_active",
    ]
    list_filter = ["is_active", "is_default"]
    search_fields = ["name", "sku"]


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ["id", "product", "variant", "alt_text", "sort_order"]
    list_filter = ["product"]
