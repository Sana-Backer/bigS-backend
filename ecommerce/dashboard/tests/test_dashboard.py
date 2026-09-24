"""
dashboard/tests/test_dashboard.py

Standard Django TestCase suite (run with `python manage.py test dashboard`).
Builds a small, real Order/OrderItem/Product/Category graph and checks
the aggregation endpoints against it directly, rather than mocking —
there's no external service in this app to mock.
"""

import uuid
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from catalog.models import Category, Product
from orders.constants import OrderStatus, PaymentStatus
from orders.models import Order, OrderItem
from users.models import User


def make_category(name="Beauty"):
    return Category.objects.create(name=name)


def make_product(category, name="Serum", price="500.00", sku=None):
    return Product.objects.create(
        category=category, name=name, sku=sku or f"SKU-{uuid.uuid4().hex[:8]}",
        base_price=Decimal(price),
    )


def make_order(*, user=None, total_amount="500.00", status=OrderStatus.CONFIRMED,
                payment_status=PaymentStatus.PAID, created_at=None):
    order = Order.objects.create(
        order_number=f"ORD-TEST-{uuid.uuid4().hex[:8].upper()}",
        user=user,
        customer_email=user.email if user else "guest@example.com",
        subtotal=Decimal(total_amount),
        total_amount=Decimal(total_amount),
        status=status,
        payment_status=payment_status,
    )
    if created_at is not None:
        Order.objects.filter(pk=order.pk).update(created_at=created_at)
        order.refresh_from_db()
    return order


def make_order_item(order, product, quantity=1, unit_price="500.00"):
    total = Decimal(unit_price) * quantity
    return OrderItem.objects.create(
        order=order, product=product,
        product_name=product.name, sku=product.sku,
        unit_price=Decimal(unit_price), quantity=quantity, total_price=total,
    )


def make_admin(email="admin@example.com"):
    return User.objects.create_superuser(email=email, password="adminpass123")


class DashboardTestBase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make_admin()
        self.customer = User.objects.create_user(email="cust1@example.com", password="pass12345")
        self.category = make_category("Beauty")
        self.product = make_product(self.category, name="Glow Serum", price="500.00")

        self.order = make_order(user=self.customer, total_amount="500.00")
        make_order_item(self.order, self.product, quantity=2, unit_price="250.00")

        self.client.force_authenticate(user=self.admin)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class DashboardOverviewTests(DashboardTestBase):
    def test_overview_returns_expected_shape(self):
        resp = self.client.get(reverse("dashboard-overview"))
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        for key in ("total_revenue", "today_sales", "total_products", "total_orders"):
            self.assertIn(key, data)
            self.assertIn("value", data[key])
            self.assertIn("change_percentage", data[key])
        # One PAID order of 500.00 exists in range.
        self.assertEqual(Decimal(data["total_revenue"]["value"]), Decimal("500.00"))
        self.assertEqual(data["total_orders"]["value"], 1)

    def test_overview_rejects_invalid_range(self):
        resp = self.client.get(reverse("dashboard-overview"), {"range": "bogus"})
        self.assertEqual(resp.status_code, 400)

    def test_non_admin_forbidden(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get(reverse("dashboard-overview"))
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_rejected(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get(reverse("dashboard-overview"))
        self.assertIn(resp.status_code, (401, 403))


class SalesAnalyticsTests(DashboardTestBase):
    def test_weekly_has_seven_buckets(self):
        resp = self.client.get(reverse("dashboard-sales-analytics"), {"period": "weekly"})
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(len(data["labels"]), 7)
        self.assertEqual(len(data["revenue"]), 7)
        self.assertEqual(sum(Decimal(v) for v in data["revenue"]), Decimal("500.00"))

    def test_yearly_has_twelve_buckets(self):
        resp = self.client.get(reverse("dashboard-sales-analytics"), {"period": "yearly"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["data"]["labels"]), 12)

    def test_invalid_period_rejected(self):
        resp = self.client.get(reverse("dashboard-sales-analytics"), {"period": "century"})
        self.assertEqual(resp.status_code, 400)


class TopSellingAndCategoriesTests(DashboardTestBase):
    def test_top_selling_products(self):
        resp = self.client.get(reverse("dashboard-top-selling"))
        self.assertEqual(resp.status_code, 200)
        rows = resp.data["data"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Glow Serum")
        self.assertEqual(rows[0]["units_sold"], 2)
        self.assertEqual(Decimal(rows[0]["revenue"]), Decimal("500.00"))

    def test_top_categories_percentages_sum_to_100(self):
        other_category = make_category("Kitchen")
        other_product = make_product(other_category, name="Blender", price="500.00")
        other_order = make_order(user=self.customer, total_amount="500.00")
        make_order_item(other_order, other_product, quantity=1, unit_price="500.00")

        resp = self.client.get(reverse("dashboard-top-categories"))
        self.assertEqual(resp.status_code, 200)
        rows = resp.data["data"]
        self.assertEqual(len(rows), 2)
        total_pct = sum(r["percentage"] for r in rows)
        self.assertAlmostEqual(total_pct, 100.0, delta=0.2)


class RevenueOverviewAndRecentOrdersTests(DashboardTestBase):
    def test_revenue_overview_default_months(self):
        resp = self.client.get(reverse("dashboard-revenue-overview"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["data"]["labels"]), 7)

    def test_recent_orders_lists_latest_first(self):
        newer = make_order(user=self.customer, total_amount="900.00")
        resp = self.client.get(reverse("dashboard-recent-orders"), {"limit": 5})
        self.assertEqual(resp.status_code, 200)
        rows = resp.data["data"]
        self.assertEqual(rows[0]["order_number"], newer.order_number)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

class ReportsTests(DashboardTestBase):
    def test_sales_report_requires_date_range(self):
        resp = self.client.get(reverse("report-sales"))
        self.assertEqual(resp.status_code, 400)

    def test_sales_report_with_valid_range(self):
        today = timezone.now().date()
        resp = self.client.get(reverse("report-sales"), {
            "date_from": (today - timezone.timedelta(days=6)).isoformat(),
            "date_to": today.isoformat(),
            "group_by": "day",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["data"]), 7)

    def test_product_performance_report(self):
        resp = self.client.get(reverse("report-products"))
        self.assertEqual(resp.status_code, 200)
        rows = resp.data["data"]
        self.assertEqual(rows[0]["name"], "Glow Serum")
        self.assertEqual(rows[0]["units_sold"], 2)

    def test_customer_report(self):
        resp = self.client.get(reverse("report-customers"))
        self.assertEqual(resp.status_code, 200)
        rows = resp.data["data"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["email"], self.customer.email)
        self.assertEqual(Decimal(rows[0]["total_spent"]), Decimal("500.00"))

    def test_inventory_report(self):
        from catalog.models import ProductVariant
        ProductVariant.objects.create(
            product=self.product, name="Default", sku=f"VAR-{uuid.uuid4().hex[:8]}",
            price=Decimal("500.00"), stock_quantity=3,
        )
        resp = self.client.get(reverse("report-inventory"), {"low_stock_threshold": 5})
        self.assertEqual(resp.status_code, 200)
        rows = resp.data["data"]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["is_low_stock"])
        self.assertFalse(rows[0]["is_out_of_stock"])

    def test_order_status_breakdown(self):
        resp = self.client.get(reverse("report-order-status"))
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(data["by_order_status"].get(OrderStatus.CONFIRMED), 1)
        self.assertEqual(data["by_payment_status"].get(PaymentStatus.PAID), 1)


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

class AnalyticsTests(DashboardTestBase):
    def test_revenue_trend(self):
        resp = self.client.get(reverse("analytics-revenue-trend"), {"period": "weekly"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("growth_rate_percentage", resp.data["data"])

    def test_category_performance(self):
        resp = self.client.get(reverse("analytics-category-performance"))
        self.assertEqual(resp.status_code, 200)
        rows = resp.data["data"]
        self.assertEqual(rows[0]["name"], "Beauty")
        self.assertEqual(rows[0]["product_count"], 1)

    def test_customer_growth(self):
        resp = self.client.get(reverse("analytics-customer-growth"), {"period": "weekly"})
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(len(data["labels"]), 7)
        self.assertEqual(data["cumulative_customers"][-1], User.objects.count())

    def test_average_order_value_trend(self):
        resp = self.client.get(reverse("analytics-average-order-value"), {"period": "weekly"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["data"]["average_order_value"]), 7)
