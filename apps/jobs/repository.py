from __future__ import annotations
from typing import Optional
from django.db.models import QuerySet, F, Q
from django.utils import timezone
from .models import Job


class JobRepository:
    """Encapsulates all database queries for Job objects."""

    @staticmethod
    def _base_qs() -> QuerySet[Job]:
        return (
            Job.objects
            .select_related("recruiter", "company", "category", "minimum_qualification")
            .prefetch_related("skills_required", "preferred_qualifications")
        )

    @staticmethod
    def get_active() -> QuerySet[Job]:
        """Public board: active, admin-approved, and not past deadline."""
        today = timezone.now().date()
        return (
            JobRepository._base_qs()
            .filter(status=Job.Status.ACTIVE, approval_status=Job.ApprovalStatus.APPROVED)
            .filter(Q(deadline__isnull=True) | Q(deadline__gte=today))
        )

    @staticmethod
    def get_featured() -> QuerySet[Job]:
        now = timezone.now()
        return (
            JobRepository.get_active()
            .filter(is_featured=True)
            .filter(Q(featured_until__isnull=True) | Q(featured_until__gte=now))
            .order_by("-published_at", "-created_at")
        )

    @staticmethod
    def get_pending_approval() -> QuerySet[Job]:
        return JobRepository._base_qs().filter(
            approval_status=Job.ApprovalStatus.PENDING
        ).order_by("created_at")

    @staticmethod
    def get_by_id(job_id: str) -> Optional[Job]:
        return JobRepository._base_qs().filter(id=job_id).first()

    @staticmethod
    def get_by_recruiter(recruiter_id: str) -> QuerySet[Job]:
        return JobRepository._base_qs().filter(recruiter_id=recruiter_id)

    @staticmethod
    def increment_views(job_id: str) -> None:
        Job.objects.filter(id=job_id).update(views_count=F("views_count") + 1)

    @staticmethod
    def expire_due_jobs() -> int:
        """Flip active jobs whose deadline has passed to EXPIRED. Returns count."""
        today = timezone.now().date()
        return Job.objects.filter(
            status=Job.Status.ACTIVE, deadline__isnull=False, deadline__lt=today
        ).update(status=Job.Status.EXPIRED)
