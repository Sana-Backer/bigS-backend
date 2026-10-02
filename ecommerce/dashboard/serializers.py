"""
dashboard/serializers.py

Every endpoint in this app is read-only and returns plain aggregated
dicts (Decimals, ints, date labels) rather than model instances, so
there are no output ModelSerializers here — only input serializers
that validate query parameters before a view calls into services.py.
"""

from rest_framework import serializers
from .models import Banner

PERIOD_CHOICES = ("today","7d","daily", "weekly", "monthly", "yearly")


class PeriodQuerySerializer(serializers.Serializer):
    period = serializers.ChoiceField(choices=PERIOD_CHOICES, required=False, default="today")


class DashboardOverviewQuerySerializer(serializers.Serializer):
    range = serializers.ChoiceField(choices=("7d", "30d", "90d", "1y"), required=False, default="30d")


class LimitQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(required=False, default=5, min_value=1, max_value=50)
    date_from = serializers.DateField(required=False, allow_null=True)
    date_to = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs):
        date_from, date_to = attrs.get("date_from"), attrs.get("date_to")
        if date_from and date_to and date_from > date_to:
            raise serializers.ValidationError("date_from must not be after date_to.")
        return attrs


class DateRangeQuerySerializer(serializers.Serializer):
    date_from = serializers.DateField(required=False, allow_null=True)
    date_to = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs):
        date_from, date_to = attrs.get("date_from"), attrs.get("date_to")
        if date_from and date_to and date_from > date_to:
            raise serializers.ValidationError("date_from must not be after date_to.")
        return attrs


class RevenueOverviewQuerySerializer(serializers.Serializer):
    months = serializers.IntegerField(required=False, default=7, min_value=1, max_value=24)


class RecentOrdersQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(required=False, default=10, min_value=1, max_value=100)


class SalesReportQuerySerializer(serializers.Serializer):
    date_from = serializers.DateField()
    date_to = serializers.DateField()
    group_by = serializers.ChoiceField(choices=("day", "week", "month"), required=False, default="day")

    def validate(self, attrs):
        if attrs["date_from"] > attrs["date_to"]:
            raise serializers.ValidationError("date_from must not be after date_to.")
        if (attrs["date_to"] - attrs["date_from"]).days > 366:
            raise serializers.ValidationError("Date range cannot exceed 366 days.")
        return attrs


class ProductReportQuerySerializer(DateRangeQuerySerializer):
    ordering = serializers.ChoiceField(
        choices=("revenue", "-revenue", "units_sold", "-units_sold", "orders_count", "-orders_count"),
        required=False, default="-revenue",
    )


class CustomerReportQuerySerializer(DateRangeQuerySerializer):
    ordering = serializers.ChoiceField(
        choices=("total_spent", "-total_spent", "orders_count", "-orders_count",
                 "last_order_at", "-last_order_at"),
        required=False, default="-total_spent",
    )


class InventoryReportQuerySerializer(serializers.Serializer):
    low_stock_threshold = serializers.IntegerField(required=False, default=10, min_value=0)

class BannerSerializer(serializers.ModelSerializer):
    """
    Full read representation — used by both the admin CRUD surface and
    the public storefront endpoint.
 
    Example response:
    {
        "id": "3fa85f64-...",
        "title": "Autumn Sale",
        "subtitle": "Up to 40% off",
        "image": "http://example.com/media/banners/autumn.jpg",
        "mobile_image": "http://example.com/media/banners/mobile/autumn.jpg",
        "link_url": "https://example.com/sale",
        "cta_text": "Shop Now",
        "placement": "home_hero",
        "sort_order": 0,
        "is_active": true,
        "is_currently_active": true,
        "start_at": null,
        "end_at": null,
        "created_at": "2024-01-01T10:00:00Z",
        "updated_at": "2024-01-01T10:00:00Z"
    }
    """
 
    is_currently_active = serializers.BooleanField(read_only=True)
 
    class Meta:
        model = Banner
        fields = [
            "id", "title", "subtitle",
            "image", "mobile_image",
            "link_url", "cta_text",
            "placement", "sort_order",
            "is_active", "is_currently_active",
            "start_at", "end_at",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "is_currently_active", "created_at", "updated_at"]
 
 
class BannerCreateUpdateSerializer(serializers.ModelSerializer):
    """
    Write serializer for POST/PATCH/PUT. `image` is required on create;
    DRF's default ImageField behaviour already makes it optional on a
    partial (PATCH) update since `partial=True` relaxes all required
    fields, so a caller can PATCH just `is_active` or `sort_order`
    without re-uploading the image.
 
    Example request body (POST /api/admin/banners/):
    {
        "title": "Autumn Sale",
        "subtitle": "Up to 40% off",
        "image": <file>,
        "link_url": "https://example.com/sale",
        "cta_text": "Shop Now",
        "placement": "home_hero",
        "sort_order": 0,
        "is_active": true
    }
    """
 
    class Meta:
        model = Banner
        fields = [
            "title", "subtitle",
            "image", "mobile_image",
            "link_url", "cta_text",
            "placement", "sort_order",
            "is_active", "start_at", "end_at",
        ]
 
    def validate(self, data):
        start_at = data.get("start_at", getattr(self.instance, "start_at", None))
        end_at = data.get("end_at", getattr(self.instance, "end_at", None))
        if start_at and end_at and start_at >= end_at:
            raise serializers.ValidationError({"end_at": "end_at must be after start_at."})
        return data
 
    def to_representation(self, instance):
        """Return the full read representation after create/update."""
        return BannerSerializer(instance, context=self.context).data
 
