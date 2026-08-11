"""
catalog/exceptions.py

Custom DRF exception handler that wraps all error responses in the
standard envelope format:

    {
        "status": "error",
        "message": "...",
        "errors": { ... }   # present for validation errors
    }
"""

from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status


def custom_exception_handler(exc, context):
    # Call DRF's default handler first to get the standard response.
    response = exception_handler(exc, context)

    if response is not None:
        status_code = response.status_code

        # Validation errors (400)
        if status_code == status.HTTP_400_BAD_REQUEST:
            return Response(
                {
                    "status": "error",
                    "message": "Validation failed.",
                    "errors": response.data,
                },
                status=status_code,
            )

        # Not found (404)
        if status_code == status.HTTP_404_NOT_FOUND:
            return Response(
                {
                    "status": "error",
                    "message": "Resource not found.",
                },
                status=status_code,
            )

        # Authentication / permission errors
        if status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        ):
            return Response(
                {
                    "status": "error",
                    "message": response.data.get("detail", "Permission denied."),
                },
                status=status_code,
            )

        # Generic fallback (e.g. 409 Conflict raised by cart/coupons/wishlist).
        # Prefer the APIException's `detail` message over stringifying the
        # whole response payload.
        if isinstance(response.data, dict) and "detail" in response.data:
            message = str(response.data["detail"])
        else:
            message = str(response.data)
        return Response(
            {
                "status": "error",
                "message": message,
            },
            status=status_code,
        )

    # Unhandled exceptions → 500
    return Response(
        {
            "status": "error",
            "message": "An unexpected server error occurred.",
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
