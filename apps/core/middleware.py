"""Custom middleware for SevaJobs."""

import logging
import time
from django.http import HttpRequest, HttpResponse

logger = logging.getLogger("apps.core")


class RequestLoggingMiddleware:
    """Logs method, path, status code, and duration for every request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        start = time.monotonic()
        response = self.get_response(request)
        duration_ms = (time.monotonic() - start) * 1000

        user = getattr(request, "user", None)
        user_repr = str(user.pk) if user and user.is_authenticated else "anon"

        logger.info(
            "%s %s %s %.1fms user=%s",
            request.method,
            request.path,
            response.status_code,
            duration_ms,
            user_repr,
        )
        return response
