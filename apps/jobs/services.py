from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.core.models import ActivityLog
from apps.core.services import AuditService
from apps.notifications.models import Notification
from apps.notifications.services import NotificationService
from .models import Job, JobApprovalHistory
from .repository import JobRepository

logger = logging.getLogger("apps.jobs")

_M2M_FIELDS = ("skills_required", "preferred_qualifications")


class JobService:
    """Business logic for the job lifecycle: CRUD, clone, approval, featuring."""

    # ----- create / update -------------------------------------------------
    @transaction.atomic
    def create_job(self, recruiter_profile, validated_data: dict) -> Job:
        m2m = {f: validated_data.pop(f, []) for f in _M2M_FIELDS}
        validated_data["slug"] = self._unique_slug(validated_data.get("title", ""))
        validated_data["recruiter"] = recruiter_profile
        validated_data.setdefault("company", recruiter_profile.company)
        job = Job.objects.create(**validated_data)
        self._set_m2m(job, m2m)
        logger.info("Job created: %s by recruiter %s", job.id, recruiter_profile.id)
        return job

    @transaction.atomic
    def update_job(self, job: Job, recruiter_profile, validated_data: dict) -> Job:
        self._assert_owner(job, recruiter_profile)
        m2m = {f: validated_data.pop(f, None) for f in _M2M_FIELDS}
        for attr, value in validated_data.items():
            setattr(job, attr, value)
        job.save()
        self._set_m2m(job, {k: v for k, v in m2m.items() if v is not None})
        return job

    @transaction.atomic
    def clone_job(self, job: Job, recruiter_profile) -> Job:
        """Duplicate a job as a fresh DRAFT pending approval."""
        self._assert_owner(job, recruiter_profile)
        clone = Job.objects.get(pk=job.pk)
        clone.pk = None
        clone.id = None
        clone._state.adding = True
        clone.title = f"{job.title} (Copy)"
        clone.slug = self._unique_slug(clone.title)
        clone.status = Job.Status.DRAFT
        clone.approval_status = Job.ApprovalStatus.PENDING
        clone.rejection_reason = ""
        clone.reviewed_by = None
        clone.reviewed_at = None
        clone.published_at = None
        clone.is_featured = False
        clone.featured_until = None
        clone.views_count = 0
        clone.applications_count = 0
        clone.save()
        # Copy many-to-many relationships.
        clone.skills_required.set(job.skills_required.all())
        clone.preferred_qualifications.set(job.preferred_qualifications.all())
        logger.info("Job %s cloned to %s", job.id, clone.id)
        return clone

    # ----- recruiter lifecycle actions ------------------------------------
    @transaction.atomic
    def submit_for_approval(self, job: Job, recruiter_profile, ip: str | None = None) -> Job:
        self._assert_owner(job, recruiter_profile)
        from apps.core.models import PlatformSettings
        if job.status not in (Job.Status.DRAFT, Job.Status.EXPIRED):
            raise ValidationError({"detail": "Only draft jobs can be submitted for approval."})
            
        settings = PlatformSettings.get_settings()
        if settings.auto_approve_jobs:
            job.approval_status = Job.ApprovalStatus.APPROVED
            job.status = Job.Status.ACTIVE
            job.published_at = timezone.now()
            job.rejection_reason = ""
            job.save(update_fields=["approval_status", "status", "published_at", "rejection_reason"])
            
            actor = recruiter_profile.user
            self._record_approval(job, JobApprovalHistory.Action.APPROVED, actor, comment="Auto-approved by system settings.")
            AuditService.log(
                user=actor, action=ActivityLog.Action.STATUS_CHANGE,
                entity_type="Job", entity_id=job.id, ip=ip,
                description=f"Job '{job.title}' auto-approved by system.",
                metadata={"event": "auto_approve_jobs"},
            )
            from .visibility_services import ContactVisibilityService
            ContactVisibilityService().initialise_for(job)
            logger.info("Job %s auto-approved on submission", job.id)
            return job

        job.approval_status = Job.ApprovalStatus.PENDING
        job.rejection_reason = ""
        job.save(update_fields=["approval_status", "rejection_reason"])

        actor = recruiter_profile.user
        self._record_approval(job, JobApprovalHistory.Action.SUBMITTED, actor)
        AuditService.log(
            user=actor, action=ActivityLog.Action.STATUS_CHANGE,
            entity_type="Job", entity_id=job.id, ip=ip,
            description=f"Job '{job.title}' submitted for approval.",
            metadata={"event": "submit_for_approval"},
        )
        logger.info("Job %s submitted for approval", job.id)
        return job

    @transaction.atomic
    def publish_job(self, job: Job, recruiter_profile) -> Job:
        self._assert_owner(job, recruiter_profile)
        if not job.is_approved:
            raise ValidationError({"detail": "Job must be approved by an admin before publishing."})
        job.status = Job.Status.ACTIVE
        if job.published_at is None:
            job.published_at = timezone.now()
        job.save(update_fields=["status", "published_at"])
        logger.info("Job %s published", job.id)
        return job

    @transaction.atomic
    def close_job(self, job: Job, recruiter_profile) -> Job:
        self._assert_owner(job, recruiter_profile)
        job.status = Job.Status.CLOSED
        job.save(update_fields=["status"])
        return job

    # ----- admin approval workflow ----------------------------------------
    @transaction.atomic
    def approve_job(self, job: Job, admin_user, auto_publish: bool = True, ip: str | None = None) -> Job:
        job.approval_status = Job.ApprovalStatus.APPROVED
        job.rejection_reason = ""
        job.reviewed_by = admin_user
        job.reviewed_at = timezone.now()
        if auto_publish:
            job.status = Job.Status.ACTIVE
            job.published_at = job.published_at or timezone.now()
        job.save()

        self._record_approval(job, JobApprovalHistory.Action.APPROVED, admin_user)
        AuditService.log(
            user=admin_user, action=ActivityLog.Action.STATUS_CHANGE,
            entity_type="Job", entity_id=job.id, ip=ip,
            description=f"Job '{job.title}' approved.",
            metadata={"event": "approve", "auto_publish": auto_publish},
        )
        # Start the recruiter-contact visibility window on first approval-publish.
        if auto_publish:
            from .visibility_services import ContactVisibilityService
            ContactVisibilityService().initialise_for(job)
        self._notify_recruiter(job, approved=True)
        logger.info("Job %s approved by %s", job.id, admin_user.pk)
        return job

    @transaction.atomic
    def reject_job(self, job: Job, admin_user, reason: str, ip: str | None = None) -> Job:
        if not reason or not reason.strip():
            raise ValidationError({"reason": "A rejection comment is required."})
        job.approval_status = Job.ApprovalStatus.REJECTED
        job.rejection_reason = reason
        job.reviewed_by = admin_user
        job.reviewed_at = timezone.now()
        job.status = Job.Status.DRAFT
        job.save()

        self._record_approval(job, JobApprovalHistory.Action.REJECTED, admin_user, comment=reason)
        AuditService.log(
            user=admin_user, action=ActivityLog.Action.STATUS_CHANGE,
            entity_type="Job", entity_id=job.id, ip=ip,
            description=f"Job '{job.title}' rejected.",
            metadata={"event": "reject", "reason": reason},
        )
        self._notify_recruiter(job, approved=False, comment=reason)
        logger.info("Job %s rejected by %s", job.id, admin_user.pk)
        return job

    # ----- featured placement ---------------------------------------------
    @transaction.atomic
    def set_featured(self, job: Job, *, featured: bool, featured_until=None) -> Job:
        job.is_featured = featured
        job.featured_until = featured_until if featured else None
        job.save(update_fields=["is_featured", "featured_until"])
        logger.info("Job %s featured=%s", job.id, featured)
        return job

    # ----- maintenance -----------------------------------------------------
    def record_view(self, job_id: str) -> None:
        JobRepository.increment_views(job_id)

    def expire_due_jobs(self) -> int:
        count = JobRepository.expire_due_jobs()
        if count:
            logger.info("Expired %d job(s) past deadline", count)
        return count

    # ----- helpers ---------------------------------------------------------
    @staticmethod
    def _record_approval(job: Job, action: str, actor, comment: str = "") -> None:
        JobApprovalHistory.objects.create(job=job, action=action, actor=actor, comment=comment)

    @staticmethod
    def _notify_recruiter(job: Job, *, approved: bool, comment: str = "") -> None:
        recruiter_user = getattr(job.recruiter, "user", None)
        if not recruiter_user:
            return
        if approved:
            ntype = Notification.Type.JOB_APPROVED
            title = "Job approved"
            message = f"Your job '{job.title}' has been approved and is now live."
        else:
            ntype = Notification.Type.JOB_REJECTED
            title = "Job rejected"
            message = f"Your job '{job.title}' was rejected. Reason: {comment}"

        NotificationService.notify(
            recipient=recruiter_user,
            notification_type=ntype,
            title=title,
            message=message,
            entity_type="Job",
            entity_id=job.id,
        )
        try:
            send_mail(
                subject=f"[SevaJobs] {title}",
                message=f"Hi {recruiter_user.first_name},\n\n{message}\n\n— The SevaJobs Team",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recruiter_user.email],
                fail_silently=True,
            )
        except Exception:  # pragma: no cover
            logger.exception("Failed to email approval decision for job %s", job.id)
            
        if approved and job.status == Job.Status.ACTIVE:
            JobService._notify_matching_seekers(job)

    @staticmethod
    def _notify_matching_seekers(job: Job) -> None:
        from apps.accounts.models import JobSeekerProfile
        from apps.applications.models import JobAlert
        from apps.notifications.services import NotificationService
        from apps.notifications.models import Notification
        
        users_to_notify = set()
        
        # 1. Match via JobSeekerProfile
        skill_ids = job.skills_required.values_list('id', flat=True)
        if skill_ids:
            profiles = JobSeekerProfile.objects.filter(
                preferred_job_type=job.job_type,
                skills__id__in=skill_ids
            ).distinct().select_related('user')
            for profile in profiles:
                users_to_notify.add(profile.user)
                
        # 2. Match via JobAlerts
        alerts = JobAlert.objects.filter(is_active=True).select_related('user')
        for alert in alerts:
            match = True
            if alert.job_type and alert.job_type != job.job_type:
                match = False
            if match and alert.experience_level and alert.experience_level != job.experience_level:
                match = False
            if match and alert.location and alert.location.lower() not in (job.location or "").lower():
                match = False
            if match and alert.keyword:
                kw = alert.keyword.lower()
                title_desc = f"{job.title or ''} {job.description or ''}".lower()
                if kw not in title_desc:
                    match = False
            if match:
                users_to_notify.add(alert.user)
        
        for user in users_to_notify:
            NotificationService.notify(
                recipient=user,
                notification_type=Notification.Type.JOB_POSTED,
                title="New job matching your profile or alerts",
                message=f"{job.title} at {job.company.name}",
                entity_type="Job",
                entity_id=job.id,
            )

    @staticmethod
    def _assert_owner(job: Job, recruiter_profile) -> None:
        if job.recruiter_id != recruiter_profile.id:
            raise PermissionDenied("You do not own this job listing.")

    @staticmethod
    def _set_m2m(job: Job, m2m: dict) -> None:
        for field, values in m2m.items():
            getattr(job, field).set(values)

    @staticmethod
    def _unique_slug(title: str) -> str:
        base = slugify(title) or "job"
        slug, counter = base, 1
        while Job.objects.filter(slug=slug).exists():
            slug = f"{base}-{counter}"
            counter += 1
        return slug
