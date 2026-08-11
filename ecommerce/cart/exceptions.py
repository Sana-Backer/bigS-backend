"""
cart/exceptions.py

Cart-domain exceptions. These subclass DRF's APIException so they flow
straight through the project's existing global exception handler
(catalog.exceptions.custom_exception_handler) and come out already
wrapped in the standard {"status": "error", ...} envelope — no
per-view try/except needed.
"""

from rest_framework import status
from rest_framework.exceptions import APIException


class GuestTokenRequired(APIException):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = "Authentication or a valid X-Guest-Token header is required."
    default_code = "guest_token_required"


class GuestSessionInvalid(APIException):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = "Guest session is invalid or has expired."
    default_code = "guest_session_invalid"


class ProductUnavailable(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "This product is not available."
    default_code = "product_unavailable"


class VariantUnavailable(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "This product variant is not available."
    default_code = "variant_unavailable"


class InsufficientStock(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Requested quantity exceeds available stock."
    default_code = "insufficient_stock"


class CartEmpty(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Your cart is empty."
    default_code = "cart_empty"
