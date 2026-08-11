from rest_framework import status
from rest_framework.exceptions import APIException


class OrderNotFound(APIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "Order not found."
    default_code = "order_not_found"


class InvalidStatusTransition(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This status transition is not allowed."
    default_code = "invalid_status_transition"


class OrderNotCancellable(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This order can no longer be cancelled."
    default_code = "order_not_cancellable"


class DuplicateOrderCreation(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "An order has already been created from this cart."
    default_code = "duplicate_order_creation"


class InvalidAddress(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "A valid billing and shipping address is required."
    default_code = "invalid_address"


class AddressNotFound(APIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "The selected address could not be found."
    default_code = "address_not_found"


class GuestEmailRequired(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "A guest email address is required to check out as a guest."
    default_code = "guest_email_required"
