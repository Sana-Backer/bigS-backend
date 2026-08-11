"""
catalog/filters.py

django-filter FilterSets for Product filtering.

Supported query params:
  ?category=skin-care
  ?brand=Botanica
  ?min_price=5.00
  ?max_price=50.00
  ?featured=true
  ?search=rose cream
  ?ordering=price | -price | created_at | -created_at
"""

import django_filters
from django.db.models import Q
from .models import Product


class ProductFilter(django_filters.FilterSet):
    category = django_filters.CharFilter(
        field_name="category__slug", lookup_expr="iexact",
        label="Category slug"
    )
    brand = django_filters.CharFilter(
        field_name="brand", lookup_expr="icontains",
        label="Brand (case-insensitive contains)"
    )
    min_price = django_filters.NumberFilter(
        field_name="base_price", lookup_expr="gte",
        label="Minimum base price"
    )
    max_price = django_filters.NumberFilter(
        field_name="base_price", lookup_expr="lte",
        label="Maximum base price"
    )
    featured = django_filters.BooleanFilter(
        field_name="is_featured",
        label="Featured only"
    )
    search = django_filters.CharFilter(
        method="filter_search",
        label="Full-text search across name, description, brand, SKU"
    )

    class Meta:
        model = Product
        fields = ["category", "brand", "min_price", "max_price", "featured", "search"]

    def filter_search(self, queryset, name, value):
        return queryset.filter(
            Q(name__icontains=value)
            | Q(description__icontains=value)
            | Q(short_description__icontains=value)
            | Q(brand__icontains=value)
            | Q(sku__icontains=value)
        )
