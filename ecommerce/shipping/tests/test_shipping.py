"""
shipping/tests/test_shipping.py

Standard Django TestCase suite (matches this project's absence of a
pytest config — run with `python manage.py test shipping`).

Shiprocket is never actually hit over the network: every test mocks
either the HTTP layer (`requests.post`/`requests.request`) for the
token-caching tests, or the higher-level functions in
shipping.providers.shiprocket_provider for everything else — so these
tests exercise only this project's own guard clauses, status mapping,
idempotency, and permission logic.
"""

import json
import uuid
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from catalog.models import Category, Product, ProductVariant
from orders.constants import FulfillmentStatus, OrderStatus, PaymentStatus
from orders.models import Order, OrderItem
from shipping.constants import ShipmentStatus, map_shiprocket_status
from shipping.models import Shipment, ShiprocketWebhookEvent
from shipping.providers import shiprocket_provider
from users.models import User

SHIPPING_SNAPSHOT = {
    "full_name": "Jane Doe",
    "phone": "+919876543210",
    "line1": "123 MG Road",
    "line2": "",
    "city": "Bengaluru",
    "state": "Karnataka",
    "postal_code": "560001",
    "country": "India",
}


def make_category():
    return Category.objects.create(name=f"Cat-{uuid.uuid4().hex[:6]}")


def make_product(category, weight=Decimal("0.750")):
    product = Product.objects.create(
        category=category,
        name=f"Product {uuid.uuid4().hex[:6]}",
        sku=f"SKU-{uuid.uuid4().hex[:8].upper()}",
        base_price=Decimal("100.00"),
    )
    variant = ProductVariant.objects.create(
        product=product,
        name="Default",
        sku=f"VAR-{uuid.uuid4().hex[:8].upper()}",
        price=Decimal("100.00"),
        stock_quantity=10,
        weight=weight,
        is_default=True,
    )
    return product, variant


def make_order(*, user=None, guest_session=None, total_amount="500.00",
                status=OrderStatus.CONFIRMED, payment_status=PaymentStatus.PAID,
                shipping_address=None, with_items=True):
    order = Order.objects.create(
        order_number=f"ORD-TEST-{uuid.uuid4().hex[:8].upper()}",
        user=user,
        guest_session=guest_session,
        customer_email="buyer@example.com",
        customer_phone="+919876543210",
        subtotal=Decimal(total_amount),
        total_amount=Decimal(total_amount),
        status=status,
        payment_status=payment_status,
        shipping_address_snapshot=SHIPPING_SNAPSHOT if shipping_address is not False else {},
        billing_address_snapshot=SHIPPING_SNAPSHOT if shipping_address is not False else {},
    )
    if with_items:
        category = make_category()
        product, variant = make_product(category)
        OrderItem.objects.create(
            order=order,
            product=product,
            variant=variant,
            product_name=product.name,
            variant_name=variant.name,
            sku=variant.sku,
            unit_price=Decimal("100.00"),
            quantity=2,
            total_price=Decimal("200.00"),
        )
    return order


def make_admin_user(email="admin@example.com"):
    return User.objects.create_superuser(email=email, password="adminpass123")


def make_customer(email="buyer@example.com"):
    return User.objects.create_user(email=email, password="pass12345")


def make_shipment(order, **overrides):
    defaults = dict(
        order=order,
        shiprocket_order_id="SR-ORDER-1",
        shiprocket_shipment_id="SR-SHIP-1",
        status=ShipmentStatus.CREATED,
        pickup_location="Primary",
        package_weight_kg=Decimal("1.500"),
    )
    defaults.update(overrides)
    return Shipment.objects.create(**defaults)


# ---------------------------------------------------------------------------
# Token caching
# ---------------------------------------------------------------------------

class TokenCachingTests(TestCase):
    def setUp(self):
        cache.clear()
        self._settings_override = override_settings(
            SHIPROCKET_EMAIL="ops@example.com", SHIPROCKET_PASSWORD="secretpass",
        )
        self._settings_override.enable()

    def tearDown(self):
        cache.clear()
        self._settings_override.disable()

    @mock.patch("shipping.providers.shiprocket_provider.requests.post")
    def test_first_call_logs_in_and_caches_token(self, mock_post):
        mock_post.return_value = mock.Mock(status_code=200, json=lambda: {"token": "tok_1"})

        token = shiprocket_provider.get_token()

        self.assertEqual(token, "tok_1")
        mock_post.assert_called_once()

    @mock.patch("shipping.providers.shiprocket_provider.requests.post")
    def test_subsequent_calls_reuse_cached_token(self, mock_post):
        mock_post.return_value = mock.Mock(status_code=200, json=lambda: {"token": "tok_2"})

        token1 = shiprocket_provider.get_token()
        token2 = shiprocket_provider.get_token()
        token3 = shiprocket_provider.get_token()

        self.assertEqual(token1, token2)
        self.assertEqual(token2, token3)
        mock_post.assert_called_once()  # login only happened once

    @mock.patch("shipping.providers.shiprocket_provider.requests.post")
    def test_force_refresh_logs_in_again(self, mock_post):
        mock_post.side_effect = [
            mock.Mock(status_code=200, json=lambda: {"token": "tok_a"}),
            mock.Mock(status_code=200, json=lambda: {"token": "tok_b"}),
        ]

        token1 = shiprocket_provider.get_token()
        token2 = shiprocket_provider.get_token(force_refresh=True)

        self.assertEqual(token1, "tok_a")
        self.assertEqual(token2, "tok_b")
        self.assertEqual(mock_post.call_count, 2)

    @mock.patch("shipping.providers.shiprocket_provider.requests.request")
    @mock.patch("shipping.providers.shiprocket_provider.requests.post")
    def test_401_triggers_token_refresh_and_retry(self, mock_post, mock_request):
        mock_post.side_effect = [
            mock.Mock(status_code=200, json=lambda: {"token": "expired_tok"}),
            mock.Mock(status_code=200, json=lambda: {"token": "fresh_tok"}),
        ]
        mock_request.side_effect = [
            mock.Mock(status_code=401, json=lambda: {"message": "expired"}, text="expired"),
            mock.Mock(status_code=200, json=lambda: {"order_id": "SR1", "shipment_id": "SH1"}),
        ]

        result = shiprocket_provider.create_order({"order_id": "ORD-1"})

        self.assertEqual(result["order_id"], "SR1")
        self.assertEqual(mock_post.call_count, 2)  # logged in, then re-logged in after 401
        self.assertEqual(mock_request.call_count, 2)  # first attempt + retry

    @mock.patch("shipping.providers.shiprocket_provider.requests.post")
    def test_missing_credentials_raises_authentication_error(self, mock_post):
        from shipping.exceptions import ShiprocketAuthenticationFailed

        with override_settings(SHIPROCKET_EMAIL="", SHIPROCKET_PASSWORD=""):
            with self.assertRaises(ShiprocketAuthenticationFailed):
                shiprocket_provider.get_token(force_refresh=True)
        mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# GET /api/shipping/serviceability/
# ---------------------------------------------------------------------------

class ServiceabilityTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @mock.patch("shipping.providers.shiprocket_provider.check_serviceability")
    def test_serviceability_check_does_not_require_authentication(self, mock_check):
        mock_check.return_value = {"available_courier_companies": []}

        resp = self.client.get(reverse("shipping-serviceability"), {"delivery_postcode": "560001"})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "success")
        mock_check.assert_called_once()

    def test_serviceability_requires_delivery_postcode(self):
        resp = self.client.get(reverse("shipping-serviceability"), {})
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# POST /api/admin/orders/<uuid:order_id>/shipping/create/
# ---------------------------------------------------------------------------

class AdminCreateShipmentTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make_admin_user()
        self.customer = make_customer()
        self.order = make_order(user=self.customer)
        self.client.force_authenticate(user=self.admin)

    def _url(self, order_id):
        return reverse("admin-shipment-create", args=[order_id])

    @mock.patch("shipping.providers.shiprocket_provider.create_order")
    def test_create_shipment_success(self, mock_create):
        mock_create.return_value = {"order_id": "SR-1001", "shipment_id": "SH-2001", "status": "NEW"}

        resp = self.client.post(self._url(self.order.id), {}, format="json")

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["status"], "success")

        shipment = Shipment.objects.get(order=self.order)
        self.assertEqual(shipment.shiprocket_order_id, "SR-1001")
        self.assertEqual(shipment.shiprocket_shipment_id, "SH-2001")
        self.assertEqual(shipment.status, ShipmentStatus.CREATED)
        # Weight computed server-side from the OrderItem/variant, never from the request.
        self.assertEqual(shipment.package_weight_kg, Decimal("1.500"))  # 0.750kg * 2 units

        self.order.refresh_from_db()
        self.assertEqual(self.order.fulfillment_status, FulfillmentStatus.PROCESSING)

        # Payload sent to Shiprocket never includes anything the client
        # could have supplied — all pulled from order/items.
        sent_payload = mock_create.call_args[0][0]
        self.assertEqual(sent_payload["order_id"], self.order.order_number)
        self.assertEqual(sent_payload["sub_total"], str(self.order.subtotal))
        self.assertEqual(len(sent_payload["order_items"]), 1)

    @mock.patch("shipping.providers.shiprocket_provider.create_order")
    def test_duplicate_shipment_is_rejected(self, mock_create):
        mock_create.return_value = {"order_id": "SR-1", "shipment_id": "SH-1"}
        self.client.post(self._url(self.order.id), {}, format="json")

        resp = self.client.post(self._url(self.order.id), {}, format="json")

        self.assertEqual(resp.status_code, 409)
        self.assertEqual(Shipment.objects.filter(order=self.order).count(), 1)
        mock_create.assert_called_once()

    def test_unpaid_order_is_rejected(self):
        unpaid_order = make_order(user=self.customer, payment_status=PaymentStatus.PENDING, status=OrderStatus.PENDING)

        resp = self.client.post(self._url(unpaid_order.id), {}, format="json")

        self.assertEqual(resp.status_code, 409)
        self.assertFalse(Shipment.objects.filter(order=unpaid_order).exists())

    def test_missing_shipping_address_is_rejected(self):
        order_no_address = make_order(user=self.customer, shipping_address=False)

        resp = self.client.post(self._url(order_no_address.id), {}, format="json")

        self.assertEqual(resp.status_code, 400)

    def test_order_in_non_shippable_status_is_rejected(self):
        cancelled_order = make_order(user=self.customer, status=OrderStatus.CANCELLED)

        resp = self.client.post(self._url(cancelled_order.id), {}, format="json")

        self.assertEqual(resp.status_code, 409)

    def test_invalid_order_returns_404(self):
        resp = self.client.post(self._url(uuid.uuid4()), {}, format="json")
        self.assertEqual(resp.status_code, 404)

    def test_unauthenticated_request_is_rejected(self):
        self.client.force_authenticate(user=None)
        resp = self.client.post(self._url(self.order.id), {}, format="json")
        self.assertEqual(resp.status_code, 401)

    def test_non_admin_customer_is_forbidden(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post(self._url(self.order.id), {}, format="json")
        self.assertEqual(resp.status_code, 403)


# ---------------------------------------------------------------------------
# POST /api/admin/shipments/<uuid:id>/assign-awb/
# ---------------------------------------------------------------------------

class AdminAssignAWBTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make_admin_user()
        self.customer = make_customer()
        self.order = make_order(user=self.customer)
        self.shipment = make_shipment(self.order)
        self.client.force_authenticate(user=self.admin)

    def _url(self, shipment_id):
        return reverse("admin-shipment-assign-awb", args=[shipment_id])

    @mock.patch("shipping.providers.shiprocket_provider.assign_awb")
    def test_assign_awb_success(self, mock_assign):
        mock_assign.return_value = {
            "response": {"data": {"awb_code": "AWB123", "courier_name": "Delhivery", "courier_company_id": 5}}
        }

        resp = self.client.post(self._url(self.shipment.id), {}, format="json")

        self.assertEqual(resp.status_code, 200)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.awb_code, "AWB123")
        self.assertEqual(self.shipment.courier_name, "Delhivery")
        self.assertEqual(self.shipment.status, ShipmentStatus.AWB_ASSIGNED)

    @mock.patch("shipping.providers.shiprocket_provider.assign_awb")
    def test_awb_failure_when_shiprocket_returns_no_code(self, mock_assign):
        mock_assign.return_value = {"response": {"data": {}}}

        resp = self.client.post(self._url(self.shipment.id), {}, format="json")

        self.assertEqual(resp.status_code, 502)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.awb_code, "")

    def test_already_assigned_awb_is_rejected(self):
        self.shipment.awb_code = "EXISTING"
        self.shipment.save(update_fields=["awb_code"])

        resp = self.client.post(self._url(self.shipment.id), {}, format="json")

        self.assertEqual(resp.status_code, 409)

    def test_shipment_not_found(self):
        resp = self.client.post(self._url(uuid.uuid4()), {}, format="json")
        self.assertEqual(resp.status_code, 404)


# ---------------------------------------------------------------------------
# POST /api/admin/shipments/<uuid:id>/label/  and  /manifest/
# ---------------------------------------------------------------------------

class AdminLabelManifestTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make_admin_user()
        self.customer = make_customer()
        self.order = make_order(user=self.customer)
        self.client.force_authenticate(user=self.admin)

    @mock.patch("shipping.providers.shiprocket_provider.generate_label")
    def test_generate_label_success(self, mock_label):
        shipment = make_shipment(self.order)
        mock_label.return_value = {"label_url": "https://labels.example.com/1.pdf"}

        resp = self.client.post(reverse("admin-shipment-label", args=[shipment.id]), {}, format="json")

        self.assertEqual(resp.status_code, 200)
        shipment.refresh_from_db()
        self.assertEqual(shipment.label_url, "https://labels.example.com/1.pdf")

    def test_manifest_requires_awb(self):
        shipment = make_shipment(self.order, awb_code="")

        resp = self.client.post(reverse("admin-shipment-manifest", args=[shipment.id]), {}, format="json")

        self.assertEqual(resp.status_code, 409)

    @mock.patch("shipping.providers.shiprocket_provider.generate_manifest")
    def test_generate_manifest_success(self, mock_manifest):
        shipment = make_shipment(self.order, awb_code="AWB999")
        mock_manifest.return_value = {"manifest_url": "https://manifests.example.com/1.pdf"}

        resp = self.client.post(reverse("admin-shipment-manifest", args=[shipment.id]), {}, format="json")

        self.assertEqual(resp.status_code, 200)
        shipment.refresh_from_db()
        self.assertEqual(shipment.manifest_url, "https://manifests.example.com/1.pdf")


# ---------------------------------------------------------------------------
# Tracking: GET /api/admin/shipments/<id>/tracking/  and  GET /api/orders/<id>/tracking/
# ---------------------------------------------------------------------------

class TrackingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make_admin_user()
        self.customer = make_customer()
        self.other_customer = make_customer(email="other@example.com")
        self.order = make_order(
            user=self.customer, status=OrderStatus.OUT_FOR_DELIVERY, payment_status=PaymentStatus.PAID,
        )
        self.order.fulfillment_status = FulfillmentStatus.OUT_FOR_DELIVERY
        self.order.save(update_fields=["fulfillment_status"])
        self.shipment = make_shipment(self.order, awb_code="AWB555", status=ShipmentStatus.OUT_FOR_DELIVERY)

    @mock.patch("shipping.providers.shiprocket_provider.track_by_awb")
    def test_admin_tracking_refreshes_and_syncs_status(self, mock_track):
        mock_track.return_value = {
            "tracking_data": {"shipment_track": [{"current_status": "Delivered"}]}
        }
        self.client.force_authenticate(user=self.admin)

        resp = self.client.get(reverse("admin-shipment-tracking", args=[self.shipment.id]))

        self.assertEqual(resp.status_code, 200)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, ShipmentStatus.DELIVERED)
        self.assertIsNotNone(self.shipment.delivered_at)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.DELIVERED)
        self.assertEqual(self.order.fulfillment_status, FulfillmentStatus.DELIVERED)

    def test_tracking_unavailable_without_awb(self):
        bare_order = make_order(user=self.customer)
        shipment_no_awb = make_shipment(bare_order, awb_code="", shiprocket_order_id="SR-X")
        self.client.force_authenticate(user=self.admin)

        resp = self.client.get(reverse("admin-shipment-tracking", args=[shipment_no_awb.id]))

        self.assertEqual(resp.status_code, 409)

    @mock.patch("shipping.providers.shiprocket_provider.track_by_awb")
    def test_tracking_failure_surfaces_as_502(self, mock_track):
        mock_track.side_effect = Exception("boom")
        self.client.force_authenticate(user=self.admin)

        resp = self.client.get(reverse("admin-shipment-tracking", args=[self.shipment.id]))

        self.assertEqual(resp.status_code, 502)

    def test_customer_can_track_own_order(self):
        self.client.force_authenticate(user=self.customer)

        resp = self.client.get(reverse("order-tracking", args=[self.order.id]))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["awb_code"], "AWB555")

    def test_customer_cannot_track_someone_elses_order(self):
        self.client.force_authenticate(user=self.other_customer)

        resp = self.client.get(reverse("order-tracking", args=[self.order.id]))

        self.assertEqual(resp.status_code, 404)  # existence not leaked

    def test_order_without_shipment_returns_404(self):
        bare_order = make_order(user=self.customer)
        self.client.force_authenticate(user=self.customer)

        resp = self.client.get(reverse("order-tracking", args=[bare_order.id]))

        self.assertEqual(resp.status_code, 404)


# ---------------------------------------------------------------------------
# POST /api/admin/shipments/<uuid:id>/cancel/
# ---------------------------------------------------------------------------

class CancelShipmentTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make_admin_user()
        self.customer = make_customer()
        self.order = make_order(user=self.customer)
        self.client.force_authenticate(user=self.admin)

    @mock.patch("shipping.providers.shiprocket_provider.cancel_order")
    def test_cancel_shipment_success(self, mock_cancel):
        shipment = make_shipment(self.order, status=ShipmentStatus.CREATED)
        mock_cancel.return_value = {"message": "cancelled"}

        resp = self.client.post(reverse("admin-shipment-cancel", args=[shipment.id]), {}, format="json")

        self.assertEqual(resp.status_code, 200)
        shipment.refresh_from_db()
        self.assertEqual(shipment.status, ShipmentStatus.CANCELLED)
        self.assertIsNotNone(shipment.cancelled_at)

        self.order.refresh_from_db()
        self.assertEqual(self.order.fulfillment_status, FulfillmentStatus.CANCELLED)

    def test_cannot_cancel_already_delivered_shipment(self):
        shipment = make_shipment(self.order, status=ShipmentStatus.DELIVERED)

        resp = self.client.post(reverse("admin-shipment-cancel", args=[shipment.id]), {}, format="json")

        self.assertEqual(resp.status_code, 409)

    @mock.patch("shipping.providers.shiprocket_provider.cancel_order")
    def test_cancellation_failure_surfaces_as_502(self, mock_cancel):
        shipment = make_shipment(self.order, status=ShipmentStatus.CREATED)
        mock_cancel.side_effect = Exception("Shiprocket unreachable")

        resp = self.client.post(reverse("admin-shipment-cancel", args=[shipment.id]), {}, format="json")

        self.assertEqual(resp.status_code, 502)
        shipment.refresh_from_db()
        self.assertEqual(shipment.status, ShipmentStatus.CREATED)  # unchanged on failure


# ---------------------------------------------------------------------------
# Status synchronization (mapping + propagation)
# ---------------------------------------------------------------------------

class StatusSyncTests(TestCase):
    def setUp(self):
        self.customer = make_customer()

    def test_status_keyword_mapping(self):
        self.assertEqual(map_shiprocket_status("Delivered"), ShipmentStatus.DELIVERED)
        self.assertEqual(map_shiprocket_status("Out for Delivery"), ShipmentStatus.OUT_FOR_DELIVERY)
        self.assertEqual(map_shiprocket_status("PICKED UP"), ShipmentStatus.PICKED_UP)
        self.assertEqual(map_shiprocket_status("In Transit"), ShipmentStatus.IN_TRANSIT)
        self.assertEqual(map_shiprocket_status("RTO Initiated"), ShipmentStatus.RTO)
        self.assertEqual(map_shiprocket_status("Canceled"), ShipmentStatus.CANCELLED)
        self.assertIsNone(map_shiprocket_status("Some Unknown Status"))
        self.assertIsNone(map_shiprocket_status(""))

    def test_sync_propagates_to_order_status(self):
        from shipping import services

        order = make_order(user=self.customer, status=OrderStatus.PACKED, payment_status=PaymentStatus.PAID)
        order.fulfillment_status = FulfillmentStatus.PACKED
        order.save(update_fields=["fulfillment_status"])
        shipment = make_shipment(order, status=ShipmentStatus.AWB_ASSIGNED, awb_code="AWB1")

        services.sync_shipment_status(shipment, "Picked Up")

        shipment.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(shipment.status, ShipmentStatus.PICKED_UP)
        self.assertEqual(order.status, OrderStatus.SHIPPED)
        self.assertEqual(order.fulfillment_status, FulfillmentStatus.SHIPPED)

    def test_sync_is_idempotent_for_repeated_status(self):
        from shipping import services

        order = make_order(user=self.customer, status=OrderStatus.SHIPPED, payment_status=PaymentStatus.PAID)
        order.fulfillment_status = FulfillmentStatus.SHIPPED
        order.save(update_fields=["fulfillment_status"])
        shipment = make_shipment(order, status=ShipmentStatus.PICKED_UP, awb_code="AWB2")

        # Same status delivered twice must not raise or double-log.
        services.sync_shipment_status(shipment, "Picked Up")
        services.sync_shipment_status(shipment, "Picked Up")

        shipment.refresh_from_db()
        self.assertEqual(shipment.status, ShipmentStatus.PICKED_UP)

    def test_sync_swallows_invalid_order_transition(self):
        """An order already DELIVERED must not blow up on a later RTO/duplicate event."""
        from shipping import services

        order = make_order(user=self.customer, status=OrderStatus.DELIVERED, payment_status=PaymentStatus.PAID)
        order.fulfillment_status = FulfillmentStatus.DELIVERED
        order.save(update_fields=["fulfillment_status"])
        shipment = make_shipment(order, status=ShipmentStatus.OUT_FOR_DELIVERY, awb_code="AWB3")

        # Should not raise even though DELIVERED -> DELIVERED isn't a valid transition.
        services.sync_shipment_status(shipment, "Delivered")

        shipment.refresh_from_db()
        self.assertEqual(shipment.status, ShipmentStatus.DELIVERED)


# ---------------------------------------------------------------------------
# POST /api/shipping/webhooks/shiprocket/
# ---------------------------------------------------------------------------

class WebhookTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.customer = make_customer()
        self.order = make_order(user=self.customer, status=OrderStatus.PACKED)
        self.order.fulfillment_status = FulfillmentStatus.PACKED
        self.order.save(update_fields=["fulfillment_status"])
        self.shipment = make_shipment(self.order, awb_code="AWBWEBHOOK", status=ShipmentStatus.AWB_ASSIGNED)

    def _post_webhook(self, payload, token="whsecret"):
        raw_body = json.dumps(payload).encode("utf-8")
        return self.client.post(
            reverse("shiprocket-webhook"),
            data=raw_body,
            content_type="application/json",
            HTTP_X_API_KEY=token,
        )

    def test_webhook_updates_shipment_and_order(self):
        from django.test import override_settings

        payload = {"awb": "AWBWEBHOOK", "current_status": "Picked Up", "order_id": "SR-ORDER-1"}
        with override_settings(SHIPROCKET_WEBHOOK_SECRET="whsecret"):
            resp = self._post_webhook(payload)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ShiprocketWebhookEvent.objects.count(), 1)

        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, ShipmentStatus.PICKED_UP)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.SHIPPED)

    def test_webhook_rejects_invalid_token(self):
        from django.test import override_settings

        payload = {"awb": "AWBWEBHOOK", "current_status": "Picked Up"}
        with override_settings(SHIPROCKET_WEBHOOK_SECRET="whsecret"):
            resp = self._post_webhook(payload, token="wrong-token")

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(ShiprocketWebhookEvent.objects.count(), 0)

    def test_duplicate_webhook_delivery_is_processed_once(self):
        from django.test import override_settings

        payload = {"awb": "AWBWEBHOOK", "current_status": "Picked Up", "order_id": "SR-ORDER-1"}
        with override_settings(SHIPROCKET_WEBHOOK_SECRET="whsecret"):
            resp1 = self._post_webhook(payload)
            resp2 = self._post_webhook(payload)

        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(ShiprocketWebhookEvent.objects.count(), 1)  # not duplicated

    def test_webhook_for_unknown_shipment_is_recorded_but_harmless(self):
        from django.test import override_settings

        payload = {"awb": "UNKNOWN-AWB", "current_status": "Picked Up"}
        with override_settings(SHIPROCKET_WEBHOOK_SECRET="whsecret"):
            resp = self._post_webhook(payload)

        self.assertEqual(resp.status_code, 200)
        event = ShiprocketWebhookEvent.objects.get()
        self.assertTrue(event.is_processed)
        self.assertIsNone(event.shipment)

    def test_webhook_with_no_secret_configured_allows_any_token(self):
        from django.test import override_settings

        payload = {"awb": "AWBWEBHOOK", "current_status": "Picked Up", "order_id": "SR-ORDER-1"}
        with override_settings(SHIPROCKET_WEBHOOK_SECRET=""):
            resp = self._post_webhook(payload, token="anything-or-nothing")

        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# Permissions matrix
# ---------------------------------------------------------------------------

class PermissionsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.customer = make_customer()
        self.staff = User.objects.create_staff(email="staff@example.com", password="staffpass123")
        self.manager = User.objects.create_user(
            email="manager@example.com", password="managerpass123", role=User.Role.MANAGER, is_staff=True,
        )
        self.order = make_order(user=self.customer)
        self.shipment = make_shipment(self.order)

    def test_staff_role_cannot_create_shipment(self):
        """Admin surface requires MANAGER or ADMIN — plain STAFF is insufficient."""
        self.client.force_authenticate(user=self.staff)
        resp = self.client.post(
            reverse("admin-shipment-create", args=[self.order.id]), {}, format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_manager_role_can_access_admin_cancel(self):
        self.client.force_authenticate(user=self.manager)
        with mock.patch("shipping.providers.shiprocket_provider.cancel_order", return_value={}):
            resp = self.client.post(
                reverse("admin-shipment-cancel", args=[self.shipment.id]), {}, format="json",
            )
        self.assertEqual(resp.status_code, 200)

    def test_anonymous_cannot_access_admin_tracking(self):
        resp = self.client.get(reverse("admin-shipment-tracking", args=[self.shipment.id]))
        self.assertEqual(resp.status_code, 401)

    def test_anonymous_cannot_access_order_tracking_without_guest_token(self):
        resp = self.client.get(reverse("order-tracking", args=[self.order.id]))
        self.assertEqual(resp.status_code, 401)

    def test_webhook_endpoint_requires_no_authentication(self):
        """The webhook is intentionally public — auth comes from the shared token."""
        with mock.patch("django.conf.settings.SHIPROCKET_WEBHOOK_SECRET", ""):
            resp = self.client.post(
                reverse("shiprocket-webhook"),
                data=json.dumps({"awb": "X", "current_status": "Picked Up"}).encode("utf-8"),
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 200)
