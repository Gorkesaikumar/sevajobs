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


@shared_task(name="jobs.process_requirement_matching")
def process_requirement_matching_task(requirement_id: str) -> int:
    """
    Asynchronous Celery task for running CandidateMatchingService on an InstitutionRequirement.
    Safe execution with error handling & activity logging.
    """
    from .models import InstitutionRequirement
    from .matching_service import CandidateMatchingService
    from .requirement_services import RequirementWorkflowService

    try:
        req = InstitutionRequirement.objects.get(pk=requirement_id)
        matches = CandidateMatchingService.find_and_store_matches(req)
        match_count = len(matches)
        RequirementWorkflowService.update_matching_status(req, match_count=match_count)
        logger.info("Requirement %s matching finished: %d candidates found.", requirement_id, match_count)
        return match_count
    except Exception as exc:
        logger.exception("Requirement %s matching failed: %s", requirement_id, exc)
        return 0

