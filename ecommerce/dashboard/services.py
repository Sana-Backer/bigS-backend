"""
dashboard/services.py

All read-only aggregation logic behind the admin dashboard, reports,
and analytics endpoints. No new models — everything here queries
orders.models.Order / OrderItem, catalog.models.Product / Category /
ProductVariant, and users.models.User, which already exist.

Revenue definition (applies everywhere in this module)
--------------------------------------------------------
"Revenue" = the sum of Order.total_amount for orders whose
payment_status is PAID, PARTIALLY_REFUNDED, or REFUNDED — i.e. orders
that were actually charged at some point. This is gross revenue (a
refund does not remove the sale from the chart); it does NOT subtract
payments.models.PaymentTransaction.refunded_amount. If your business
wants net-of-refunds revenue instead, that's the one constant
(REVENUE_PAYMENT_STATUSES) and the one line (subtracting refunded
amounts via a payments-app query) to change.

"Total orders" counts every Order in range regardless of status
(matches a Recent Orders table that also lists cancelled orders).

Bucketing strategy
-------------------
Time-series endpoints (sales analytics, revenue trend, customer
growth, average order value) bucket by simple, explicit start/end
datetime windows and run one small aggregate query per bucket (max
30, for the "monthly" period) rather than a single annotate(Trunc...)
query. This trades a little query volume for something that behaves
identically across SQLite/Postgres and never leaves a chart with a
silently-missing zero-value bucket — worth it for an admin-only,
low-traffic surface like this.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Count, Max, Sum
from django.utils import timezone

from catalog.models import Product, ProductVariant
from orders.constants import PaymentStatus
from orders.models import Order, OrderItem
from users.models import User

from .exceptions import InvalidPeriod

ZERO = Decimal("0.00")

REVENUE_PAYMENT_STATUSES = (
    PaymentStatus.PAID,
    PaymentStatus.PARTIALLY_REFUNDED,
    PaymentStatus.REFUNDED,
)

RANGE_DAYS = {"today": 1, "7d": 7, "30d": 30, "90d": 90, "1y": 365}


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------

def _pct_change(current, previous) -> float:
    """Percentage change from `previous` to `current`, defensively handling zero."""
    current = float(current or 0)
    previous = float(previous or 0)
    if previous == 0:
        return 100.0 if current else 0.0
    return round((current - previous) / previous * 100, 1)


def _shift_months(dt, delta_months: int):
    """Returns `dt` shifted by `delta_months` whole calendar months (day fixed at 1)."""
    month_index = dt.month - 1 + delta_months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    return dt.replace(year=year, month=month)


def _hourly_buckets(now, hours=24):
    start = (now - timedelta(hours=hours - 1)).replace(minute=0, second=0, microsecond=0)
    buckets = []
    for i in range(hours):
        b_start = start + timedelta(hours=i)
        b_end = b_start + timedelta(hours=1)
        buckets.append((b_start, b_end, b_start.strftime("%H:00")))
    return buckets

def _hourly_buckets_today(now):
    """
    Returns hourly buckets for the current calendar day only.
    """

    start = now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    current_hour = now.replace(
        minute=0,
        second=0,
        microsecond=0,
    )

    buckets = []
    cursor = start

    while cursor <= current_hour:
        b_start = cursor
        b_end = cursor + timedelta(hours=1)

        buckets.append(
            (
                b_start,
                b_end,
                b_start.strftime("%H:00"),
            )
        )

        cursor += timedelta(hours=1)

    return buckets

def _daily_buckets(now, days=7):
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    buckets = []
    for i in range(days):
        b_start = start + timedelta(days=i)
        b_end = b_start + timedelta(days=1)
        label = b_start.strftime("%a") if days <= 7 else b_start.strftime("%b %d")
        buckets.append((b_start, b_end, label))
    return buckets


def _monthly_buckets(now, months=12):
    anchor = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    starts = []
    cursor = anchor
    for _ in range(months):
        starts.append(cursor)
        cursor = _shift_months(cursor, -1)
    starts.reverse()
    buckets = []
    for b_start in starts:
        b_end = _shift_months(b_start, 1)
        buckets.append((b_start, b_end, b_start.strftime("%b")))
    return buckets


def _buckets_for_period(period: str, now):
    if period in ("today", "daily"):
        return _hourly_buckets_today(now)
    if period in ("7d", "weekly"):
        return _daily_buckets(now, days=7)
    if period == "monthly":
        return _daily_buckets(now, days=30)
    if period == "90d":
        return _daily_buckets(now, days=90)
    if period == "yearly":
        return _monthly_buckets(now, months=12)
    raise InvalidPeriod()


def _revenue_orders_for_bucket(b_start, b_end):
    return Order.objects.filter(
        created_at__gte=b_start, created_at__lt=b_end,
        payment_status__in=REVENUE_PAYMENT_STATUSES,
    ).aggregate(revenue=Sum("total_amount"), orders=Count("id"))


# ---------------------------------------------------------------------------
# Dashboard — GET /api/admin/dashboard/overview/
# ---------------------------------------------------------------------------

def get_dashboard_overview(range_key: str = "30d") -> dict:
    days = RANGE_DAYS.get(range_key, 30)
    now = timezone.now()
    period_start = now - timedelta(days=days)
    prev_start = period_start - timedelta(days=days)

    current_orders = Order.objects.filter(created_at__gte=period_start, created_at__lte=now)
    previous_orders = Order.objects.filter(created_at__gte=prev_start, created_at__lt=period_start)

    current_revenue = current_orders.filter(payment_status__in=REVENUE_PAYMENT_STATUSES) \
        .aggregate(v=Sum("total_amount"))["v"] or ZERO
    previous_revenue = previous_orders.filter(payment_status__in=REVENUE_PAYMENT_STATUSES) \
        .aggregate(v=Sum("total_amount"))["v"] or ZERO

    current_order_count = current_orders.count()
    previous_order_count = previous_orders.count()

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    today_sales = Order.objects.filter(
        created_at__gte=today_start, payment_status__in=REVENUE_PAYMENT_STATUSES,
    ).aggregate(v=Sum("total_amount"))["v"] or ZERO
    yesterday_sales = Order.objects.filter(
        created_at__gte=yesterday_start, created_at__lt=today_start,
        payment_status__in=REVENUE_PAYMENT_STATUSES,
    ).aggregate(v=Sum("total_amount"))["v"] or ZERO

    total_products = Product.objects.filter(is_active=True).count()
    previous_total_products = Product.objects.filter(is_active=True, created_at__lt=period_start).count()

    return {
        "range": range_key,
        "total_revenue": {
            "value": current_revenue,
            "change_percentage": _pct_change(current_revenue, previous_revenue),
        },
        "today_sales": {
            "value": today_sales,
            "change_percentage": _pct_change(today_sales, yesterday_sales),
        },
        "total_products": {
            "value": total_products,
            "change_percentage": _pct_change(total_products, previous_total_products),
        },
        "total_orders": {
            "value": current_order_count,
            "change_percentage": _pct_change(current_order_count, previous_order_count),
        },
    }


# ---------------------------------------------------------------------------
# Dashboard — GET /api/admin/dashboard/sales-analytics/
# ---------------------------------------------------------------------------

def get_sales_analytics(period: str = "weekly") -> dict:
    now = timezone.now()
    buckets = _buckets_for_period(period, now)

    labels, revenue_series, orders_series = [], [], []
    for b_start, b_end, label in buckets:
        row = _revenue_orders_for_bucket(b_start, b_end)
        labels.append(label)
        revenue_series.append(row["revenue"] or ZERO)
        orders_series.append(row["orders"] or 0)

    return {"period": period, "labels": labels, "revenue": revenue_series, "orders": orders_series}


# ---------------------------------------------------------------------------
# Dashboard — GET /api/admin/dashboard/top-selling/
# ---------------------------------------------------------------------------

def get_top_selling_products(limit: int = 5, date_from=None, date_to=None) -> list:
    qs = OrderItem.objects.filter(order__payment_status__in=REVENUE_PAYMENT_STATUSES)
    if date_from:
        qs = qs.filter(order__created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(order__created_at__date__lte=date_to)

    rows = list(
        qs.values("product_id", "product_name")
        .annotate(units_sold=Sum("quantity"), revenue=Sum("total_price"))
        .order_by("-revenue")[:limit]
    )

    product_ids = [r["product_id"] for r in rows if r["product_id"]]
    products = {p.id: p for p in Product.objects.select_related("category").filter(id__in=product_ids)}

    results = []
    for r in rows:
        product = products.get(r["product_id"])
        results.append({
            "product_id": r["product_id"],
            # product_name is the OrderItem snapshot — correct even if the
            # product was later renamed or deleted from the catalog.
            "name": r["product_name"],
            "category": product.category.name if product else None,
            "units_sold": r["units_sold"] or 0,
            "revenue": r["revenue"] or ZERO,
        })
    return results


# ---------------------------------------------------------------------------
# Dashboard — GET /api/admin/dashboard/top-categories/
# ---------------------------------------------------------------------------

def get_top_categories(date_from=None, date_to=None) -> list:
    qs = OrderItem.objects.filter(
        order__payment_status__in=REVENUE_PAYMENT_STATUSES, product__isnull=False,
    )
    if date_from:
        qs = qs.filter(order__created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(order__created_at__date__lte=date_to)

    rows = list(
        qs.values("product__category_id", "product__category__name")
        .annotate(revenue=Sum("total_price"))
        .order_by("-revenue")
    )
    total_revenue = sum((r["revenue"] or ZERO) for r in rows) or ZERO

    results = []
    for r in rows:
        revenue = r["revenue"] or ZERO
        percentage = round(float(revenue) / float(total_revenue) * 100, 1) if total_revenue else 0.0
        results.append({
            "category_id": r["product__category_id"],
            "name": r["product__category__name"] or "Uncategorized",
            "revenue": revenue,
            "percentage": percentage,
        })
    return results


# ---------------------------------------------------------------------------
# Dashboard — GET /api/admin/dashboard/revenue-overview/
# ---------------------------------------------------------------------------

def get_revenue_overview(months: int = 7) -> dict:
    now = timezone.now()
    buckets = _monthly_buckets(now, months=months)
    labels, data = [], []
    for b_start, b_end, label in buckets:
        v = Order.objects.filter(
            created_at__gte=b_start, created_at__lt=b_end,
            payment_status__in=REVENUE_PAYMENT_STATUSES,
        ).aggregate(v=Sum("total_amount"))["v"] or ZERO
        labels.append(label)
        data.append(v)
    return {"labels": labels, "data": data}


# ---------------------------------------------------------------------------
# Dashboard — GET /api/admin/dashboard/recent-orders/
# ---------------------------------------------------------------------------

def get_recent_orders(limit: int = 10) -> list:
    orders = Order.objects.select_related("user").order_by("-created_at")[:limit]
    results = []
    for o in orders:
        customer_name = o.user.full_name if o.user_id else (o.customer_email or "Guest")
        results.append({
            "id": o.id,
            "order_number": o.order_number,
            "customer_name": customer_name,
            "customer_email": o.customer_email,
            "amount": o.total_amount,
            "currency": o.currency,
            "status": o.status,
            "payment_status": o.payment_status,
            "fulfillment_status": o.fulfillment_status,
            "created_at": o.created_at,
        })
    return results


# ---------------------------------------------------------------------------
# Reports — GET /api/admin/reports/sales/
# ---------------------------------------------------------------------------

def _date_range_buckets(date_from, date_to, group_by: str):
    """
    Buckets a *date* (not datetime) range [date_from, date_to] inclusive
    into day/week/month chunks, each as (start_date, end_date_exclusive, label).
    """
    buckets = []
    if group_by == "day":
        cursor = date_from
        while cursor <= date_to:
            nxt = cursor + timedelta(days=1)
            buckets.append((cursor, nxt, cursor.isoformat()))
            cursor = nxt
    elif group_by == "week":
        cursor = date_from
        while cursor <= date_to:
            nxt = min(cursor + timedelta(days=7), date_to + timedelta(days=1))
            buckets.append((cursor, nxt, f"{cursor.isoformat()} – {(nxt - timedelta(days=1)).isoformat()}"))
            cursor = nxt
    elif group_by == "month":
        cursor = date_from.replace(day=1)
        while cursor <= date_to:
            nxt = _shift_months(datetime.combine(cursor, datetime.min.time()), 1).date()
            buckets.append((cursor, nxt, cursor.strftime("%b %Y")))
            cursor = nxt
    else:
        raise InvalidPeriod()
    return buckets


def get_sales_report(date_from, date_to, group_by: str = "day") -> list:
    buckets = _date_range_buckets(date_from, date_to, group_by)
    rows = []
    for b_start, b_end, label in buckets:
        agg = Order.objects.filter(
            created_at__date__gte=b_start, created_at__date__lt=b_end,
            payment_status__in=REVENUE_PAYMENT_STATUSES,
        ).aggregate(revenue=Sum("total_amount"), orders=Count("id"))
        revenue = agg["revenue"] or ZERO
        orders_count = agg["orders"] or 0
        avg = (revenue / orders_count).quantize(Decimal("0.01")) if orders_count else ZERO
        rows.append({
            "period": label,
            "orders_count": orders_count,
            "revenue": revenue,
            "average_order_value": avg,
        })
    return rows


# ---------------------------------------------------------------------------
# Reports — GET /api/admin/reports/products/
# ---------------------------------------------------------------------------

_PRODUCT_ORDERING_FIELDS = {
    "revenue", "-revenue", "units_sold", "-units_sold", "orders_count", "-orders_count",
}


def get_product_performance_report(date_from=None, date_to=None, ordering: str = "-revenue") -> list:
    if ordering not in _PRODUCT_ORDERING_FIELDS:
        ordering = "-revenue"

    qs = OrderItem.objects.filter(order__payment_status__in=REVENUE_PAYMENT_STATUSES)
    if date_from:
        qs = qs.filter(order__created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(order__created_at__date__lte=date_to)

    rows = list(
        qs.values("product_id", "product_name")
        .annotate(
            units_sold=Sum("quantity"),
            revenue=Sum("total_price"),
            orders_count=Count("order_id", distinct=True),
        )
        .order_by(ordering)
    )

    product_ids = [r["product_id"] for r in rows if r["product_id"]]
    products = {p.id: p for p in Product.objects.filter(id__in=product_ids)}
    stock_by_product = dict(
        ProductVariant.objects.filter(product_id__in=product_ids)
        .values("product_id").annotate(stock=Sum("stock_quantity"))
        .values_list("product_id", "stock")
    )

    results = []
    for r in rows:
        product = products.get(r["product_id"])
        results.append({
            "product_id": r["product_id"],
            "name": r["product_name"],
            "sku": product.sku if product else None,
            "units_sold": r["units_sold"] or 0,
            "revenue": r["revenue"] or ZERO,
            "orders_count": r["orders_count"] or 0,
            "current_stock": stock_by_product.get(r["product_id"], 0),
            "is_active": product.is_active if product else False,
        })
    return results


# ---------------------------------------------------------------------------
# Reports — GET /api/admin/reports/customers/
# ---------------------------------------------------------------------------

_CUSTOMER_ORDERING_FIELDS = {
    "total_spent", "-total_spent", "orders_count", "-orders_count",
    "last_order_at", "-last_order_at",
}


def get_customer_report(date_from=None, date_to=None, ordering: str = "-total_spent") -> list:
    if ordering not in _CUSTOMER_ORDERING_FIELDS:
        ordering = "-total_spent"

    qs = Order.objects.filter(user__isnull=False, payment_status__in=REVENUE_PAYMENT_STATUSES)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)

    rows = (
        qs.values("user_id", "user__email", "user__first_name", "user__last_name")
        .annotate(orders_count=Count("id"), total_spent=Sum("total_amount"), last_order_at=Max("created_at"))
        .order_by(ordering)
    )

    results = []
    for r in rows:
        orders_count = r["orders_count"] or 0
        total_spent = r["total_spent"] or ZERO
        avg = (total_spent / orders_count).quantize(Decimal("0.01")) if orders_count else ZERO
        name = f"{r['user__first_name']} {r['user__last_name']}".strip() or r["user__email"]
        results.append({
            "user_id": r["user_id"],
            "name": name,
            "email": r["user__email"],
            "orders_count": orders_count,
            "total_spent": total_spent,
            "average_order_value": avg,
            "last_order_at": r["last_order_at"],
        })
    return results


# ---------------------------------------------------------------------------
# Reports — GET /api/admin/reports/inventory/
# ---------------------------------------------------------------------------

def get_inventory_report(low_stock_threshold: int = 10) -> list:
    variants = (
        ProductVariant.objects
        .select_related("product", "product__category")
        .filter(is_active=True)
        .order_by("stock_quantity")
    )
    results = []
    for v in variants:
        results.append({
            "product_id": v.product_id,
            "product_name": v.product.name,
            "variant_id": v.id,
            "variant_name": v.name,
            "sku": v.sku,
            "category": v.product.category.name if v.product.category_id else None,
            "stock_quantity": v.stock_quantity,
            "is_low_stock": v.stock_quantity <= low_stock_threshold,
            "is_out_of_stock": v.stock_quantity == 0,
        })
    return results


# ---------------------------------------------------------------------------
# Reports — GET /api/admin/reports/order-status/
# ---------------------------------------------------------------------------

def _status_counts(field: str) -> dict:
    rows = Order.objects.values(field).annotate(count=Count("id")).order_by()
    return {row[field]: row["count"] for row in rows}


def get_order_status_breakdown() -> dict:
    return {
        "by_order_status": _status_counts("status"),
        "by_payment_status": _status_counts("payment_status"),
        "by_fulfillment_status": _status_counts("fulfillment_status"),
    }


# ---------------------------------------------------------------------------
# Analytics — GET /api/admin/analytics/revenue-trend/
# ---------------------------------------------------------------------------

def get_revenue_trend(period: str = "weekly") -> dict:
    base = get_sales_analytics(period)
    revenue = base["revenue"]
    if revenue:
        growth_rate = _pct_change(revenue[-1], revenue[0])
    else:
        growth_rate = 0.0
    base["growth_rate_percentage"] = growth_rate
    return base


# ---------------------------------------------------------------------------
# Analytics — GET /api/admin/analytics/category-performance/
# ---------------------------------------------------------------------------

def get_category_performance(date_from=None, date_to=None) -> list:
    qs = OrderItem.objects.filter(
        order__payment_status__in=REVENUE_PAYMENT_STATUSES, product__isnull=False,
    )
    if date_from:
        qs = qs.filter(order__created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(order__created_at__date__lte=date_to)

    rows = list(
        qs.values("product__category_id", "product__category__name")
        .annotate(
            revenue=Sum("total_price"),
            units_sold=Sum("quantity"),
            orders_count=Count("order_id", distinct=True),
        )
        .order_by("-revenue")
    )

    category_ids = [r["product__category_id"] for r in rows if r["product__category_id"]]
    product_counts = dict(
        Product.objects.filter(category_id__in=category_ids, is_active=True)
        .values("category_id").annotate(c=Count("id")).values_list("category_id", "c")
    )

    results = []
    for r in rows:
        cat_id = r["product__category_id"]
        results.append({
            "category_id": cat_id,
            "name": r["product__category__name"] or "Uncategorized",
            "revenue": r["revenue"] or ZERO,
            "units_sold": r["units_sold"] or 0,
            "orders_count": r["orders_count"] or 0,
            "product_count": product_counts.get(cat_id, 0),
        })
    return results


# ---------------------------------------------------------------------------
# Analytics — GET /api/admin/analytics/customer-growth/
# ---------------------------------------------------------------------------

def get_customer_growth(period: str = "weekly") -> dict:
    now = timezone.now()
    buckets = _buckets_for_period(period, now)

    running = User.objects.filter(date_joined__lt=buckets[0][0]).count() if buckets else 0

    labels, new_customers, cumulative = [], [], []
    for b_start, b_end, label in buckets:
        c = User.objects.filter(date_joined__gte=b_start, date_joined__lt=b_end).count()
        running += c
        labels.append(label)
        new_customers.append(c)
        cumulative.append(running)

    return {
        "period": period,
        "labels": labels,
        "new_customers": new_customers,
        "cumulative_customers": cumulative,
    }


# ---------------------------------------------------------------------------
# Analytics — GET /api/admin/analytics/average-order-value/
# ---------------------------------------------------------------------------

def get_average_order_value_trend(period: str = "weekly") -> dict:
    base = get_sales_analytics(period)
    aov = []
    for revenue, orders_count in zip(base["revenue"], base["orders"]):
        aov.append((revenue / orders_count).quantize(Decimal("0.01")) if orders_count else ZERO)
    return {"period": period, "labels": base["labels"], "average_order_value": aov}
