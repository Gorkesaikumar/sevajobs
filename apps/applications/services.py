"""Applicant Tracking System — application lifecycle and notifications."""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import F

from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.jobs.models import Job
from apps.notifications.models import Notification
from apps.notifications.services import NotificationService
from .models import JobApplication, ApplicationStatusHistory

logger = logging.getLogger("apps.applications")

S = JobApplication.Status

#: Allowed recruiter-driven transitions. Withdrawal is candidate-only and is
#: handled separately. Terminal states have no outgoing transitions.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    S.APPLIED: {S.UNDER_REVIEW, S.SHORTLISTED, S.REJECTED},
    S.UNDER_REVIEW: {S.SHORTLISTED, S.REJECTED},
    S.SHORTLISTED: {S.INTERVIEW_SCHEDULED, S.REJECTED},
    S.INTERVIEW_SCHEDULED: {S.SELECTED, S.REJECTED},
    S.SELECTED: set(),
    S.REJECTED: set(),
    S.WITHDRAWN: set(),
}


class ApplicationService:
    """Submission, recruiter pipeline movement, and candidate withdrawal."""

    def __init__(self) -> None:
        self._notifications = NotificationService()

    # ----- candidate: apply -----------------------------------------------
    @transaction.atomic
    def submit(
        self, *, job, applicant, resume, cover_letter: str = "", expected_salary=None
    ) -> JobApplication:
        if JobApplication.objects.filter(job=job, applicant=applicant).exists():
            raise ValidationError({"detail": "You have already applied for this job."})
        if job.status != Job.Status.ACTIVE:
            raise ValidationError({"detail": "This job is no longer accepting applications."})
        if resume.job_seeker_id != applicant.id:
            raise PermissionDenied("You can only apply with your own resume.")

        application = JobApplication.objects.create(
            job=job,
            applicant=applicant,
            resume=resume,
            cover_letter=cover_letter,
            expected_salary=expected_salary,
        )
        self._record_history(application, "", S.APPLIED, applicant)
        Job.objects.filter(id=job.id).update(applications_count=F("applications_count") + 1)

        # Notify the recruiter who owns the job.
        recruiter_user = getattr(job.recruiter, "user", None)
        if recruiter_user:
            self._notifications.notify(
                recipient=recruiter_user,
                actor=applicant,
                notification_type=Notification.Type.APPLICATION_RECEIVED,
                title="New application received",
                message=f"{applicant.full_name} applied for {job.title}.",
                entity_type="JobApplication",
                entity_id=application.id,
            )
        logger.info("Application %s submitted by %s", application.id, applicant.email)
        return application

    # ----- recruiter: move candidate through the pipeline ------------------
    @transaction.atomic
    def move_status(
        self,
        application: JobApplication,
        *,
        new_status: str,
        changed_by,
        note: str = "",
        interview_at=None,
        interview_mode: str = "",
        interview_location: str = "",
    ) -> JobApplication:
        old_status = application.status
        if new_status == old_status:
            raise ValidationError({"status": "Application is already in this status."})
        if new_status not in ALLOWED_TRANSITIONS.get(old_status, set()):
            raise ValidationError(
                {"status": f"Cannot move from '{old_status}' to '{new_status}'."}
            )

        update_fields = ["status"]
        if new_status == S.INTERVIEW_SCHEDULED:
            if not interview_at:
                raise ValidationError({"interview_at": "Interview date/time is required."})
            application.interview_at = interview_at
            application.interview_mode = interview_mode
            application.interview_location = interview_location
            update_fields += ["interview_at", "interview_mode", "interview_location"]

        application.status = new_status
        application.save(update_fields=update_fields)
        self._record_history(application, old_status, new_status, changed_by, note)
        self._notify_candidate(application, new_status)
        logger.info("Application %s moved %s -> %s", application.id, old_status, new_status)
        return application

    # ----- candidate: withdraw --------------------------------------------
    @transaction.atomic
    def withdraw(self, application: JobApplication, applicant) -> JobApplication:
        if application.applicant_id != applicant.id:
            raise PermissionDenied("You cannot withdraw someone else's application.")
        if application.status in JobApplication.TERMINAL_STATUSES:
            raise ValidationError({"detail": "This application can no longer be withdrawn."})
        old_status = application.status
        application.status = S.WITHDRAWN
        application.save(update_fields=["status"])
        self._record_history(application, old_status, S.WITHDRAWN, applicant)
        return application

    # ----- helpers ---------------------------------------------------------
    @staticmethod
    def _record_history(application, from_status, to_status, changed_by, note: str = "") -> None:
        ApplicationStatusHistory.objects.create(
            application=application,
            from_status=from_status,
            to_status=to_status,
            changed_by=changed_by,
            note=note,
        )

    def _notify_candidate(self, application: JobApplication, new_status: str) -> None:
        """In-app + email notification to the candidate on a status change."""
        candidate = application.applicant
        label = application.get_status_display()
        job_title = application.job.title

        title = f"Application update: {label}"
        message = self._status_message(application, new_status, job_title)

        self._notifications.notify(
            recipient=candidate,
            notification_type=Notification.Type.STATUS_CHANGED,
            title=title,
            message=message,
            entity_type="JobApplication",
            entity_id=application.id,
        )
        try:
            send_mail(
                subject=f"[SevaJobs] {title}",
                message=f"Hi {candidate.first_name},\n\n{message}\n\n— The SevaJobs Team",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[candidate.email],
                fail_silently=True,
            )
        except Exception:  # pragma: no cover — never break the transition on email failure
            logger.exception("Failed to send status email for application %s", application.id)

    @staticmethod
    def _status_message(application, new_status: str, job_title: str) -> str:
        if new_status == S.INTERVIEW_SCHEDULED and application.interview_at:
            when = application.interview_at.strftime("%d %b %Y, %H:%M")
            mode = application.get_interview_mode_display() or "Interview"
            where = application.interview_location or "details to follow"
            return (
                f"Your interview for '{job_title}' is scheduled for {when} "
                f"({mode} — {where})."
            )
        messages = {
            S.UNDER_REVIEW: f"Your application for '{job_title}' is now under review.",
            S.SHORTLISTED: f"Good news! You have been shortlisted for '{job_title}'.",
            S.SELECTED: f"Congratulations! You have been selected for '{job_title}'.",
            S.REJECTED: f"Thank you for applying to '{job_title}'. The team has decided not to proceed.",
        }
        return messages.get(new_status, f"Your application status for '{job_title}' is now {new_status}.")
