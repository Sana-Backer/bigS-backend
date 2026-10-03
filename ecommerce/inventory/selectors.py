"""
inventory/selectors.py – read-side helpers (no writes).

A "stock row" is one sellable unit: an active variant, or an active product
that has no variants. Rows are plain dicts so they can be filtered, paginated
and exported (JSON / Excel) the same way.
"""

from django.db.models import Count, Q

from catalog.models import Product, ProductVariant

from .services import default_low_stock_threshold

IN_STOCK, LOW, OUT = "in_stock", "low", "out"


def _status(qty, threshold):
    if qty <= 0:
        return OUT
    return LOW if qty <= threshold else IN_STOCK


def stock_rows(*, search=None, category_slug=None, status=None, kind=None):
    default_thr = default_low_stock_threshold()
    rows = []

    if kind in (None, "", "variant"):
        qs = (ProductVariant.objects.filter(is_active=True, product__is_active=True)
              .select_related("product", "product__category", "stock_policy"))
        if search:
            qs = qs.filter(Q(sku__icontains=search) | Q(name__icontains=search)
                           | Q(product__name__icontains=search) | Q(product__sku__icontains=search))
        if category_slug:
            qs = qs.filter(product__category__slug=category_slug)
        for v in qs:
            policy = getattr(v, "stock_policy", None)
            thr = policy.low_stock_threshold if policy else default_thr
            rows.append({
                "kind": "variant", "product_id": v.product_id, "variant_id": v.id,
                "sku": v.sku, "name": f"{v.product.name} – {v.name}",
                "category": v.product.category.name if v.product.category_id else None,
                "stock_quantity": v.stock_quantity, "low_stock_threshold": thr,
                "reorder_quantity": policy.reorder_quantity if policy else 0,
                "unit_price": v.effective_price, "status": _status(v.stock_quantity, thr),
            })

    if kind in (None, "", "product"):
        qs = (Product.objects.filter(is_active=True)
              .annotate(n_variants=Count("variants"))
              .filter(n_variants=0).select_related("category", "stock_policy"))
        if search:
            qs = qs.filter(Q(sku__icontains=search) | Q(name__icontains=search))
        if category_slug:
            qs = qs.filter(category__slug=category_slug)
        for p in qs:
            policy = getattr(p, "stock_policy", None)
            thr = policy.low_stock_threshold if policy else default_thr
            rows.append({
                "kind": "product", "product_id": p.id, "variant_id": None,
                "sku": p.sku, "name": p.name,
                "category": p.category.name if p.category_id else None,
                "stock_quantity": p.stock_quantity, "low_stock_threshold": thr,
                "reorder_quantity": policy.reorder_quantity if policy else 0,
                "unit_price": p.effective_price, "status": _status(p.stock_quantity, thr),
            })

    if status == "attention":
        rows = [r for r in rows if r["status"] in (LOW, OUT)]
    elif status in (IN_STOCK, LOW, OUT):
        rows = [r for r in rows if r["status"] == status]

    rows.sort(key=lambda r: (r["stock_quantity"], r["sku"]))
    return rows


def stock_summary():
    rows = stock_rows()
    return {
        "sku_count": len(rows),
        "units_on_hand": sum(r["stock_quantity"] for r in rows),
        "stock_value_at_selling_price": sum(r["stock_quantity"] * r["unit_price"] for r in rows),
        "in_stock": sum(1 for r in rows if r["status"] == IN_STOCK),
        "low_stock": sum(1 for r in rows if r["status"] == LOW),
        "out_of_stock": sum(1 for r in rows if r["status"] == OUT),
    }
