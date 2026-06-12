"""
Recruiter contact visibility — business logic.

Drives the "visible for N days after approval, then hidden" rule and
admin-side overrides. Every change is audit-logged.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from django.db import transaction
from django.utils import timezone

from apps.core.models import ActivityLog
from apps.core.services import AuditService

from .models import ContactVisibilityConfig, Job, JobContactVisibility

logger = logging.getLogger("apps.jobs")


class ContactVisibilityService:
    """Create, override, and query per-job contact visibility."""

    # ----- creation (called from approval flow) ---------------------------
    @transaction.atomic
    def initialise_for(self, job: Job) -> JobContactVisibility:
        """Create or reset visibility when a job is first approved & published."""
        config = ContactVisibilityConfig.get_solo()
        expires_at = timezone.now() + timedelta(days=config.default_visibility_days)
        vis, _created = JobContactVisibility.objects.update_or_create(
            job=job,
            defaults={
                "state": JobContactVisibility.State.AUTO,
                "expires_at": expires_at,
                "overridden_by": None,
            },
        )
        AuditService.log(
            action=ActivityLog.Action.CREATE,
            entity_type="JobContactVisibility", entity_id=vis.id,
            description=f"Visibility initialised for job '{job.title}' (expires {expires_at:%Y-%m-%d %H:%M}).",
            metadata={"job_id": str(job.id), "expires_at": expires_at.isoformat(),
                      "default_visibility_days": config.default_visibility_days},
        )
        return vis

    # ----- admin overrides --------------------------------------------------
    @transaction.atomic
    def force_show(self, job: Job, admin_user, reason: str = "", ip: str | None = None) -> JobContactVisibility:
        return self._set_override(
            job, admin_user, JobContactVisibility.State.SHOW, reason, ip, event="force_show"
        )

    @transaction.atomic
    def force_hide(self, job: Job, admin_user, reason: str = "", ip: str | None = None) -> JobContactVisibility:
        return self._set_override(
            job, admin_user, JobContactVisibility.State.HIDE, reason, ip, event="force_hide"
        )

    @transaction.atomic
    def reset_to_auto(self, job: Job, admin_user, ip: str | None = None) -> JobContactVisibility:
        """Clear an override, restoring the default time-bounded visibility."""
        config = ContactVisibilityConfig.get_solo()
        vis = self._get_or_create(job, config)
        vis.state = JobContactVisibility.State.AUTO
        vis.expires_at = max(vis.expires_at, timezone.now() + timedelta(days=config.default_visibility_days))
        vis.overridden_by = admin_user
        vis.save()
        AuditService.log(
            user=admin_user, action=ActivityLog.Action.UPDATE,
            entity_type="JobContactVisibility", entity_id=vis.id, ip=ip,
            description=f"Visibility reset to AUTO for job '{job.title}'.",
            metadata={"event": "reset_to_auto", "job_id": str(job.id)},
        )
        return vis

    # ----- global config ----------------------------------------------------
    @transaction.atomic
    def configure_global(
        self,
        admin_user,
        *,
        default_visibility_days: Optional[int] = None,
        is_globally_disabled: Optional[bool] = None,
        ip: str | None = None,
    ) -> ContactVisibilityConfig:
        config = ContactVisibilityConfig.get_solo()
        changes: dict = {}
        if default_visibility_days is not None and default_visibility_days != config.default_visibility_days:
            changes["default_visibility_days"] = {
                "from": config.default_visibility_days, "to": default_visibility_days,
            }
            config.default_visibility_days = default_visibility_days
        if is_globally_disabled is not None and is_globally_disabled != config.is_globally_disabled:
            changes["is_globally_disabled"] = {
                "from": config.is_globally_disabled, "to": is_globally_disabled,
            }
            config.is_globally_disabled = is_globally_disabled

        if changes:
            config.updated_by = admin_user
            config.save()
            AuditService.log(
                user=admin_user, action=ActivityLog.Action.UPDATE,
                entity_type="ContactVisibilityConfig", entity_id=config.id, ip=ip,
                description="Global contact-visibility config updated.",
                metadata={"event": "configure_global", "changes": changes},
            )
        return config

    # ----- scheduled-task workhorse ---------------------------------------
    @transaction.atomic
    def expire_due(self) -> int:
        """
        Flip every AUTO row whose ``expires_at`` has passed to HIDDEN.

        Returns the number of rows transitioned. Called by the Celery beat task
        :func:`apps.jobs.tasks.hide_expired_contacts` every few minutes.
        """
        now = timezone.now()
        due_qs = JobContactVisibility.objects.select_for_update().filter(
            state=JobContactVisibility.State.AUTO, expires_at__lte=now,
        )
        ids = list(due_qs.values_list("id", "job_id"))
        if not ids:
            return 0
        due_qs.update(state=JobContactVisibility.State.HIDDEN)
        for vis_id, job_id in ids:
            AuditService.log(
                action=ActivityLog.Action.STATUS_CHANGE,
                entity_type="JobContactVisibility", entity_id=vis_id,
                description="Contact visibility expired automatically.",
                metadata={"event": "auto_expire", "job_id": str(job_id)},
            )
        logger.info("Expired contact visibility for %d job(s).", len(ids))
        return len(ids)

    # ----- read paths -------------------------------------------------------
    @staticmethod
    def is_visible_for(job: Job, viewer=None) -> bool:
        """
        True if the recruiter's contact details should be exposed to ``viewer``.

        Admins / staff always see contacts. Anyone else gets the public rule:
        per-job visibility state + global kill-switch.
        """
        if viewer is not None and (viewer.is_authenticated and (viewer.is_staff or viewer.role == "admin")):
            return True
        if ContactVisibilityConfig.get_solo().is_globally_disabled:
            return False
        vis = getattr(job, "contact_visibility", None)
        return bool(vis and vis.is_publicly_visible)

    # ----- helpers ----------------------------------------------------------
    @staticmethod
    def _get_or_create(job: Job, config: ContactVisibilityConfig) -> JobContactVisibility:
        vis, _ = JobContactVisibility.objects.get_or_create(
            job=job,
            defaults={
                "state": JobContactVisibility.State.AUTO,
                "expires_at": timezone.now() + timedelta(days=config.default_visibility_days),
            },
        )
        return vis

    def _set_override(self, job, admin_user, new_state, reason, ip, event) -> JobContactVisibility:
        config = ContactVisibilityConfig.get_solo()
        vis = self._get_or_create(job, config)
        from_state = vis.state
        vis.state = new_state
        vis.overridden_by = admin_user
        vis.save(update_fields=["state", "overridden_by", "last_changed_at"])
        AuditService.log(
            user=admin_user, action=ActivityLog.Action.STATUS_CHANGE,
            entity_type="JobContactVisibility", entity_id=vis.id, ip=ip,
            description=f"Visibility override on '{job.title}': {from_state} → {new_state}. {reason}".strip(),
            metadata={"event": event, "from": from_state, "to": new_state, "reason": reason,
                      "job_id": str(job.id)},
        )
        return vis
