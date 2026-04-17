"""Standardized DRF exception handler.

Every error response the API returns goes through here so clients can rely on
a single shape:

    {"error": {"code": "<slug>", "message": "<human readable>", "details": ...}}

`details` carries the original DRF validation error structure for form-like
errors; it is absent on server errors to avoid leaking internals.
"""
import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


_DEFAULT_CODE_BY_STATUS = {
    status.HTTP_400_BAD_REQUEST: "bad_request",
    status.HTTP_401_UNAUTHORIZED: "not_authenticated",
    status.HTTP_403_FORBIDDEN: "permission_denied",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "unsupported_media_type",
    status.HTTP_429_TOO_MANY_REQUESTS: "throttled",
    status.HTTP_500_INTERNAL_SERVER_ERROR: "server_error",
}


def _resolve_code(exc, status_code):
    default_code = getattr(exc, "default_code", None)
    if default_code and default_code != "error":
        return default_code
    return _DEFAULT_CODE_BY_STATUS.get(status_code, "error")


def custom_exception_handler(exc, context):
    # Map a couple of Django-native exceptions DRF doesn't translate on its own.
    if isinstance(exc, Http404):
        exc = APIException(detail="Not found.")
        exc.status_code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, DjangoPermissionDenied):
        exc = APIException(detail="Permission denied.")
        exc.status_code = status.HTTP_403_FORBIDDEN

    response = drf_exception_handler(exc, context)

    if response is None:
        # Anything we didn't translate is an unhandled server error.
        logger.exception("Unhandled exception in %s", context.get("view"), exc_info=exc)
        return Response(
            {"error": {"code": "server_error", "message": "Internal server error."}},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    status_code = response.status_code
    original = response.data
    code = _resolve_code(exc, status_code)

    if isinstance(original, dict) and "detail" in original and len(original) == 1:
        payload = {"code": code, "message": str(original["detail"])}
    elif isinstance(original, (list, dict)):
        payload = {
            "code": code,
            "message": "Request validation failed."
            if status_code == status.HTTP_400_BAD_REQUEST
            else "Request could not be processed.",
            "details": original,
        }
    else:
        payload = {"code": code, "message": str(original)}

    response.data = {"error": payload}
    return response
