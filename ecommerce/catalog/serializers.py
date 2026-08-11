"""
catalog/serializers.py

DRF serializers for the catalog app.

Hierarchy:
  CategorySerializer           – flat + nested tree
  ProductImageSerializer       – image detail
  ProductVariantSerializer     – variant with computed fields
  ProductListSerializer        – lightweight product list
  ProductDetailSerializer      – full product with variants & images
  ProductCreateUpdateSerializer – write operations with validation
"""

from decimal import Decimal
from rest_framework import serializers
from .models import Category, Product, ProductVariant, ProductImage


# ---------------------------------------------------------------------------
# Category
# ---------------------------------------------------------------------------

class CategorySerializer(serializers.ModelSerializer):
    """
    Flat representation.  `children` is included for tree views.

    Example response:
    {
        "id": "3fa85f64-...",
        "name": "Beauty Care",
        "slug": "beauty-care",
        "description": "...",
        "image": "http://example.com/media/categories/beauty.jpg",
        "parent": null,
        "is_active": true,
        "children": [],
        "created_at": "2024-01-01T10:00:00Z",
        "updated_at": "2024-01-01T10:00:00Z"
    }
    """

    # Recursive children – only one level deep by default;
    # the /tree/ endpoint builds the full tree recursively in the view.
    children = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = [
            "id", "name", "slug", "description", "image",
            "parent", "is_active", "children",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "slug", "created_at", "updated_at"]

    def get_children(self, obj):
        active_children = obj.children.filter(is_active=True)
        return CategorySerializer(active_children, many=True, context=self.context).data


class CategoryCreateUpdateSerializer(serializers.ModelSerializer):
    """Lightweight serializer used for write operations (POST / PUT)."""

    class Meta:
        model = Category
        fields = [
            "name", "description", "image", "parent", "is_active",
        ]

    def validate_parent(self, value):
        """Prevent a category from being its own parent."""
        if value and self.instance and value.pk == self.instance.pk:
            raise serializers.ValidationError(
                "A category cannot be its own parent."
            )
        return value


# ---------------------------------------------------------------------------
# ProductImage
# ---------------------------------------------------------------------------

class ProductImageSerializer(serializers.ModelSerializer):
    """
    Example response:
    {
        "id": "...",
        "image": "http://example.com/media/products/img.jpg",
        "alt_text": "Rose Face Cream",
        "sort_order": 0,
        "variant": null,
        "created_at": "2024-01-01T10:00:00Z"
    }
    """

    class Meta:
        model = ProductImage
        fields = [
            "id", "product", "variant", "image",
            "alt_text", "sort_order", "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class ProductImageCreateSerializer(serializers.ModelSerializer):
    """Used when uploading images via /api/products/{id}/images/."""

    class Meta:
        model = ProductImage
        fields = ["variant", "image", "alt_text", "sort_order"]


# ---------------------------------------------------------------------------
# ProductVariant
# ---------------------------------------------------------------------------

class ProductVariantSerializer(serializers.ModelSerializer):
    """
    Full variant with computed fields.

    Example response:
    {
        "id": "...",
        "name": "500ml Lavender",
        "sku": "LVD-500-LAV",
        "attributes": {"size": "500ml", "fragrance": "lavender"},
        "price": "12.99",
        "sale_price": "9.99",
        "effective_price": "9.99",
        "discount_percentage": 23.1,
        "stock_quantity": 150,
        "in_stock": true,
        "weight": "0.550",
        "is_default": true,
        "is_active": true,
        "images": [...],
        "created_at": "2024-01-01T10:00:00Z",
        "updated_at": "2024-01-01T10:00:00Z"
    }
    """

    effective_price = serializers.SerializerMethodField()
    discount_percentage = serializers.SerializerMethodField()
    in_stock = serializers.SerializerMethodField()
    images = ProductImageSerializer(many=True, read_only=True)

    class Meta:
        model = ProductVariant
        fields = [
            "id", "name", "sku", "attributes",
            "price", "sale_price", "effective_price", "discount_percentage",
            "stock_quantity", "in_stock",
            "weight", "is_default", "is_active",
            "images",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "effective_price", "discount_percentage",
                            "in_stock", "created_at", "updated_at"]

    def get_effective_price(self, obj):
        return str(obj.effective_price)

    def get_discount_percentage(self, obj):
        if obj.sale_price:
            discount = ((obj.price - obj.sale_price) / obj.price) * 100
            return round(float(discount), 1)
        return 0

    def get_in_stock(self, obj):
        return obj.stock_quantity > 0


class ProductVariantCreateUpdateSerializer(serializers.ModelSerializer):
    """Write serializer for variants; validates sale_price and duplicates."""

    class Meta:
        model = ProductVariant
        fields = [
            "name", "sku", "attributes",
            "price", "sale_price",
            "stock_quantity", "weight",
            "is_default", "is_active",
        ]

    def validate(self, data):
        price = data.get("price", getattr(self.instance, "price", None))
        sale_price = data.get("sale_price", getattr(self.instance, "sale_price", None))

        if sale_price is not None and sale_price > price:
            raise serializers.ValidationError(
                {"sale_price": "sale_price must be <= price."}
            )
        return data


# ---------------------------------------------------------------------------
# Product – List (lightweight)
# ---------------------------------------------------------------------------

class ProductListSerializer(serializers.ModelSerializer):
    """
    Minimal representation for list endpoints (fast queries).

    Example response item:
    {
        "id": "...",
        "name": "Rose Face Cream",
        "slug": "rose-face-cream",
        "sku": "RFC-001",
        "brand": "Botanica",
        "category": {"id": "...", "name": "Skin Care", "slug": "skin-care"},
        "base_price": "15.99",
        "sale_price": "12.99",
        "effective_price": "12.99",
        "discount_percentage": 18.8,
        "is_featured": true,
        "primary_image": "http://example.com/media/products/img.jpg",
        "in_stock": true
    }
    """

    category = serializers.SerializerMethodField()
    effective_price = serializers.SerializerMethodField()
    discount_percentage = serializers.SerializerMethodField()
    primary_image = serializers.SerializerMethodField()
    in_stock = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id", "name", "slug", "sku", "brand",
            "category",
            "base_price", "sale_price", "effective_price", "discount_percentage",
            "is_featured", "primary_image", "in_stock",
            "created_at",
        ]

    def get_category(self, obj):
        return {"id": obj.category.id, "name": obj.category.name,
                "slug": obj.category.slug}

    def get_effective_price(self, obj):
        return str(obj.effective_price)

    def get_discount_percentage(self, obj):
        return obj.discount_percentage

    def get_primary_image(self, obj):
        img = obj.images.order_by("sort_order").first()
        if img:
            request = self.context.get("request")
            return request.build_absolute_uri(img.image.url) if request else img.image.url
        return None

    def get_in_stock(self, obj):
        return obj.variants.filter(is_active=True, stock_quantity__gt=0).exists()


# ---------------------------------------------------------------------------
# Product – Detail (full)
# ---------------------------------------------------------------------------

class ProductDetailSerializer(serializers.ModelSerializer):
    """
    Full product detail including nested variants and images.
    """

    category = CategorySerializer(read_only=True)
    variants = ProductVariantSerializer(many=True, read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    effective_price = serializers.SerializerMethodField()
    discount_percentage = serializers.SerializerMethodField()
    in_stock = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id", "name", "slug", "sku", "brand",
            "category",
            "description", "short_description",
            "base_price", "sale_price", "effective_price", "discount_percentage",
            "is_featured", "is_active",
            "images", "variants",
            "in_stock",
            "created_at", "updated_at",
        ]

    def get_effective_price(self, obj):
        return str(obj.effective_price)

    def get_discount_percentage(self, obj):
        return obj.discount_percentage

    def get_in_stock(self, obj):
        return obj.variants.filter(is_active=True, stock_quantity__gt=0).exists()


# ---------------------------------------------------------------------------
# Product – Create / Update
# ---------------------------------------------------------------------------

class ProductCreateUpdateSerializer(serializers.ModelSerializer):
    """
    Write serializer with full validation.

    Example request body (POST /api/products/):
    {
        "category": "3fa85f64-...",
        "name": "Rose Face Cream",
        "sku": "RFC-001",
        "brand": "Botanica",
        "description": "Nourishing rose cream...",
        "short_description": "Hydrating daily face cream.",
        "base_price": "15.99",
        "sale_price": "12.99",
        "is_featured": false,
        "is_active": true
    }
    """

    class Meta:
        model = Product
        fields = [
            "category", "name", "sku", "brand",
            "description", "short_description",
            "base_price", "sale_price",
            "is_featured", "is_active",
        ]

    def validate(self, data):
        base_price = data.get(
            "base_price", getattr(self.instance, "base_price", None)
        )
        sale_price = data.get(
            "sale_price", getattr(self.instance, "sale_price", None)
        )
        if sale_price is not None and base_price is not None:
            if Decimal(str(sale_price)) > Decimal(str(base_price)):
                raise serializers.ValidationError(
                    {"sale_price": "sale_price must be less than or equal to base_price."}
                )
        return data

    def validate_category(self, value):
        if not value.is_active:
            raise serializers.ValidationError("Cannot assign product to an inactive category.")
        return value

    def to_representation(self, instance):
        """Return the full detail representation after create/update."""
        return ProductDetailSerializer(instance, context=self.context).data
