from rest_framework import serializers

from .models import Wishlist, WishlistItem


class WishlistItemProductSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.SlugField()
    base_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    sale_price = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    is_active = serializers.BooleanField()
    primary_image = serializers.SerializerMethodField()
    in_stock = serializers.SerializerMethodField()

    def get_primary_image(self, obj):
        # obj is a Product instance (not a dict)
        img = obj.images.order_by("sort_order").first()
        if img:
            request = self.context.get("request")
            return request.build_absolute_uri(img.image.url) if request else img.image.url
        return None

    def get_in_stock(self, obj):
        return obj.variants.filter(is_active=True, stock_quantity__gt=0).exists()


class WishlistItemSerializer(serializers.ModelSerializer):
    product = WishlistItemProductSerializer(read_only=True)

    class Meta:
        model = WishlistItem
        fields = ["id", "product", "created_at"]
        read_only_fields = fields


class WishlistSerializer(serializers.ModelSerializer):
    items = WishlistItemSerializer(many=True, read_only=True)

    class Meta:
        model = Wishlist
        fields = ["id", "items", "created_at", "updated_at"]
        read_only_fields = fields


class AddWishlistItemSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()


class MoveToCartSerializer(serializers.Serializer):
    variant_id = serializers.UUIDField(required=False, allow_null=True)
    quantity = serializers.IntegerField(min_value=1, default=1)
