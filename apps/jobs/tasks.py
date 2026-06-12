"""Celery tasks for the jobs app."""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger("apps.jobs")


@shared_task(name="jobs.hide_expired_contacts")
def hide_expired_contacts() -> int:
    """
    Periodic task: flip every AUTO `JobContactVisibility` whose `expires_at`
    has passed to HIDDEN. Returns the number of jobs updated.

    Scheduled by Celery beat (see ``CELERY_BEAT_SCHEDULE`` in settings).
    """
    from .visibility_services import ContactVisibilityService

    count = ContactVisibilityService().expire_due()
    if count:
        logger.info("hide_expired_contacts: hid %d job(s)", count)
    return count


@shared_task(name="jobs.expire_due_jobs")
def expire_due_jobs() -> int:
    """Periodic task: flip active jobs past their deadline to EXPIRED."""
    from .services import JobService

    return JobService().expire_due_jobs()
