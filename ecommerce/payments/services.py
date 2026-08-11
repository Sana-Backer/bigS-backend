"""
payments/services.py

All payment orchestration logic:
  - get_or_create_razorpay_order()  – POST /api/payments/razorpay/create/
  - verify_payment()                – POST /api/payments/razorpay/verify/
  - process_webhook_event()         – POST /api/payments/webhooks/razorpay/
  - process_refund()                – POST /api/payments/razorpay/refund/
                                       POST /api/admin/orders/<id>/refund/

Reuse, not reinvention
-----------------------
- Order status transitions: orders.services.change_payment_status() /
  change_order_status() are the ONLY way this module ever touches
  Order.status / Order.payment_status — the allowed-transition maps
  in orders/constants.py are never duplicated or bypassed here. Where
  a transition isn't applicable (e.g. already applied by a concurrent
  webhook), InvalidStatusTransition is caught and ignored — that is
  the expected shape of idempotent, order-agnostic delivery.
- Ownership scoping: orders.selectors.get_order_for_owner() (used at
  the view layer) and orders.exceptions.OrderNotFound are reused so a
  payments 404 carries exactly the same "don't leak whether this ID
  exists" guarantee the orders app already provides.
- Money: Decimal everywhere in this module; the razorpay_provider
  module is the only place paise conversion happens.
"""

import json
import secrets
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from orders.constants import OrderStatus, PaymentStatus
from orders.exceptions import InvalidStatusTransition
from orders.exceptions import OrderNotFound as OrderNotFoundForOwner
from orders.models import Order
from orders import services as orders_services

from .constants import (
    LIVE_TRANSACTION_STATUSES,
    RAZORPAY_RECEIPT_MAX_LENGTH,
    REFUNDABLE_TRANSACTION_STATUSES,
    PaymentTransactionStatus,
    WebhookEventType,
)
from .exceptions import (
    InvalidPaymentSignature,
    InvalidRefundAmount,
    InvalidWebhookPayload,
    InvalidWebhookSignature,
    OrderNotPayable,
    PaymentAmountMismatch,
    PaymentCurrencyMismatch,
    PaymentNotCaptured,
    PaymentNotRefundable,
    PaymentOrderMismatch,
    PaymentTransactionNotFound,
    RefundExceedsRefundable,
)
from .models import PaymentTransaction, PaymentWebhookEvent
from .providers import razorpay_provider

# Orders in these states may still accept a payment attempt.
PAYABLE_ORDER_STATUSES = {OrderStatus.PENDING, OrderStatus.CONFIRMED}
PAYABLE_PAYMENT_STATUSES = {PaymentStatus.PENDING, PaymentStatus.FAILED}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_order_payable(order: Order) -> bool:
    return order.status in PAYABLE_ORDER_STATUSES and order.payment_status in PAYABLE_PAYMENT_STATUSES


def _assert_owns_order(order: Order, user=None, guest_session=None):
    """
    Same 404-not-leak-existence guarantee as orders.selectors.get_order_for_owner:
    a payment-verification request for someone else's order must look
    identical to one for a nonexistent order.
    """
    if user is not None:
        if order.user_id != getattr(user, "id", None):
            raise OrderNotFoundForOwner()
    else:
        if order.guest_session_id != getattr(guest_session, "id", None):
            raise OrderNotFoundForOwner()


def _generate_receipt(order: Order) -> str:
    suffix = secrets.token_hex(3)
    receipt = f"{order.order_number}-{suffix}"
    return receipt[:RAZORPAY_RECEIPT_MAX_LENGTH]


def _mark_order_paid(order: Order, changed_by=None):
    """
    Idempotently moves an Order to payment_status=PAID and, if it's
    still PENDING, to status=CONFIRMED. Safe to call from both the
    /verify/ endpoint and the webhook handler for the same order —
    whichever arrives first wins, the other is a no-op.
    """
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.payment_status != PaymentStatus.PAID:
        try:
            orders_services.change_payment_status(
                order, PaymentStatus.PAID, changed_by=changed_by,
                reason="Razorpay payment captured.",
            )
        except InvalidStatusTransition:
            pass
    order.refresh_from_db()
    if order.status == OrderStatus.PENDING:
        try:
            orders_services.change_order_status(
                order, OrderStatus.CONFIRMED, changed_by=changed_by,
                reason="Payment confirmed via Razorpay.",
            )
        except InvalidStatusTransition:
            pass


def _mark_order_payment_failed(order: Order, reason: str, changed_by=None):
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.payment_status in (PaymentStatus.PENDING, PaymentStatus.AUTHORIZED):
        try:
            orders_services.change_payment_status(
                order, PaymentStatus.FAILED, changed_by=changed_by, reason=reason,
            )
        except InvalidStatusTransition:
            pass


def _apply_refund(txn: PaymentTransaction, refund_id: str, refund_amount_paise: int) -> bool:
    """
    Idempotently folds one Razorpay refund into a transaction's
    refunded_amount. Returns False (no-op) if this refund_id has
    already been applied — the mechanism that makes both the manual
    refund call and the refund.processed/refund.failed webhooks safe
    to both fire for the same underlying refund.
    """
    processed_ids = list(txn.processed_refund_ids or [])
    if refund_id in processed_ids:
        return False

    processed_ids.append(refund_id)
    refund_amount = razorpay_provider.to_rupees(refund_amount_paise)

    txn.processed_refund_ids = processed_ids
    txn.refunded_amount = (txn.refunded_amount + refund_amount).quantize(Decimal("0.01"))
    txn.status = (
        PaymentTransactionStatus.REFUNDED
        if txn.refunded_amount >= txn.amount
        else PaymentTransactionStatus.PARTIALLY_REFUNDED
    )
    txn.save(update_fields=["processed_refund_ids", "refunded_amount", "status", "updated_at"])

    order = Order.objects.select_for_update().get(pk=txn.order_id)
    target_payment_status = (
        PaymentStatus.REFUNDED
        if txn.status == PaymentTransactionStatus.REFUNDED
        else PaymentStatus.PARTIALLY_REFUNDED
    )
    if order.payment_status != target_payment_status:
        try:
            orders_services.change_payment_status(
                order, target_payment_status, changed_by=None,
                reason=f"Razorpay refund {refund_id} processed.",
            )
        except InvalidStatusTransition:
            pass
    return True


# ---------------------------------------------------------------------------
# POST /api/payments/razorpay/create/
# ---------------------------------------------------------------------------

@transaction.atomic
def get_or_create_razorpay_order(*, order: Order, user=None, guest_session=None):
    """
    Returns (transaction, created). Idempotent: if a CREATED/AUTHORIZED
    transaction already exists for this order, it is reused instead of
    creating a second Razorpay order (protects against double-clicking
    "Pay Now").
    """
    order = Order.objects.select_for_update().get(pk=order.pk)

    if not is_order_payable(order):
        raise OrderNotPayable()

    existing = (
        PaymentTransaction.objects
        .filter(order=order, status__in=LIVE_TRANSACTION_STATUSES)
        .order_by("-created_at")
        .first()
    )
    if existing is not None:
        return existing, False

    amount_paise = razorpay_provider.to_paise(order.total_amount)
    receipt = _generate_receipt(order)

    rp_order = razorpay_provider.create_order(
        amount_paise=amount_paise,
        currency=order.currency,
        receipt=receipt,
        notes={"order_id": str(order.id), "order_number": order.order_number},
    )

    txn = PaymentTransaction.objects.create(
        order=order,
        razorpay_order_id=rp_order["id"],
        amount=order.total_amount,
        amount_paise=amount_paise,
        currency=order.currency,
        receipt=receipt,
        status=PaymentTransactionStatus.CREATED,
        initiated_by=user,
    )
    return txn, True


# ---------------------------------------------------------------------------
# POST /api/payments/razorpay/verify/
# ---------------------------------------------------------------------------

@transaction.atomic
def verify_payment(*, razorpay_order_id: str, razorpay_payment_id: str, razorpay_signature: str,
                    user=None, guest_session=None) -> PaymentTransaction:
    """
    Never trusts the frontend's own success message: recomputes the
    signature server-side, then re-fetches the payment from Razorpay
    directly to confirm amount/currency/status before marking anything
    paid. Idempotent — calling this twice for an already-verified
    payment simply returns the same PAID transaction without hitting
    Razorpay again.
    """
    try:
        txn = (
            PaymentTransaction.objects
            .select_for_update()
            .select_related("order")
            .get(razorpay_order_id=razorpay_order_id)
        )
    except PaymentTransaction.DoesNotExist:
        raise PaymentTransactionNotFound("No payment transaction found for this Razorpay order.")

    _assert_owns_order(txn.order, user=user, guest_session=guest_session)

    # Idempotency: already verified and paid — nothing left to do.
    if txn.status in (PaymentTransactionStatus.PAID, PaymentTransactionStatus.PARTIALLY_REFUNDED,
                       PaymentTransactionStatus.REFUNDED):
        return txn

    if not razorpay_provider.verify_payment_signature(razorpay_order_id, razorpay_payment_id, razorpay_signature):
        txn.status = PaymentTransactionStatus.FAILED
        txn.razorpay_payment_id = razorpay_payment_id
        txn.razorpay_signature = razorpay_signature
        txn.failure_reason = "Signature verification failed."
        txn.save(update_fields=["status", "razorpay_payment_id", "razorpay_signature", "failure_reason", "updated_at"])
        _mark_order_payment_failed(txn.order, reason="Razorpay signature verification failed.")
        raise InvalidPaymentSignature()

    # Never trust the frontend beyond the signature: re-fetch the payment
    # itself from Razorpay to confirm what actually happened.
    payment = razorpay_provider.fetch_payment(razorpay_payment_id)

    if payment.get("order_id") != razorpay_order_id:
        raise PaymentOrderMismatch()
    if int(payment.get("amount", -1)) != txn.amount_paise:
        raise PaymentAmountMismatch()
    if payment.get("currency") != txn.currency:
        raise PaymentCurrencyMismatch()

    payment_status = payment.get("status")
    if payment_status not in ("authorized", "captured"):
        txn.status = PaymentTransactionStatus.FAILED
        txn.razorpay_payment_id = razorpay_payment_id
        txn.razorpay_signature = razorpay_signature
        txn.failure_reason = f"Unexpected payment status from Razorpay: {payment_status}"
        txn.save(update_fields=["status", "razorpay_payment_id", "razorpay_signature", "failure_reason", "updated_at"])
        _mark_order_payment_failed(txn.order, reason=txn.failure_reason)
        raise PaymentNotCaptured()

    txn.razorpay_payment_id = razorpay_payment_id
    txn.razorpay_signature = razorpay_signature
    txn.verified_at = timezone.now()
    txn.status = (
        PaymentTransactionStatus.PAID if payment_status == "captured"
        else PaymentTransactionStatus.AUTHORIZED
    )
    txn.save(update_fields=["razorpay_payment_id", "razorpay_signature", "verified_at", "status", "updated_at"])

    if txn.status == PaymentTransactionStatus.PAID:
        _mark_order_paid(txn.order, changed_by=user)

    return txn


# ---------------------------------------------------------------------------
# POST /api/payments/webhooks/razorpay/
# ---------------------------------------------------------------------------

def _entity(payload: dict, key: str) -> dict:
    return (payload.get("payload") or {}).get(key, {}).get("entity", {}) or {}


def _get_live_txn_by_rp_order(razorpay_order_id):
    if not razorpay_order_id:
        return None
    return (
        PaymentTransaction.objects
        .select_for_update()
        .select_related("order")
        .filter(razorpay_order_id=razorpay_order_id)
        .first()
    )


def _handle_payment_authorized(event: PaymentWebhookEvent, entity: dict):
    txn = _get_live_txn_by_rp_order(entity.get("order_id"))
    if txn is None:
        return
    event.payment_transaction = txn
    if txn.status == PaymentTransactionStatus.CREATED:
        txn.razorpay_payment_id = entity.get("id", txn.razorpay_payment_id)
        txn.status = PaymentTransactionStatus.AUTHORIZED
        txn.save(update_fields=["razorpay_payment_id", "status", "updated_at"])


def _handle_payment_captured(event: PaymentWebhookEvent, entity: dict):
    txn = _get_live_txn_by_rp_order(entity.get("order_id"))
    if txn is None:
        return
    event.payment_transaction = txn

    if txn.status in (PaymentTransactionStatus.PAID, PaymentTransactionStatus.PARTIALLY_REFUNDED,
                      PaymentTransactionStatus.REFUNDED):
        return  # already reconciled, e.g. by the /verify/ endpoint — idempotent no-op

    if int(entity.get("amount", -1)) != txn.amount_paise or entity.get("currency") != txn.currency:
        txn.status = PaymentTransactionStatus.FAILED
        txn.failure_reason = "Webhook amount/currency mismatch with stored transaction."
        txn.save(update_fields=["status", "failure_reason", "updated_at"])
        return

    txn.razorpay_payment_id = entity.get("id", txn.razorpay_payment_id)
    txn.status = PaymentTransactionStatus.PAID
    txn.verified_at = timezone.now()
    txn.save(update_fields=["razorpay_payment_id", "status", "verified_at", "updated_at"])
    _mark_order_paid(txn.order, changed_by=None)


def _handle_payment_failed(event: PaymentWebhookEvent, entity: dict):
    txn = _get_live_txn_by_rp_order(entity.get("order_id"))
    if txn is None:
        return
    event.payment_transaction = txn

    if txn.status in (PaymentTransactionStatus.PAID, PaymentTransactionStatus.PARTIALLY_REFUNDED,
                      PaymentTransactionStatus.REFUNDED):
        return  # a stale failure event must never clobber a later success

    txn.status = PaymentTransactionStatus.FAILED
    txn.razorpay_payment_id = entity.get("id", txn.razorpay_payment_id)
    txn.failure_reason = (entity.get("error_description") or "Payment failed.")[:500]
    txn.save(update_fields=["status", "razorpay_payment_id", "failure_reason", "updated_at"])

    _mark_order_payment_failed(txn.order, reason=txn.failure_reason)


def _handle_order_paid(event: PaymentWebhookEvent, payload: dict):
    payment_entity = _entity(payload, "payment")
    if payment_entity:
        _handle_payment_captured(event, payment_entity)


def _handle_refund_processed(event: PaymentWebhookEvent, entity: dict):
    txn = (
        PaymentTransaction.objects
        .select_for_update()
        .select_related("order")
        .filter(razorpay_payment_id=entity.get("payment_id"))
        .first()
    )
    if txn is None or not entity.get("id"):
        return
    event.payment_transaction = txn
    _apply_refund(txn, entity["id"], int(entity.get("amount", 0)))


def _handle_refund_failed(event: PaymentWebhookEvent, entity: dict):
    txn = (
        PaymentTransaction.objects
        .filter(razorpay_payment_id=entity.get("payment_id"))
        .first()
    )
    if txn is not None:
        event.payment_transaction = txn
    # Refund failed on Razorpay's side: no money moved, nothing to apply.
    # The event row itself (with its payload) is the audit trail.


_WEBHOOK_HANDLERS = {
    WebhookEventType.PAYMENT_AUTHORIZED: lambda event, payload: _handle_payment_authorized(event, _entity(payload, "payment")),
    WebhookEventType.PAYMENT_CAPTURED: lambda event, payload: _handle_payment_captured(event, _entity(payload, "payment")),
    WebhookEventType.PAYMENT_FAILED: lambda event, payload: _handle_payment_failed(event, _entity(payload, "payment")),
    WebhookEventType.ORDER_PAID: lambda event, payload: _handle_order_paid(event, payload),
    WebhookEventType.REFUND_PROCESSED: lambda event, payload: _handle_refund_processed(event, _entity(payload, "refund")),
    WebhookEventType.REFUND_FAILED: lambda event, payload: _handle_refund_failed(event, _entity(payload, "refund")),
}


@transaction.atomic
def process_webhook_event(*, raw_body: bytes, signature: str, event_id: str) -> PaymentWebhookEvent:
    """
    Verifies the webhook signature, then records + dispatches the
    event. Duplicate deliveries (same X-Razorpay-Event-Id) are a
    guaranteed no-op: the unique constraint on event_id means the
    second delivery's get_or_create() finds the existing row and
    `created` is False, so the handler never runs twice.
    """
    if not razorpay_provider.verify_webhook_signature(raw_body, signature):
        raise InvalidWebhookSignature()

    try:
        body_str = raw_body.decode("utf-8") if isinstance(raw_body, bytes) else raw_body
        payload = json.loads(body_str)
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidWebhookPayload() from exc

    event_type = payload.get("event", "")

    # Idempotency: unique event_id constraint. If two deliveries race,
    # Django's get_or_create() catches the resulting IntegrityError and
    # re-fetches, so `created` is reliably False for the loser.
    event, created = PaymentWebhookEvent.objects.get_or_create(
        event_id=event_id,
        defaults={"event_type": event_type, "payload": payload},
    )
    if not created:
        return event

    handler = _WEBHOOK_HANDLERS.get(event_type)
    if handler is None:
        # Unhandled event type (e.g. one not in HANDLED_WEBHOOK_EVENTS) —
        # still recorded above for audit, just nothing further to do.
        event.is_processed = True
        event.processed_at = timezone.now()
        event.save(update_fields=["is_processed", "processed_at", "updated_at"])
        return event

    try:
        handler(event, payload)
        event.is_processed = True
        event.processed_at = timezone.now()
        event.save(update_fields=["is_processed", "processed_at", "payment_transaction", "updated_at"])
    except Exception as exc:
        event.processing_error = str(exc)[:500]
        event.save(update_fields=["processing_error", "updated_at"])
        raise
    return event


# ---------------------------------------------------------------------------
# POST /api/payments/razorpay/refund/
# POST /api/admin/orders/<uuid:order_id>/refund/
# ---------------------------------------------------------------------------

@transaction.atomic
def process_refund(*, payment_transaction: PaymentTransaction, amount=None, initiated_by=None,
                    reason: str = "") -> PaymentTransaction:
    """
    Full or partial refund against an already-captured payment.
    Validates the payment was successful and that the requested amount
    does not exceed what remains refundable, then calls Razorpay and
    folds the result into the transaction via the same _apply_refund()
    helper the refund.processed webhook uses — so a webhook confirming
    this exact refund later is a safe no-op, not a double-refund.
    """
    txn = (
        PaymentTransaction.objects
        .select_for_update()
        .select_related("order")
        .get(pk=payment_transaction.pk)
    )

    if txn.status not in REFUNDABLE_TRANSACTION_STATUSES:
        raise PaymentNotRefundable()

    refundable = txn.refundable_amount
    if refundable <= 0:
        raise PaymentNotRefundable("Nothing left to refund on this payment.")

    if amount is None:
        refund_amount = refundable
    else:
        refund_amount = Decimal(amount).quantize(Decimal("0.01"))
        if refund_amount <= 0:
            raise InvalidRefundAmount()
        if refund_amount > refundable:
            raise RefundExceedsRefundable(
                f"Refund amount exceeds the refundable amount of {refundable}."
            )

    refund_paise = razorpay_provider.to_paise(refund_amount)
    notes = {"order_id": str(txn.order_id)}
    if reason:
        notes["reason"] = reason[:250]

    rp_refund = razorpay_provider.create_refund(
        payment_id=txn.razorpay_payment_id,
        amount_paise=refund_paise,
        notes=notes,
    )

    _apply_refund(txn, rp_refund["id"], int(rp_refund.get("amount", refund_paise)))
    txn.refresh_from_db()
    return txn
