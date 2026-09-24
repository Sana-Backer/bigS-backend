"""
dashboard/serializers.py

Every endpoint in this app is read-only and returns plain aggregated
dicts (Decimals, ints, date labels) rather than model instances, so
there are no output ModelSerializers here — only input serializers
that validate query parameters before a view calls into services.py.
"""

from rest_framework import serializers

PERIOD_CHOICES = ("daily", "weekly", "monthly", "yearly")


class PeriodQuerySerializer(serializers.Serializer):
    period = serializers.ChoiceField(choices=PERIOD_CHOICES, required=False, default="weekly")


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
