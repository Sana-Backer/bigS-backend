"""
dashboard/exceptions.py

This app is read-only (pure aggregation over orders/catalog/users/
payments — no models of its own), so the only failures it can ever
raise are bad query parameters. These subclass DRF's APIException so
they flow through the project's existing global exception handler
(catalog.exceptions.custom_exception_handler) and come out wrapped in
the standard {"status": "error", ...} envelope. In practice query
params are validated by serializers first, so these are a defensive
backstop rather than the primary validation path.
"""

from rest_framework import status
from rest_framework.exceptions import APIException


class InvalidPeriod(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Invalid period. Must be one of: daily, weekly, monthly, yearly."
    default_code = "invalid_period"


class InvalidDateRange(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Invalid date range."
    default_code = "invalid_date_range"

class BannerNotFound(APIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "Banner not found."
    default_code = "banner_not_found"
 
