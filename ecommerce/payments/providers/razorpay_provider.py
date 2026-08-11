"""
payments/providers/razorpay_provider.py

Thin wrapper around the official `razorpay` Python SDK.

This is the ONLY module in the project allowed to import `razorpay`
or read RAZORPAY_KEY_SECRET / RAZORPAY_WEBHOOK_SECRET from settings.
Everything else (services.py, views.py) calls the functions below —
never the SDK or the secret settings directly. This keeps the secret
key out of logs, serializers, and responses by construction: there is
exactly one place it is ever touched.

RAZORPAY_KEY_ID is the only Razorpay identifier ever handed back to a
client (it is public by design — required by Razorpay's Checkout.js).
"""

from decimal import ROUND_HALF_UP, Decimal

import razorpay
from django.conf import settings

from ..exceptions import RazorpayAPIError

_client = None


def get_client():
    """Lazily-constructed, module-cached Razorpay client."""
    global _client
    if _client is None:
        _client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    return _client


def to_paise(amount) -> int:
    """Converts a Decimal/str/float INR amount into an integer paise value."""
    rupees = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    return int((rupees * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_rupees(paise) -> Decimal:
    return (Decimal(paise) / Decimal(100)).quantize(Decimal("0.01"))


def create_order(*, amount_paise: int, currency: str = "INR", receipt: str = "", notes: dict | None = None) -> dict:
    """Creates a Razorpay Order. Raises RazorpayAPIError on any SDK/API failure."""
    client = get_client()
    try:
        return client.order.create({
            "amount": amount_paise,
            "currency": currency,
            "receipt": receipt,
            "payment_capture": 1,
            "notes": notes or {},
        })
    except razorpay.errors.BadRequestError as exc:
        raise RazorpayAPIError(str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive: network/SDK errors
        raise RazorpayAPIError(str(exc)) from exc


def fetch_payment(payment_id: str) -> dict:
    """Fetches a payment's authoritative state directly from Razorpay."""
    client = get_client()
    try:
        return client.payment.fetch(payment_id)
    except razorpay.errors.BadRequestError as exc:
        raise RazorpayAPIError(str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise RazorpayAPIError(str(exc)) from exc


def verify_payment_signature(razorpay_order_id: str, razorpay_payment_id: str, razorpay_signature: str) -> bool:
    """
    Verifies the HMAC-SHA256 signature Razorpay returns to the frontend
    after checkout. This NEVER trusts the frontend's own "success"
    message — it recomputes the signature server-side using
    RAZORPAY_KEY_SECRET (never exposed to the client).
    """
    client = get_client()
    try:
        client.utility.verify_payment_signature({
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": razorpay_signature,
        })
        return True
    except razorpay.errors.SignatureVerificationError:
        return False


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    """
    Verifies X-Razorpay-Signature against the RAW webhook request body
    using RAZORPAY_WEBHOOK_SECRET. Must be given the exact raw bytes —
    never a re-serialized/re-parsed copy of the payload.
    """
    client = get_client()
    body_str = raw_body.decode("utf-8") if isinstance(raw_body, bytes) else raw_body
    try:
        client.utility.verify_webhook_signature(body_str, signature, settings.RAZORPAY_WEBHOOK_SECRET)
        return True
    except razorpay.errors.SignatureVerificationError:
        return False


def create_refund(*, payment_id: str, amount_paise: int, notes: dict | None = None) -> dict:
    """
    Creates a refund against a captured payment. Passing `amount_paise`
    less than the full captured amount creates a partial refund;
    passing the full captured amount creates a full refund. Raises
    RazorpayAPIError on any SDK/API failure.
    """
    client = get_client()
    try:
        return client.payment.refund(payment_id, {
            "amount": amount_paise,
            "notes": notes or {},
        })
    except razorpay.errors.BadRequestError as exc:
        raise RazorpayAPIError(str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise RazorpayAPIError(str(exc)) from exc
