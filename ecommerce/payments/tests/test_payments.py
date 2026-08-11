"""
payments/tests/test_payments.py

Standard Django TestCase suite (matches this project's absence of a
pytest config — run with `python manage.py test payments`).

The Razorpay SDK itself is never hit: every test mocks the functions
in payments.providers.razorpay_provider, so these tests exercise only
this project's own signature-verification, amount-checking, status-
transition, and idempotency logic.
"""

import json
import uuid
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from orders.constants import OrderStatus, PaymentStatus
from orders.models import Order
from payments.constants import PaymentTransactionStatus
from payments.models import PaymentTransaction, PaymentWebhookEvent
from users.models import User


def make_order(*, user=None, guest_session=None, total_amount="500.00",
                status=OrderStatus.PENDING, payment_status=PaymentStatus.PENDING):
    return Order.objects.create(
        order_number=f"ORD-TEST-{uuid.uuid4().hex[:8].upper()}",
        user=user,
        guest_session=guest_session,
        customer_email="buyer@example.com",
        subtotal=Decimal(total_amount),
        total_amount=Decimal(total_amount),
        status=status,
        payment_status=payment_status,
    )


def make_admin_user(email="admin@example.com"):
    return User.objects.create_superuser(email=email, password="adminpass123")


# ---------------------------------------------------------------------------
# POST /api/payments/razorpay/create/
# ---------------------------------------------------------------------------

class RazorpayCreateOrderTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email="buyer1@example.com", password="pass12345")
        self.order = make_order(user=self.user, total_amount="500.00")
        self.client.force_authenticate(user=self.user)

    @mock.patch("payments.providers.razorpay_provider.create_order")
    def test_create_razorpay_order_success(self, mock_create):
        mock_create.return_value = {"id": "order_RZP1", "amount": 50000, "currency": "INR", "status": "created"}

        resp = self.client.post(
            reverse("razorpay-create-order"), {"order_id": str(self.order.id)}, format="json",
        )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["status"], "success")
        self.assertEqual(resp.data["data"]["razorpay_order_id"], "order_RZP1")
        self.assertEqual(resp.data["data"]["amount"], 50000)

        txn = PaymentTransaction.objects.get(order=self.order)
        self.assertEqual(txn.razorpay_order_id, "order_RZP1")
        self.assertEqual(txn.amount_paise, 50000)
        self.assertEqual(txn.status, PaymentTransactionStatus.CREATED)
        mock_create.assert_called_once()

    @mock.patch("payments.providers.razorpay_provider.create_order")
    def test_create_is_idempotent_for_repeat_calls(self, mock_create):
        mock_create.return_value = {"id": "order_RZP2", "amount": 50000, "currency": "INR", "status": "created"}

        resp1 = self.client.post(reverse("razorpay-create-order"), {"order_id": str(self.order.id)}, format="json")
        resp2 = self.client.post(reverse("razorpay-create-order"), {"order_id": str(self.order.id)}, format="json")

        self.assertEqual(resp1.data["data"]["razorpay_order_id"], resp2.data["data"]["razorpay_order_id"])
        self.assertEqual(PaymentTransaction.objects.filter(order=self.order).count(), 1)
        mock_create.assert_called_once()  # second request reused the existing transaction

    def test_create_rejects_order_not_owned_by_caller(self):
        other_user = User.objects.create_user(email="other1@example.com", password="pass12345")
        other_order = make_order(user=other_user)

        resp = self.client.post(reverse("razorpay-create-order"), {"order_id": str(other_order.id)}, format="json")

        self.assertEqual(resp.status_code, 404)
        self.assertEqual(PaymentTransaction.objects.count(), 0)

    def test_create_rejects_non_payable_order(self):
        cancelled_order = make_order(user=self.user, status=OrderStatus.CANCELLED)

        resp = self.client.post(reverse("razorpay-create-order"), {"order_id": str(cancelled_order.id)}, format="json")

        self.assertEqual(resp.status_code, 409)


# ---------------------------------------------------------------------------
# POST /api/payments/razorpay/verify/
# ---------------------------------------------------------------------------

class RazorpayVerifyPaymentTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email="buyer2@example.com", password="pass12345")
        self.order = make_order(user=self.user, total_amount="500.00")
        self.txn = PaymentTransaction.objects.create(
            order=self.order,
            razorpay_order_id="order_ABC",
            amount=Decimal("500.00"),
            amount_paise=50000,
            currency="INR",
            status=PaymentTransactionStatus.CREATED,
        )
        self.client.force_authenticate(user=self.user)
        self.payload = {
            "razorpay_order_id": "order_ABC",
            "razorpay_payment_id": "pay_123",
            "razorpay_signature": "sig_abc",
        }

    @mock.patch("payments.providers.razorpay_provider.fetch_payment")
    @mock.patch("payments.providers.razorpay_provider.verify_payment_signature")
    def test_successful_payment_marks_order_paid_and_confirmed(self, mock_verify_sig, mock_fetch):
        mock_verify_sig.return_value = True
        mock_fetch.return_value = {"order_id": "order_ABC", "amount": 50000, "currency": "INR", "status": "captured"}

        resp = self.client.post(reverse("razorpay-verify-payment"), self.payload, format="json")

        self.assertEqual(resp.status_code, 200)
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.status, PaymentTransactionStatus.PAID)
        self.assertEqual(self.txn.razorpay_payment_id, "pay_123")

        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, PaymentStatus.PAID)
        self.assertEqual(self.order.status, OrderStatus.CONFIRMED)

    @mock.patch("payments.providers.razorpay_provider.fetch_payment")
    @mock.patch("payments.providers.razorpay_provider.verify_payment_signature")
    def test_failed_payment_status_from_razorpay(self, mock_verify_sig, mock_fetch):
        mock_verify_sig.return_value = True
        mock_fetch.return_value = {"order_id": "order_ABC", "amount": 50000, "currency": "INR", "status": "failed"}

        resp = self.client.post(reverse("razorpay-verify-payment"), self.payload, format="json")

        self.assertEqual(resp.status_code, 400)
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.status, PaymentTransactionStatus.FAILED)

        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, PaymentStatus.FAILED)
        # Order itself is left alone (not auto-cancelled) so the customer can retry.
        self.assertEqual(self.order.status, OrderStatus.PENDING)

    @mock.patch("payments.providers.razorpay_provider.fetch_payment")
    @mock.patch("payments.providers.razorpay_provider.verify_payment_signature")
    def test_invalid_signature_is_rejected_without_trusting_frontend(self, mock_verify_sig, mock_fetch):
        mock_verify_sig.return_value = False

        resp = self.client.post(reverse("razorpay-verify-payment"), self.payload, format="json")

        self.assertEqual(resp.status_code, 400)
        mock_fetch.assert_not_called()  # never even asks Razorpay for the payment once the signature fails

        self.txn.refresh_from_db()
        self.assertEqual(self.txn.status, PaymentTransactionStatus.FAILED)
        self.assertIn("Signature", self.txn.failure_reason)

    @mock.patch("payments.providers.razorpay_provider.fetch_payment")
    @mock.patch("payments.providers.razorpay_provider.verify_payment_signature")
    def test_duplicate_verification_is_idempotent(self, mock_verify_sig, mock_fetch):
        mock_verify_sig.return_value = True
        mock_fetch.return_value = {"order_id": "order_ABC", "amount": 50000, "currency": "INR", "status": "captured"}

        resp1 = self.client.post(reverse("razorpay-verify-payment"), self.payload, format="json")
        resp2 = self.client.post(reverse("razorpay-verify-payment"), self.payload, format="json")

        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        # The second call must not re-verify against Razorpay at all.
        mock_fetch.assert_called_once()
        self.assertEqual(PaymentTransaction.objects.filter(order=self.order).count(), 1)


# ---------------------------------------------------------------------------
# POST /api/payments/webhooks/razorpay/
# ---------------------------------------------------------------------------

class RazorpayWebhookTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email="buyer3@example.com", password="pass12345")
        self.order = make_order(user=self.user, total_amount="750.00")
        self.txn = PaymentTransaction.objects.create(
            order=self.order,
            razorpay_order_id="order_WH1",
            amount=Decimal("750.00"),
            amount_paise=75000,
            currency="INR",
            status=PaymentTransactionStatus.CREATED,
        )

    def _post_webhook(self, payload, event_id="evt_1", signature="sig_wh"):
        raw_body = json.dumps(payload).encode("utf-8")
        return self.client.post(
            reverse("razorpay-webhook"),
            data=raw_body,
            content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE=signature,
            HTTP_X_RAZORPAY_EVENT_ID=event_id,
        )

    @mock.patch("payments.providers.razorpay_provider.verify_webhook_signature")
    def test_payment_captured_webhook_marks_order_paid(self, mock_verify):
        mock_verify.return_value = True
        payload = {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_WH1", "order_id": "order_WH1",
                        "amount": 75000, "currency": "INR", "status": "captured",
                    }
                }
            },
        }

        resp = self._post_webhook(payload)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PaymentWebhookEvent.objects.count(), 1)

        self.txn.refresh_from_db()
        self.assertEqual(self.txn.status, PaymentTransactionStatus.PAID)

        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, PaymentStatus.PAID)

    @mock.patch("payments.providers.razorpay_provider.verify_webhook_signature")
    def test_invalid_webhook_signature_is_rejected(self, mock_verify):
        mock_verify.return_value = False
        payload = {"event": "payment.captured", "payload": {}}

        resp = self._post_webhook(payload)

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(PaymentWebhookEvent.objects.count(), 0)

    @mock.patch("payments.providers.razorpay_provider.verify_webhook_signature")
    def test_duplicate_webhook_delivery_is_processed_once(self, mock_verify):
        mock_verify.return_value = True
        payload = {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_WH2", "order_id": "order_WH1",
                        "amount": 75000, "currency": "INR", "status": "captured",
                    }
                }
            },
        }

        resp1 = self._post_webhook(payload, event_id="evt_dup")
        resp2 = self._post_webhook(payload, event_id="evt_dup")  # Razorpay retry, same event id

        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(PaymentWebhookEvent.objects.filter(event_id="evt_dup").count(), 1)

    def test_missing_signature_header_is_rejected(self):
        raw_body = json.dumps({"event": "payment.captured", "payload": {}}).encode("utf-8")
        resp = self.client.post(
            reverse("razorpay-webhook"), data=raw_body, content_type="application/json",
            HTTP_X_RAZORPAY_EVENT_ID="evt_no_sig",
        )
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# Refunds — POST /api/admin/orders/<uuid:order_id>/refund/
# ---------------------------------------------------------------------------

class RefundTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make_admin_user()
        self.buyer = User.objects.create_user(email="buyer4@example.com", password="pass12345")
        self.order = make_order(
            user=self.buyer, total_amount="1000.00",
            status=OrderStatus.CONFIRMED, payment_status=PaymentStatus.PAID,
        )
        self.txn = PaymentTransaction.objects.create(
            order=self.order,
            razorpay_order_id="order_RFND",
            razorpay_payment_id="pay_RFND",
            amount=Decimal("1000.00"),
            amount_paise=100000,
            currency="INR",
            status=PaymentTransactionStatus.PAID,
        )
        self.client.force_authenticate(user=self.admin)

    @mock.patch("payments.providers.razorpay_provider.create_refund")
    def test_full_refund(self, mock_refund):
        mock_refund.return_value = {"id": "rfnd_full", "amount": 100000, "status": "processed"}

        resp = self.client.post(
            reverse("admin-order-refund", kwargs={"order_id": self.order.id}), {}, format="json",
        )

        self.assertEqual(resp.status_code, 200)
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.status, PaymentTransactionStatus.REFUNDED)
        self.assertEqual(self.txn.refunded_amount, Decimal("1000.00"))
        self.assertEqual(self.txn.refundable_amount, Decimal("0.00"))

        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, PaymentStatus.REFUNDED)

        mock_refund.assert_called_once_with(
            payment_id="pay_RFND", amount_paise=100000, notes={"order_id": str(self.order.id)},
        )

    @mock.patch("payments.providers.razorpay_provider.create_refund")
    def test_partial_refund(self, mock_refund):
        mock_refund.return_value = {"id": "rfnd_partial", "amount": 40000, "status": "processed"}

        resp = self.client.post(
            reverse("admin-order-refund", kwargs={"order_id": self.order.id}),
            {"amount": "400.00"}, format="json",
        )

        self.assertEqual(resp.status_code, 200)
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.status, PaymentTransactionStatus.PARTIALLY_REFUNDED)
        self.assertEqual(self.txn.refunded_amount, Decimal("400.00"))
        self.assertEqual(self.txn.refundable_amount, Decimal("600.00"))

        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, PaymentStatus.PARTIALLY_REFUNDED)

    @mock.patch("payments.providers.razorpay_provider.create_refund")
    def test_refund_amount_exceeding_refundable_is_rejected(self, mock_refund):
        resp = self.client.post(
            reverse("admin-order-refund", kwargs={"order_id": self.order.id}),
            {"amount": "5000.00"}, format="json",
        )

        self.assertEqual(resp.status_code, 400)
        mock_refund.assert_not_called()
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.refunded_amount, Decimal("0.00"))

    @mock.patch("payments.providers.razorpay_provider.create_refund")
    def test_second_partial_refund_cannot_exceed_remaining_refundable(self, mock_refund):
        mock_refund.return_value = {"id": "rfnd_p1", "amount": 70000, "status": "processed"}
        first = self.client.post(
            reverse("admin-order-refund", kwargs={"order_id": self.order.id}),
            {"amount": "700.00"}, format="json",
        )
        self.assertEqual(first.status_code, 200)

        # Only 300.00 left refundable — asking for 400.00 must fail.
        second = self.client.post(
            reverse("admin-order-refund", kwargs={"order_id": self.order.id}),
            {"amount": "400.00"}, format="json",
        )
        self.assertEqual(second.status_code, 400)

        self.txn.refresh_from_db()
        self.assertEqual(self.txn.refunded_amount, Decimal("700.00"))

    def test_refund_requires_manager_or_admin_role(self):
        self.client.force_authenticate(user=self.buyer)
        resp = self.client.post(
            reverse("admin-order-refund", kwargs={"order_id": self.order.id}), {}, format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_refund_not_possible_when_order_never_paid(self):
        unpaid_order = make_order(user=self.buyer, total_amount="200.00")
        resp = self.client.post(
            reverse("admin-order-refund", kwargs={"order_id": unpaid_order.id}), {}, format="json",
        )
        self.assertEqual(resp.status_code, 404)


# ---------------------------------------------------------------------------
# Admin payment list/detail
# ---------------------------------------------------------------------------

class AdminPaymentViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make_admin_user(email="admin2@example.com")
        self.buyer = User.objects.create_user(email="buyer5@example.com", password="pass12345")
        self.order = make_order(user=self.buyer, total_amount="300.00")
        self.txn = PaymentTransaction.objects.create(
            order=self.order,
            razorpay_order_id="order_LIST1",
            amount=Decimal("300.00"),
            amount_paise=30000,
            currency="INR",
            status=PaymentTransactionStatus.CREATED,
        )
        self.client.force_authenticate(user=self.admin)

    def test_admin_can_list_payments(self):
        resp = self.client.get(reverse("admin-payment-list"))
        self.assertEqual(resp.status_code, 200)

    def test_admin_can_retrieve_payment_detail(self):
        resp = self.client.get(reverse("admin-payment-detail", kwargs={"id": self.txn.id}))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["razorpay_order_id"], "order_LIST1")

    def test_non_admin_cannot_list_payments(self):
        self.client.force_authenticate(user=self.buyer)
        resp = self.client.get(reverse("admin-payment-list"))
        self.assertEqual(resp.status_code, 403)
