"""Channels consumer that pushes Notification rows to the authenticated user."""

from __future__ import annotations

import json
import logging
from typing import Any

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .models import Notification

logger = logging.getLogger("apps.notifications")


def user_group_name(user_id) -> str:
    return f"notifications_{user_id}"


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    """One WebSocket per authenticated user. Group membership is `notifications_<id>`.

    Inbound messages from the client:
      * `{"action": "mark_read", "id": "<uuid>"}`         — mark single notification read
      * `{"action": "mark_all_read"}`                     — bulk mark read
      * `{"action": "ping"}`                              — keepalive

    Outbound messages to the client:
      * `{"type": "notification.new", "notification": {…}}` — emitted by
        NotificationService.notify when a row is created.
      * `{"type": "notification.unread_count", "count": N}` — emitted whenever
        the unread count changes (after mark-read, etc.).
    """

    async def connect(self) -> None:
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close(code=4401)
            return
        self.group = user_group_name(user.id)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        # Send initial unread count so the client can render the badge.
        count = await self._unread_count(user)
        await self.send_json({"type": "notification.unread_count", "count": count})

    async def disconnect(self, code: int) -> None:
        group = getattr(self, "group", None)
        if group:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content: dict, **kwargs) -> None:
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            return
        action = (content or {}).get("action")
        if action == "mark_read":
            nid = content.get("id")
            if nid:
                await self._mark_read(user, nid)
                count = await self._unread_count(user)
                await self.send_json({"type": "notification.unread_count", "count": count})
        elif action == "mark_all_read":
            await self._mark_all_read(user)
            await self.send_json({"type": "notification.unread_count", "count": 0})
        elif action == "ping":
            await self.send_json({"type": "pong"})

    # ----- group handlers (called by channel_layer.group_send) -------------
    async def notification_new(self, event: dict) -> None:
        """Broadcast handler — payload pushed by NotificationService."""
        await self.send_json({"type": "notification.new", "notification": event["notification"]})
        # Also nudge the badge.
        user = self.scope.get("user")
        if user and user.is_authenticated:
            count = await self._unread_count(user)
            await self.send_json({"type": "notification.unread_count", "count": count})

    async def notification_unread_count(self, event: dict) -> None:
        await self.send_json({"type": "notification.unread_count", "count": event["count"]})

    # ----- DB helpers ------------------------------------------------------
    @database_sync_to_async
    def _unread_count(self, user) -> int:
        return Notification.objects.filter(recipient=user, is_read=False).count()

    @database_sync_to_async
    def _mark_read(self, user, nid) -> None:
        Notification.objects.filter(pk=nid, recipient=user, is_read=False).update(is_read=True)

    @database_sync_to_async
    def _mark_all_read(self, user) -> None:
        from django.utils import timezone
        Notification.objects.filter(recipient=user, is_read=False).update(
            is_read=True, read_at=timezone.now()
        )
