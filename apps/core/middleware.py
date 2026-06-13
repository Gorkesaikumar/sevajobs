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

class MaintenanceModeMiddleware:
    """
    Blocks all non-staff users from accessing the site if maintenance mode is active.
    Allows access to admin URLs regardless of the setting.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        from apps.core.models import PlatformSettings
        from django.shortcuts import render
        
        # Don't block requests to the Django admin or dashboard admin
        if request.path.startswith('/admin/') or request.path.startswith('/dashboard/admin/'):
            return self.get_response(request)

        settings = PlatformSettings.get_settings()
        
        if settings.maintenance_mode:
            # Check if user is authenticated and is staff/admin
            user = getattr(request, 'user', None)
            if user and user.is_authenticated and (user.is_staff or user.is_superuser or user.is_admin_role):
                return self.get_response(request)
                
            return render(request, "pages/maintenance.html", status=503)
            
        return self.get_response(request)
