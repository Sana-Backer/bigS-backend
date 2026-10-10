"""
catalog/filters.py

Variant-aware filtering and sorting for the product list.

Price/stock follow the exact same precedence as catalog.serializers
(_representative_variant etc.): the default active variant, else the cheapest
active variant, else the product's own fields. So filtering/sorting always
agrees with the price shown on the card.

Query params (all optional, combinable):
  category=skin-care            category slug; includes all sub-categories
  brand=Botanica,Lumina         one or more brands (comma-separated or repeated)
  min_price=5&max_price=50      range on the price the customer pays
  in_stock=true|false
  on_sale=true
  min_discount=20               at least 20% off
  featured=true
  search=rose cream
  ordering=price_asc | price_desc | newest | oldest | name_asc | name_desc
           | discount | featured       (legacy: price, -price, created_at, -created_at)
"""

import django_filters
from django.db.models import (
    BooleanField, Case, DecimalField, Exists, ExpressionWrapper, F, OuterRef,
    Q, Subquery, Value, When,
)
from django.db.models.functions import Coalesce, Lower

from .models import Category, Product, ProductVariant

_DEC = DecimalField(max_digits=12, decimal_places=2)

ORDERING_MAP = {
    "price_asc": ["effective_price_value", "-created_at"],
    "price_desc": ["-effective_price_value", "-created_at"],
    "newest": ["-created_at"],
    "oldest": ["created_at"],
    "name_asc": ["name"],
    "name_desc": ["-name"],
    "discount": ["-discount_pct", "-created_at"],
    "featured": ["-is_featured", "-created_at"],
    # legacy values kept so existing clients don't break
    "price": ["effective_price_value", "-created_at"],
    "-price": ["-effective_price_value", "-created_at"],
    "created_at": ["created_at"],
    "-created_at": ["-created_at"],
}


def annotate_pricing(qs):
    """Add effective_price_value, list_price_value, discount_pct, in_stock_flag."""
    active = ProductVariant.objects.filter(product=OuterRef("pk"), is_active=True)
    default = active.filter(is_default=True)
    cheapest = active.order_by("price")

    def eff(v):
        return v.annotate(e=Coalesce("sale_price", "price", output_field=_DEC)).values("e")[:1]

    qs = qs.annotate(
        list_price_value=Coalesce(
            Subquery(default.values("price")[:1], output_field=_DEC),
            Subquery(cheapest.values("price")[:1], output_field=_DEC),
            F("base_price"),
            output_field=_DEC,
        ),
        effective_price_value=Coalesce(
            Subquery(eff(default), output_field=_DEC),
            Subquery(eff(cheapest), output_field=_DEC),
            Coalesce("sale_price", "base_price", output_field=_DEC),
            output_field=_DEC,
        ),
    )
    qs = qs.annotate(
        discount_pct=Case(
            When(
                list_price_value__gt=0,
                then=ExpressionWrapper(
                    (F("list_price_value") - F("effective_price_value")) * 100
                    / F("list_price_value"),
                    output_field=DecimalField(max_digits=6, decimal_places=2),
                ),
            ),
            default=Value(0),
            output_field=DecimalField(max_digits=6, decimal_places=2),
        ),
        # mirrors serializers._product_in_stock
        in_stock_flag=Case(
            When(
                Exists(ProductVariant.objects.filter(product=OuterRef("pk"))),
                then=Exists(
                    ProductVariant.objects.filter(
                        product=OuterRef("pk"), is_active=True, stock_quantity__gt=0
                    )
                ),
            ),
            default=Q(stock_quantity__gt=0),
            output_field=BooleanField(),
        ),
    )
    return qs


def category_with_descendants(slug):
    """Slug of a category -> list of its id + all descendant ids."""
    root = Category.objects.filter(slug__iexact=slug, is_active=True).first()
    if not root:
        return []
    ids, frontier = [root.id], [root.id]
    while frontier:
        frontier = list(
            Category.objects.filter(parent_id__in=frontier, is_active=True)
            .values_list("id", flat=True)
        )
        ids.extend(frontier)
    return ids


class CharInFilter(django_filters.BaseInFilter, django_filters.CharFilter):
    pass


class ProductFilter(django_filters.FilterSet):
    category = django_filters.CharFilter(method="filter_category", label="Category slug (includes sub-categories)")
    brand = CharInFilter(method="filter_brand", label="Brand(s), comma-separated")
    min_price = django_filters.NumberFilter(method="filter_min_price")
    max_price = django_filters.NumberFilter(method="filter_max_price")
    in_stock = django_filters.BooleanFilter(method="filter_in_stock")
    on_sale = django_filters.BooleanFilter(method="filter_on_sale")
    min_discount = django_filters.NumberFilter(method="filter_min_discount")
    featured = django_filters.BooleanFilter(field_name="is_featured")
    search = django_filters.CharFilter(method="filter_search")
    ordering = django_filters.CharFilter(method="filter_ordering")

    class Meta:
        model = Product
        fields = []

    def __init__(self, data=None, queryset=None, *args, **kwargs):
        if queryset is not None:
            queryset = annotate_pricing(queryset)
        super().__init__(data, queryset, *args, **kwargs)

    def filter_category(self, qs, name, value):
        return qs.filter(category_id__in=category_with_descendants(value))

    def filter_brand(self, qs, name, value):
        q = Q()
        for b in value:
            if b.strip():
                q |= Q(brand__iexact=b.strip())
        return qs.filter(q) if q else qs

    def filter_min_price(self, qs, name, value):
        return qs.filter(effective_price_value__gte=value)

    def filter_max_price(self, qs, name, value):
        return qs.filter(effective_price_value__lte=value)

    def filter_in_stock(self, qs, name, value):
        return qs.filter(in_stock_flag=value)

    def filter_on_sale(self, qs, name, value):
        cond = Q(effective_price_value__lt=F("list_price_value"))
        return qs.filter(cond) if value else qs.exclude(cond)

    def filter_min_discount(self, qs, name, value):
        return qs.filter(discount_pct__gte=value)

    def filter_search(self, qs, name, value):
        value = value.strip()
        if not value:
            return qs
        return qs.filter(
            Q(name__icontains=value)
            | Q(description__icontains=value)
            | Q(short_description__icontains=value)
            | Q(brand__icontains=value)
            | Q(sku__icontains=value)
            | Q(variants__sku__icontains=value, variants__is_active=True)
        ).distinct()

    def filter_ordering(self, qs, name, value):
        order = ORDERING_MAP.get(value.strip())
        if not order:
            return qs
        
        # Make name sorting case-insensitive
        if "name" in order[0] or "-name" in order[0]:
            qs = qs.annotate(name_lower=Lower("name"))
            order = [o.replace("name", "name_lower") for o in order]
            
        return qs.order_by(*order)