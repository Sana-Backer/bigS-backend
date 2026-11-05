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
    from django.core.exceptions import ValidationError as DjangoValidationError

    if isinstance(exc, DjangoValidationError):
        if hasattr(exc, "message_dict"):
            errors = exc.message_dict
        elif hasattr(exc, "messages"):
            errors = {"detail": exc.messages}
        else:
            errors = {"detail": str(exc)}
        return Response(
            {
                "status": "error",
                "message": "Validation failed.",
                "errors": errors,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

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
            message = "Resource not found."
            if isinstance(response.data, dict) and "detail" in response.data:
                message = str(response.data["detail"])
            return Response(
                {
                    "status": "error",
                    "message": message,
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
    import traceback
    from django.conf import settings
    trace = traceback.format_exc()
    traceback.print_exc()
    try:
        with open(settings.BASE_DIR / "server_exceptions.log", "a", encoding="utf-8") as f:
            f.write(f"\n--- EXCEPTION: {exc} ---\n{trace}\n")
    except Exception:
        pass

    return Response(
        {
            "status": "error",
            "message": "An unexpected server error occurred.",
            "detail": str(exc) if getattr(settings, "DEBUG", False) else None,
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
