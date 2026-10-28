"""
dashboard/serializers.py

Every endpoint in this app is read-only and returns plain aggregated
dicts (Decimals, ints, date labels) rather than model instances, so
there are no output ModelSerializers here — only input serializers
that validate query parameters before a view calls into services.py.
"""

from rest_framework import serializers
 
from catalog.models import Category
from .models import Banner, BannerPlacement

PERIOD_CHOICES = ("today", "7d", "daily", "weekly", "monthly", "yearly", "90d")


class PeriodQuerySerializer(serializers.Serializer):
    period = serializers.ChoiceField(choices=PERIOD_CHOICES, required=False, default="today")


class DashboardOverviewQuerySerializer(serializers.Serializer):
    range = serializers.ChoiceField(choices=("today", "7d", "30d", "90d", "1y"), required=False, default="30d")


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
    """Read representation — admin CRUD + public storefront endpoint."""
 
    is_currently_active = serializers.BooleanField(read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True, default=None)
    category_slug = serializers.CharField(source="category.slug", read_only=True, default=None)
 
    class Meta:
        model = Banner
        fields = [
            "id", "title", "subtitle",
            "image", "mobile_image",
            "link_url", "cta_text",
            "placement", "is_mobile",
            "category", "category_name", "category_slug",
            "sort_order",
            "is_active", "is_currently_active",
            "start_at", "end_at",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "is_currently_active", "created_at", "updated_at"]
 

 
class BannerCreateUpdateSerializer(serializers.ModelSerializer):
    """
    Write serializer. Example (shop-page banner for one category, phone version):
    {
        "title": "Beauty Care — phone",
        "image": <file>,
        "placement": "shop_category",
        "category": "<category uuid>",
        "is_mobile": true,
        "is_active": true
    }
    """

    start_at = serializers.DateTimeField(required=False, allow_null=True)
    end_at = serializers.DateTimeField(required=False, allow_null=True)

 
    category = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.filter(is_active=True), required=False, allow_null=True,
    )
 
    class Meta:
        model = Banner
        fields = [
            "title", "subtitle",
            "image", "mobile_image",
            "link_url", "cta_text",
            "placement", "is_mobile", "category", "sort_order",
            "is_active", "start_at", "end_at",
        ]

    def to_internal_value(self, data):
        # Convert empty strings to None for nullable DateTimeFields (sent via FormData)
        if hasattr(data, "copy"):
            data = data.copy()
        elif isinstance(data, dict):
            data = data.copy()
        if "start_at" in data and data["start_at"] in ("", "null", "undefined"):
            data["start_at"] = None
        if "end_at" in data and data["end_at"] in ("", "null", "undefined"):
            data["end_at"] = None
        return super().to_internal_value(data)

    def validate(self, data):
        inst = self.instance
        start_at = data.get("start_at", getattr(inst, "start_at", None))
        end_at = data.get("end_at", getattr(inst, "end_at", None))
        if start_at and end_at and start_at >= end_at:
            raise serializers.ValidationError({"end_at": "end_at must be after start_at."})
 
        placement = data.get("placement", getattr(inst, "placement", BannerPlacement.HOME_HERO))
        category = data.get("category", getattr(inst, "category", None))
        if category and placement != BannerPlacement.SHOP_CATEGORY:
            raise serializers.ValidationError(
                {"category": "A category can only be set for the 'shop_category' placement."}
            )
        return data
 
    def to_representation(self, instance):
        return BannerSerializer(instance, context=self.context).data
 
 
class BannerPublicQuerySerializer(serializers.Serializer):
    """Validates ?placement=&device=&category= on the public endpoint."""
 
    placement = serializers.ChoiceField(choices=BannerPlacement.choices, required=False, allow_blank=True)
    device = serializers.ChoiceField(choices=("mobile", "desktop"), required=False, allow_blank=True)
    category = serializers.SlugField(required=False, allow_blank=True)
 