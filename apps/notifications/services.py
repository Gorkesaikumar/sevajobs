"""In-app notification creation + real-time broadcast over Channels."""

from __future__ import annotations

import logging
from typing import Optional

from .models import Notification

logger = logging.getLogger("apps.notifications")


def _serialize(notification: Notification) -> dict:
    """Plain JSON-able payload for WS broadcast. Mirrors REST shape."""
    return {
        "id": str(notification.id),
        "title": notification.title,
        "message": notification.message,
        "notification_type": notification.notification_type,
        "entity_type": notification.entity_type,
        "entity_id": str(notification.entity_id) if notification.entity_id else None,
        "is_read": notification.is_read,
        "metadata": notification.metadata or {},
        "created_at": notification.created_at.isoformat(),
    }


def _broadcast(notification: Notification) -> None:
    """Push the notification to the recipient's per-user channel group.

    Safe to call even when Channels / Redis is unavailable — silently swallows
    transport failures rather than breaking the originating request.
    """
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        layer = get_channel_layer()
        if layer is None:
            return
        from .consumers import user_group_name
        async_to_sync(layer.group_send)(
            user_group_name(notification.recipient_id),
            {"type": "notification.new", "notification": _serialize(notification)},
        )
    except Exception:  # pragma: no cover — never let WS issues break a DB write
        logger.exception("Failed to broadcast notification %s", notification.pk)


class NotificationService:
    """Creates in-app notifications and broadcasts them over WebSocket."""

    @staticmethod
    def notify(
        *,
        recipient,
        notification_type: str,
        title: str,
        message: str = "",
        actor=None,
        entity_type: str = "",
        entity_id=None,
        metadata: Optional[dict] = None,
    ) -> Notification:
        notification = Notification.objects.create(
            recipient=recipient,
            actor=actor,
            notification_type=notification_type,
            title=title,
            message=message,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata=metadata or {},
        )
        logger.info("Notification %s created for %s", notification_type, recipient.pk)
        _broadcast(notification)
        return notification
