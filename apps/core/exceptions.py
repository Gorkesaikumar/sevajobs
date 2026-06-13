"""Centralised DRF exception handler."""

import logging
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger("apps.core")


def custom_exception_handler(exc: Exception, context: dict) -> Response | None:
    """
    Normalises all API error responses to:
    { "error": { "code": str, "message": str, "details": any } }
    """
    # Convert Django ValidationError to DRF equivalent
    if isinstance(exc, DjangoValidationError):
        exc = exceptions.ValidationError(detail=exc.message_dict if hasattr(exc, "message_dict") else exc.messages)

    response = exception_handler(exc, context)

    if response is not None:
        code = getattr(exc, "default_code", "error")
        message = _extract_message(response.data)
        details = response.data if not isinstance(response.data, str) else None

        response.data = {
            "error": {
                "code": code,
                "message": message,
                "details": details,
            }
        }

        logger.warning(
            "API error %s — %s — %s",
            response.status_code,
            code,
            message,
        )

    return response


def _extract_message(data: Any) -> str:
    if isinstance(data, str):
        return data
    if isinstance(data, list) and data:
        first = data[0]
        return str(first) if not isinstance(first, dict) else str(first)
    if isinstance(data, dict):
        for key in ("detail", "non_field_errors", "message"):
            if key in data:
                val = data[key]
                return str(val[0]) if isinstance(val, list) else str(val)
        return str(next(iter(data.values())))
    return "An error occurred."
