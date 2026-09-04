"""
shipping/exceptions.py

Shipping-domain exceptions. These subclass DRF's APIException so they
flow straight through the project's existing global exception handler
(catalog.exceptions.custom_exception_handler) and come out already
wrapped in the standard {"status": "error", ...} envelope — exactly the
same pattern used by orders/exceptions.py and payments/exceptions.py.
"""

from rest_framework import status
from rest_framework.exceptions import APIException


class ShipmentNotFound(APIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "Shipment not found."
    default_code = "shipment_not_found"


class DuplicateShipment(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "A shipment already exists for this order."
    default_code = "duplicate_shipment"


class OrderNotPaid(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This order has not been paid for yet."
    default_code = "order_not_paid"


class OrderNotShippable(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This order is not in a shippable state."
    default_code = "order_not_shippable"


class MissingShippingAddress(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "This order has no shipping address on file."
    default_code = "missing_shipping_address"


class InvalidServiceabilityRequest(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "A valid delivery postal code is required."
    default_code = "invalid_serviceability_request"


class ShiprocketAuthenticationFailed(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Could not authenticate with Shiprocket."
    default_code = "shiprocket_authentication_failed"


class ShiprocketAPIError(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Shiprocket API request failed."
    default_code = "shiprocket_api_error"


class AWBAssignmentFailed(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Failed to assign an AWB code for this shipment."
    default_code = "awb_assignment_failed"


class AWBAlreadyAssigned(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "An AWB code has already been assigned to this shipment."
    default_code = "awb_already_assigned"


class LabelGenerationFailed(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Failed to generate the shipping label."
    default_code = "label_generation_failed"


class ManifestGenerationFailed(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Failed to generate the manifest."
    default_code = "manifest_generation_failed"


class ManifestRequiresAWB(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "An AWB code must be assigned before generating a manifest."
    default_code = "manifest_requires_awb"


class TrackingFailed(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Failed to fetch tracking information."
    default_code = "tracking_failed"


class TrackingNotAvailable(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Tracking is not available until this shipment has an AWB code."
    default_code = "tracking_not_available"


class ShipmentNotCancellable(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This shipment can no longer be cancelled."
    default_code = "shipment_not_cancellable"


class CancellationFailed(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Failed to cancel the shipment with Shiprocket."
    default_code = "cancellation_failed"


class InvalidWebhookPayload(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Webhook payload could not be parsed."
    default_code = "invalid_webhook_payload"


class InvalidWebhookSignature(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Webhook verification token is missing or invalid."
    default_code = "invalid_webhook_signature"
