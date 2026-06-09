"""Cross-cutting services: centralised audit logging."""

from __future__ import annotations

import logging
from typing import Optional

from .models import ActivityLog

logger = logging.getLogger("apps.core")


class AuditService:
    """Writes immutable audit-trail rows to :class:`core.ActivityLog`."""

    @staticmethod
    def log(
        *,
        user=None,
        action: str = ActivityLog.Action.UPDATE,
        entity_type: str,
        entity_id: Optional[str] = None,
        description: str = "",
        metadata: Optional[dict] = None,
        ip: Optional[str] = None,
        user_agent: str = "",
    ) -> ActivityLog:
        entry = ActivityLog.objects.create(
            user=user,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            description=description,
            metadata=metadata or {},
            ip_address=ip,
            user_agent=user_agent,
        )
        logger.info("AUDIT %s %s by %s", action, entity_type, getattr(user, "pk", "system"))
        return entry
