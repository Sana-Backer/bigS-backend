"""
payments/exceptions.py

Payments-domain exceptions. These subclass DRF's APIException so they
flow straight through the project's existing global exception handler
(catalog.exceptions.custom_exception_handler) and come out already
wrapped in the standard {"status": "error", ...} envelope.
"""

from rest_framework import status
from rest_framework.exceptions import APIException


class PaymentTransactionNotFound(APIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "Payment transaction not found."
    default_code = "payment_transaction_not_found"


class OrderNotPayable(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This order is not currently payable."
    default_code = "order_not_payable"


class InvalidPaymentSignature(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Payment signature verification failed."
    default_code = "invalid_payment_signature"


class PaymentOrderMismatch(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "The payment does not belong to the specified Razorpay order."
    default_code = "payment_order_mismatch"


class PaymentAmountMismatch(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "The paid amount does not match the order amount."
    default_code = "payment_amount_mismatch"


class PaymentCurrencyMismatch(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "The payment currency does not match the order currency."
    default_code = "payment_currency_mismatch"


class PaymentNotCaptured(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "The payment has not been authorized or captured by Razorpay."
    default_code = "payment_not_captured"


class PaymentNotRefundable(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This payment is not eligible for a refund."
    default_code = "payment_not_refundable"


class InvalidRefundAmount(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Refund amount must be greater than zero."
    default_code = "invalid_refund_amount"


class RefundExceedsRefundable(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Refund amount exceeds the refundable amount for this payment."
    default_code = "refund_exceeds_refundable"


class InvalidWebhookSignature(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Webhook signature verification failed."
    default_code = "invalid_webhook_signature"


class WebhookSignatureMissing(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Missing X-Razorpay-Signature header."
    default_code = "webhook_signature_missing"


class WebhookEventIdMissing(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Missing X-Razorpay-Event-Id header."
    default_code = "webhook_event_id_missing"


class InvalidWebhookPayload(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Webhook payload could not be parsed."
    default_code = "invalid_webhook_payload"


class RazorpayAPIError(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Razorpay API request failed."
    default_code = "razorpay_api_error"
