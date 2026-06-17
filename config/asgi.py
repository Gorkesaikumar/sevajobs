"""ASGI config for SevaJobs.

HTTP traffic continues to be served by Django's default WSGI/ASGI handler.
WebSocket traffic (real-time notifications) is routed through Channels with
AuthMiddlewareStack so the consumer can identify the authenticated user from
the session cookie.
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

# IMPORTANT: get_asgi_application() must be called BEFORE importing anything
# that touches the ORM (consumers, routing modules that import models, etc.)
# — Channels' own documentation calls this out explicitly.
from django.core.asgi import get_asgi_application  # noqa: E402
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from apps.notifications.routing import websocket_urlpatterns  # noqa: E402


application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
    ),
})
