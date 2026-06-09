"""In-app notification creation."""

from __future__ import annotations

import logging
from typing import Optional

from .models import Notification

logger = logging.getLogger("apps.notifications")


class NotificationService:
    """Creates in-app notifications. Email delivery is handled by the caller."""

    @staticmethod
    def notify(
        *,
        recipient,
        notification_type: str,
        title: str,
        message: str = "",
        actor=None,
        entity_type: str = "",
        entity_id: Optional[str] = None,
    ) -> Notification:
        notification = Notification.objects.create(
            recipient=recipient,
            actor=actor,
            notification_type=notification_type,
            title=title,
            message=message,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        logger.info("Notification %s created for %s", notification_type, recipient.pk)
        return notification
