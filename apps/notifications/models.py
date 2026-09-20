"""Notification model (table #12)."""

from django.conf import settings
from django.db import models
from django.utils import timezone
from apps.core.models import BaseModel


class Notification(BaseModel):
    """
    An in-app notification delivered to a single recipient (table #12).

    `actor` is the user who triggered the event (nullable for system events).
    `entity_type` + `entity_id` provide a generic deep-link to the related
    object (a Job, an Application, etc.) without a hard foreign key.
    """

    class Type(models.TextChoices):
        APPLICATION_RECEIVED = "application_received", "Application Received"
        STATUS_CHANGED = "status_changed", "Application Status Changed"
        APPLICATION_SHORTLISTED = "application_shortlisted", "Application Shortlisted"
        INTERVIEW_SCHEDULED = "interview_scheduled", "Interview Scheduled"
        APPLICATION_SELECTED = "application_selected", "Application Selected"
        APPLICATION_REJECTED = "application_rejected", "Application Rejected"
        JOB_POSTED = "job_posted", "Job Posted"
        JOB_APPROVED = "job_approved", "Job Approved"
        JOB_REJECTED = "job_rejected", "Job Rejected"
        JOB_EXPIRING = "job_expiring", "Job Expiring Soon"
        PROFILE_VIEWED = "profile_viewed", "Profile Viewed"
        SYSTEM = "system", "System"
        JOB_ASSIGNED = "job_assigned", "Job Assigned"
        JOB_REASSIGNED = "job_reassigned", "Job Reassigned"
        RECRUITMENT_COMPLETED = "recruitment_completed", "Recruitment Completed"
        CANDIDATE_SELECTED = "candidate_selected", "Candidate Selected"
        HIGH_APP_VOLUME = "high_app_volume", "High Application Volume"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="triggered_notifications",
    )
    notification_type = models.CharField(max_length=30, choices=Type.choices, db_index=True)
    title = models.CharField(max_length=255)
    message = models.TextField(blank=True)
    entity_type = models.CharField(max_length=100, blank=True)
    entity_id = models.UUIDField(null=True, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True, help_text="Structured data for rich notifications (e.g. interview details).")

    class Meta(BaseModel.Meta):
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        indexes = [
            models.Index(fields=["recipient", "is_read", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.notification_type} → {self.recipient_id}"

    def mark_read(self) -> None:
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at"])


# ===========================================================================
# Table — EmailSuppression (AWS SES Bounces & Complaints)
# ===========================================================================
class EmailSuppression(BaseModel):
    """
    Stores email addresses that experienced hard bounces or spam complaints.
    Used to suppress future outbound transactional emails to prevent SES domain reputation damage.
    """

    class Reason(models.TextChoices):
        BOUNCE = "bounce", "Permanent Bounce"
        COMPLAINT = "complaint", "Spam Complaint"
        MANUAL = "manual", "Manual Suppression"

    email = models.EmailField(unique=True, db_index=True)
    reason = models.CharField(max_length=20, choices=Reason.choices, default=Reason.BOUNCE, db_index=True)
    bounce_type = models.CharField(max_length=50, blank=True)
    bounce_sub_type = models.CharField(max_length=50, blank=True)
    details = models.JSONField(default=dict, blank=True, help_text="Raw event payload from AWS SNS.")

    class Meta(BaseModel.Meta):
        verbose_name = "Email Suppression"
        verbose_name_plural = "Email Suppressions"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.email} ({self.reason})"

    @classmethod
    def is_suppressed(cls, email: str | None) -> bool:
        if not email or not isinstance(email, str) or not email.strip():
            return False
        return cls.objects.filter(email=email.strip().lower()).exists()

    @classmethod
    def suppress(
        cls,
        email: str | None,
        reason: str,
        bounce_type: str = "",
        bounce_sub_type: str = "",
        details: dict | None = None,
    ) -> "EmailSuppression" | None:
        if not email or not isinstance(email, str) or not email.strip():
            return None
        normalized = email.strip().lower()
        obj, _ = cls.objects.update_or_create(
            email=normalized,
            defaults={
                "reason": reason,
                "bounce_type": bounce_type[:50],
                "bounce_sub_type": bounce_sub_type[:50],
                "details": details or {},
            },
        )
        return obj
