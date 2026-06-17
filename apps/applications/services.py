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
from .models import JobApplication, ApplicationStatusHistory, RecruiterNote

logger = logging.getLogger("apps.applications")

S = JobApplication.Status

#: Allowed recruiter-driven transitions. Withdrawal is candidate-only and is
#: handled separately. Terminal states have no outgoing transitions.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    S.APPLIED: {S.UNDER_REVIEW, S.SHORTLISTED, S.REJECTED, S.ARCHIVED},
    S.UNDER_REVIEW: {S.SHORTLISTED, S.REJECTED, S.ARCHIVED, S.APPLIED},
    S.SHORTLISTED: {S.INTERVIEW_SCHEDULED, S.INTERVIEW_CANCELLED, S.INTERVIEW_COMPLETED, S.SELECTED, S.REJECTED, S.UNDER_REVIEW, S.ARCHIVED},
    S.INTERVIEW_SCHEDULED: {S.INTERVIEWING, S.INTERVIEW_COMPLETED, S.INTERVIEW_CANCELLED, S.SELECTED, S.REJECTED, S.SHORTLISTED, S.ARCHIVED},
    S.INTERVIEWING: {S.INTERVIEW_COMPLETED, S.INTERVIEW_CANCELLED, S.SELECTED, S.REJECTED, S.SHORTLISTED, S.ARCHIVED},
    S.INTERVIEW_COMPLETED: {S.DECISION_PENDING, S.SELECTED, S.REJECTED, S.ARCHIVED},
    S.DECISION_PENDING: {S.SELECTED, S.REJECTED, S.ARCHIVED},
    S.INTERVIEW_CANCELLED: {S.SHORTLISTED, S.INTERVIEW_SCHEDULED, S.REJECTED, S.ARCHIVED},
    S.SELECTED: {S.OFFER_SENT, S.OFFER_ACCEPTED, S.REJECTED, S.ARCHIVED},
    S.OFFER_SENT: {S.OFFER_ACCEPTED, S.REJECTED, S.SELECTED, S.ARCHIVED},
    S.OFFER_ACCEPTED: {S.JOINED, S.REJECTED, S.ARCHIVED},
    S.JOINED: {S.ARCHIVED},
    S.REJECTED: {S.ARCHIVED, S.UNDER_REVIEW},
    S.WITHDRAWN: set(),
    S.ARCHIVED: set(),
}

#: Statuses that require an interview slot to be present at transition time.
INTERVIEW_REQUIRED_STATUSES = {S.INTERVIEW_SCHEDULED}

#: Notification.Type mapping for stage-specific candidate notifications. Falls
#: back to STATUS_CHANGED for stages without a dedicated event type.
_STATUS_TO_NOTIFICATION = {
    S.SHORTLISTED: "application_shortlisted",
    S.INTERVIEW_SCHEDULED: "interview_scheduled",
    S.SELECTED: "application_selected",
    S.OFFER_ACCEPTED: "offer_accepted",
    S.JOINED: "joining_confirmed",
    S.REJECTED: "application_rejected",
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
        interview_type: str = "",
        interviewer_name: str = "",
        meeting_link: str = "",
        monthly_salary=None,
        annual_ctc=None,
        probation_period="",
        benefits="",
        working_hours="",
        joining_date=None,
        valid_until=None,
    ) -> JobApplication:
        from django.utils import timezone

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
            if interview_type:
                application.interview_type = interview_type
            if interviewer_name:
                application.interviewer_name = interviewer_name
            if meeting_link:
                application.meeting_link = meeting_link
            update_fields += [
                "interview_at", "interview_mode", "interview_location",
                "interview_type", "interviewer_name", "meeting_link",
            ]

        if new_status == S.SHORTLISTED:
            application.shortlisted_at = timezone.now()
            application.shortlisted_by = changed_by
            update_fields += ["shortlisted_at", "shortlisted_by"]

        if new_status == S.SELECTED:
            from .models import CandidateSelection, OfferDetails
            CandidateSelection.objects.update_or_create(
                application=application,
                defaults={"selected_by": changed_by}
            )
            OfferDetails.objects.update_or_create(
                application=application,
                defaults={
                    "status": OfferDetails.OfferStatus.PENDING,
                    "monthly_salary": monthly_salary or 0,
                    "annual_ctc": annual_ctc or 0,
                    "probation_period": probation_period or "",
                    "benefits": benefits or "",
                    "working_hours": working_hours or "",
                    "joining_date": joining_date,
                    "valid_until": valid_until,
                }
            )

        if new_status == S.OFFER_ACCEPTED:
            if hasattr(application, "offer_details"):
                application.offer_details.status = "accepted"
                application.offer_details.save(update_fields=["status"])
            
            # Notify recruiter
            recruiter_user = getattr(application.job.recruiter, "user", None)
            if recruiter_user:
                self._notifications.notify(
                    recipient=recruiter_user,
                    actor=application.applicant,
                    notification_type="offer_accepted",
                    title="Offer Accepted",
                    message=f"{application.applicant.full_name} has accepted the offer for {application.job.title}.",
                    entity_type="JobApplication",
                    entity_id=application.id,
                )

            # Auto-closure logic based on filled vacancies
            job = application.job
            accepted_count = JobApplication.objects.filter(
                job=job,
                status__in=[JobApplication.Status.OFFER_ACCEPTED, JobApplication.Status.JOINED]
            ).count()
            if accepted_count >= job.vacancies:
                job.status = "closed"
                job.save(update_fields=["status"])

                # Notify recruiter that position is filled
                if recruiter_user:
                    self._notifications.notify(
                        recipient=recruiter_user,
                        title="Position Filled",
                        message=f"All {job.vacancies} vacancies for '{job.title}' have been successfully accepted. The job is now closed.",
                        notification_type="system"
                    )

        if new_status == S.REJECTED:
            if hasattr(application, "offer_details"):
                application.offer_details.status = "declined"
                application.offer_details.save(update_fields=["status"])

            from .models import CandidateRejection
            CandidateRejection.objects.update_or_create(
                application=application,
                defaults={"rejected_by": changed_by, "reason": note or "Not specified"}
            )

            if old_status in [S.SELECTED, S.OFFER_SENT, S.OFFER_ACCEPTED]:
                # Notify recruiter
                recruiter_user = getattr(application.job.recruiter, "user", None)
                if recruiter_user:
                    self._notifications.notify(
                        recipient=recruiter_user,
                        actor=application.applicant,
                        notification_type="offer_declined",
                        title="Offer Declined",
                        message=f"{application.applicant.full_name} has declined the offer for {application.job.title}.",
                        entity_type="JobApplication",
                        entity_id=application.id,
                    )

        if new_status == S.JOINED:
            if hasattr(application, "offer_details"):
                application.offer_details.status = "joined"
                application.offer_details.save(update_fields=["status"])

            # Notify recruiter
            recruiter_user = getattr(application.job.recruiter, "user", None)
            if recruiter_user:
                self._notifications.notify(
                    recipient=recruiter_user,
                    actor=application.applicant,
                    notification_type="joining_confirmed",
                    title="Candidate Joined",
                    message=f"{application.applicant.full_name} has joined as {application.job.title}.",
                    entity_type="JobApplication",
                    entity_id=application.id,
                )

        application.status = new_status
        application.save(update_fields=update_fields)
        self._record_history(application, old_status, new_status, changed_by, note)
        self._notify_candidate(application, new_status)
        logger.info("Application %s moved %s -> %s", application.id, old_status, new_status)
        return application

    # ----- bulk recruiter actions -----------------------------------------
    @transaction.atomic
    def bulk_move_status(self, application_ids, *, new_status: str, changed_by, company) -> dict:
        """Move many applications to the same status. Returns counts {ok, failed}."""
        qs = JobApplication.objects.filter(id__in=application_ids, job__company=company)
        ok, failed = 0, 0
        errors: list[str] = []
        for app in qs:
            try:
                self.move_status(app, new_status=new_status, changed_by=changed_by)
                ok += 1
            except (ValidationError, PermissionDenied) as e:
                failed += 1
                errors.append(f"{app.id}: {e}")
        return {"ok": ok, "failed": failed, "errors": errors}

    # ----- recruiter notes ------------------------------------------------
    @transaction.atomic
    def add_note(self, application: JobApplication, *, author, body: str) -> RecruiterNote:
        body = (body or "").strip()
        if not body:
            raise ValidationError({"body": "Note cannot be empty."})
        if len(body) > 5000:
            raise ValidationError({"body": "Note is too long (5000 chars max)."})
        return RecruiterNote.objects.create(application=application, author=author, body=body)

    @transaction.atomic
    def edit_note(self, note: RecruiterNote, *, editor, body: str) -> RecruiterNote:
        if note.author_id and editor.id != note.author_id and not getattr(editor, "is_admin_role", False):
            raise PermissionDenied("You can only edit notes you authored.")
        body = (body or "").strip()
        if not body:
            raise ValidationError({"body": "Note cannot be empty."})
        note.body = body
        note.save(update_fields=["body", "updated_at"])
        return note

    @transaction.atomic
    def delete_note(self, note: RecruiterNote, *, actor) -> None:
        if note.author_id and actor.id != note.author_id and not getattr(actor, "is_admin_role", False):
            raise PermissionDenied("You can only delete notes you authored.")
        note.delete()

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
        company_name = getattr(application.job, "company", None)
        company_name = company_name.name if company_name else "the employer"

        ntype = _STATUS_TO_NOTIFICATION.get(new_status, Notification.Type.STATUS_CHANGED)

        # Build rich metadata for notifications
        notif_metadata: dict = {}
        if new_status == S.INTERVIEW_SCHEDULED and application.interview_at:
            when = application.interview_at
            notif_metadata = {
                "interview_date": when.strftime("%Y-%m-%d"),
                "interview_time": when.strftime("%H:%M"),
                "interview_date_display": when.strftime("%A, %d %B %Y"),
                "interview_time_display": when.strftime("%I:%M %p"),
                "interview_type": application.interview_type,
                "interview_mode": application.interview_mode,
                "interview_mode_display": application.get_interview_mode_display(),
                "interviewer_name": application.interviewer_name,
                "meeting_link": application.meeting_link,
                "interview_location": application.interview_location,
                "job_title": job_title,
                "company_name": company_name,
                "application_id": str(application.id),
            }
            title = f"Interview Scheduled — {job_title}"
            message = self._build_interview_message(application, job_title, company_name)
        elif new_status == S.SELECTED:
            title = "🎉 Congratulations! You have been selected"
            message = self._status_message(application, new_status, job_title)
            
            offer = getattr(application, "offer_details", None)
            selection_date = ""
            offer_status = ""
            offer_package = ""
            joining_date = ""
            if offer:
                selection_date = offer.created_at.strftime("%Y-%m-%d")
                offer_status = offer.get_status_display()
                offer_package = f"₹{offer.annual_ctc:,} CTC / ₹{offer.monthly_salary:,} monthly"
                joining_date = offer.joining_date.strftime("%Y-%m-%d") if offer.joining_date else ""

            notif_metadata = {
                "job_title": job_title,
                "company_name": company_name,
                "selection_date": selection_date,
                "offer_status": offer_status,
                "offer_package_summary": offer_package,
                "joining_date": joining_date,
                "application_id": str(application.id),
                "has_offer": True,
            }
        elif new_status == S.REJECTED:
            title = "Application Update"
            message = self._status_message(application, new_status, job_title)
            notif_metadata = {
                "job_title": job_title,
                "company_name": company_name,
                "application_id": str(application.id),
            }
        elif new_status == S.SHORTLISTED:
            title = f"🎉 You've been shortlisted for {job_title}"
            message = self._status_message(application, new_status, job_title)
            notif_metadata = {
                "job_title": job_title,
                "company_name": company_name,
                "application_id": str(application.id),
            }
        else:
            title = f"Application update: {label}"
            message = self._status_message(application, new_status, job_title)
            notif_metadata = {
                "job_title": job_title,
                "company_name": company_name,
                "application_id": str(application.id),
                "status": new_status,
            }

        self._notifications.notify(
            recipient=candidate,
            notification_type=ntype,
            title=title,
            message=message,
            entity_type="JobApplication",
            entity_id=application.id,
            metadata=notif_metadata,
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
        company_name = getattr(application.job, "company", None)
        company_name = company_name.name if company_name else "the institution"

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
            S.SELECTED: (
                f"🎉 Congratulations!\n\n"
                f"You have been selected for the position of {job_title} at {company_name}.\n\n"
                f"Please review your offer details in the Selected/Rejected section."
            ),
            S.REJECTED: (
                f"Application Update\n\n"
                f"Thank you for applying for {job_title} at {company_name}.\n\n"
                f"After careful consideration, your application has not been selected for this position.\n\n"
                f"We encourage you to explore other opportunities available on the platform."
            ),
        }
        return messages.get(new_status, f"Your application status for '{job_title}' is now {new_status}.")
    @staticmethod
    def _build_interview_message(application, job_title: str, company_name: str) -> str:
        """Build a rich, multi-line message for interview_scheduled notifications."""
        when = application.interview_at
        lines = [
            f"Your interview for {job_title} at {company_name} has been scheduled.",
            "",
            f"Date: {when.strftime('%A, %d %B %Y')}",
            f"Time: {when.strftime('%I:%M %p')}",
            f"Mode: {application.get_interview_mode_display() or 'TBD'}",
        ]
        if application.interview_type:
            lines.append(f"Type: {application.get_interview_type_display()}")
        if application.interviewer_name:
            lines.append(f"Interviewer: {application.interviewer_name}")
        if application.meeting_link:
            lines.append(f"Meeting Link: {application.meeting_link}")
        if application.interview_location:
            lines.append(f"Location: {application.interview_location}")
        lines.append("")
        lines.append("Please confirm your attendance from your dashboard.")
        return "\n".join(lines)

