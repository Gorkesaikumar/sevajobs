"""WebSocket URL patterns for in-app notifications."""

from django.urls import path
from .consumers import NotificationConsumer

websocket_urlpatterns = [
    path("ws/notifications/", NotificationConsumer.as_asgi()),
]
