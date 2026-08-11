"""
common/responses.py

Shared response envelope helpers.

NOTE ON RESPONSE FORMAT
------------------------
The project already has a global DRF exception handler
(catalog.exceptions.custom_exception_handler, wired via
settings.REST_FRAMEWORK["EXCEPTION_HANDLER"]) and matching response
helpers in users/views.py and catalog/views.py. Both use the envelope:

    { "status": "success" | "error", "message": "...", "data": {...} }

instead of {"success": true/false, ...}. To keep every endpoint in the
project — old and new — returning a consistent shape, the cart, coupons,
and wishlist apps reuse this exact convention rather than introducing a
second, conflicting envelope. Swapping the global EXCEPTION_HANDLER to
match a `{"success": true/false}` shape would change the error format of
every already-shipped users/catalog endpoint, which the brief says not
to touch.

These helpers are just thin wrappers so cart/coupons/wishlist views don't
duplicate the same dict-building code that already exists (in slightly
different copies) in users/views.py and catalog/views.py.
"""

from rest_framework import status
from rest_framework.response import Response


def ok(data=None, message=None, status_code=status.HTTP_200_OK):
    payload = {"status": "success", "data": data if data is not None else {}}
    if message:
        payload["message"] = message
    return Response(payload, status=status_code)


def created(data=None, message="Created."):
    return ok(data, message, status.HTTP_201_CREATED)


def no_content(message="Deleted."):
    return Response({"status": "success", "message": message}, status=status.HTTP_204_NO_CONTENT)


def err(message, code=status.HTTP_400_BAD_REQUEST, errors=None):
    payload = {"status": "error", "message": message}
    if errors:
        payload["errors"] = errors
    return Response(payload, status=code)
