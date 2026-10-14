"""Notification model (table #12)."""

from __future__ import annotations

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
        UNSUBSCRIBE = "unsubscribe", "User Unsubscribed"
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
    ) -> EmailSuppression | None:
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

    @classmethod
    def unsubscribe(cls, email: str | None, details: dict | None = None) -> EmailSuppression | None:
        """Mark an email address as unsubscribed from bulk campaigns."""
        return cls.suppress(email, reason=cls.Reason.UNSUBSCRIBE, details=details or {})


# ===========================================================================
# Bulk Email Campaigns & Delivery Tracking
# ===========================================================================
class EmailCampaign(BaseModel):
    """
    Campaign metadata for bulk emails dispatched to candidates/employers.
    Scoped to an InstitutionRequirement or other recruitment entity.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        QUEUED = "queued", "Queued"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        PARTIALLY_FAILED = "partially_failed", "Partially Failed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    VALID_TRANSITIONS = {
        Status.DRAFT: {Status.QUEUED, Status.PROCESSING, Status.CANCELLED},
        Status.QUEUED: {Status.PROCESSING, Status.CANCELLED, Status.FAILED},
        Status.PROCESSING: {Status.COMPLETED, Status.PARTIALLY_FAILED, Status.FAILED, Status.CANCELLED},
        Status.COMPLETED: set(),
        Status.PARTIALLY_FAILED: set(),
        Status.FAILED: {Status.QUEUED},  # Allow retry
        Status.CANCELLED: set(),
    }

    name = models.CharField(max_length=255)
    requirement = models.ForeignKey(
        "jobs.InstitutionRequirement",
        on_delete=models.CASCADE,
        related_name="email_campaigns",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_email_campaigns",
    )
    subject = models.CharField(max_length=255)
    body_html = models.TextField()
    body_plain = models.TextField(blank=True)
    selected_statuses = models.JSONField(
        default=list,
        blank=True,
        help_text="List of RequirementCandidateMatch lifecycle status codes targeted.",
    )
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )

    # Recipient metrics counters
    total_recipients = models.PositiveIntegerField(default=0)
    pending_count = models.PositiveIntegerField(default=0)
    sent_count = models.PositiveIntegerField(default=0)
    delivered_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    suppressed_count = models.PositiveIntegerField(default=0)

    scheduled_at = models.DateTimeField(null=True, blank=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_summary = models.TextField(blank=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Email Campaign"
        verbose_name_plural = "Email Campaigns"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["requirement", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_status_display()})"

    def can_transition_to(self, new_status: str) -> bool:
        allowed = self.VALID_TRANSITIONS.get(self.status, set())
        return new_status in allowed

    def transition_to(self, new_status: str, save: bool = True) -> None:
        if not self.can_transition_to(new_status):
            raise ValueError(f"Illegal campaign transition from '{self.status}' to '{new_status}'")
        self.status = new_status
        now = timezone.now()
        if new_status == self.Status.PROCESSING and not self.started_at:
            self.started_at = now
        elif new_status in (self.Status.COMPLETED, self.Status.PARTIALLY_FAILED, self.Status.FAILED, self.Status.CANCELLED):
            self.completed_at = now
        if save:
            self.save(update_fields=["status", "started_at", "completed_at", "updated_at"])


class CampaignRecipient(BaseModel):
    """
    Individual delivery record for a single campaign recipient.
    Guarantees strict 1-to-1 addressing, idempotency, and auditability.
    """

    class RecipientStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        QUEUED = "queued", "Queued"
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Failed"
        SUPPRESSED = "suppressed", "Suppressed"
        CANCELLED = "cancelled", "Cancelled"

    campaign = models.ForeignKey(
        EmailCampaign,
        on_delete=models.CASCADE,
        related_name="recipients",
    )
    candidate = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="campaign_deliveries",
    )
    match = models.ForeignKey(
        "jobs.RequirementCandidateMatch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="campaign_deliveries",
    )
    recipient_name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(db_index=True)
    status = models.CharField(
        max_length=30,
        choices=RecipientStatus.choices,
        default=RecipientStatus.PENDING,
        db_index=True,
    )
    provider_message_id = models.CharField(max_length=150, blank=True, db_index=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True)

    queued_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Campaign Recipient"
        verbose_name_plural = "Campaign Recipients"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "email"],
                name="unique_recipient_per_campaign",
            ),
        ]
        indexes = [
            models.Index(fields=["campaign", "status"]),
            models.Index(fields=["email", "status"]),
            models.Index(fields=["provider_message_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.email} - {self.campaign.name} ({self.status})"


# ===========================================================================
# Reusable Recruitment Email Templates by Status
# ===========================================================================
class RecruitmentEmailTemplate(BaseModel):
    """
    Reusable email template mapped to recruitment lifecycle statuses.
    Supports system defaults, custom administrator edits, and versioning.
    """

    class StatusKey(models.TextChoices):
        SHORTLISTED = "shortlisted", "Shortlisted Candidates"
        INTERVIEWING = "interviewing", "Interviewing Candidates"
        SELECTED = "selected", "Selected Candidates"
        JOINED = "joined", "Joined Candidates"
        REJECTED = "rejected", "Rejected Candidates"
        GENERAL = "general", "General Eligible Candidates"

    name = models.CharField(max_length=150)
    status_key = models.CharField(
        max_length=30,
        choices=StatusKey.choices,
        default=StatusKey.GENERAL,
        db_index=True,
    )
    subject = models.CharField(max_length=255)
    body_html = models.TextField()
    body_plain = models.TextField(blank=True)
    is_default = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Indicates the authoritative default template automatically loaded for this status.",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    version = models.PositiveIntegerField(default=1)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_recruitment_templates",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_recruitment_templates",
    )

    class Meta(BaseModel.Meta):
        verbose_name = "Recruitment Email Template"
        verbose_name_plural = "Recruitment Email Templates"
        ordering = ["status_key", "-is_default", "name"]
        indexes = [
            models.Index(fields=["status_key", "is_default", "is_active"]),
        ]

    def __str__(self) -> str:
        default_badge = " [Default]" if self.is_default else ""
        return f"{self.name} ({self.get_status_key_display()}){default_badge} v{self.version}"

    @classmethod
    def get_default_template(cls, status_key: str) -> RecruitmentEmailTemplate:
        """
        Retrieves the active default template for a given status key.
        If not yet seeded in the database, falls back to the in-memory canonical definition.
        """
        clean_key = str(status_key).strip().lower()
        if clean_key in ("interview_scheduled", "interview"):
            clean_key = cls.StatusKey.INTERVIEWING
        elif clean_key in ("all", "eligible", "matched"):
            clean_key = cls.StatusKey.GENERAL

        valid_keys = [c[0] for c in cls.StatusKey.choices]
        if clean_key not in valid_keys:
            clean_key = cls.StatusKey.GENERAL

        template = cls.objects.filter(status_key=clean_key, is_default=True, is_active=True).first()
        if not template:
            template = cls.objects.filter(status_key=clean_key, is_active=True).first()
        if not template:
            from .default_templates import CANONICAL_TEMPLATES
            defn = CANONICAL_TEMPLATES.get(clean_key, CANONICAL_TEMPLATES[cls.StatusKey.GENERAL])
            template, _ = cls.objects.get_or_create(
                status_key=clean_key,
                is_default=True,
                defaults={
                    "name": defn["name"],
                    "subject": defn["subject"],
                    "body_html": defn["body_html"],
                    "body_plain": defn.get("body_plain", ""),
                    "is_active": True,
                    "version": 1,
                },
            )
        return template


# ===========================================================================
# Daily Email Quota & Usage Accounting
# ===========================================================================
class DailyEmailQuotaTracking(BaseModel):
    """
    Per-day persistent usage ledger tracking Resend dispatches against the daily quota.
    Enforces the operational target (90) and absolute hard limit (100) per calendar day.
    """

    date = models.DateField(unique=True, db_index=True)
    sent_count = models.PositiveIntegerField(
        default=0,
        help_text="Messages successfully accepted by Resend email provider today.",
    )
    reserved_count = models.PositiveIntegerField(
        default=0,
        help_text="Capacity reserved for active or queued campaign recipients today.",
    )
    delivered_count = models.PositiveIntegerField(
        default=0,
        help_text="Messages confirmed delivered via Resend webhooks today.",
    )
    failed_count = models.PositiveIntegerField(
        default=0,
        help_text="Messages or attempts that permanently failed today.",
    )
    daily_limit = models.PositiveIntegerField(
        default=100,
        help_text="Absolute maximum emails allowed per day (configured hard cap).",
    )
    daily_target = models.PositiveIntegerField(
        default=90,
        help_text="Target operational ceiling for daily email dispatches.",
    )
    last_sent_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Daily Email Quota Tracking"
        verbose_name_plural = "Daily Email Quota Tracking"
        ordering = ["-date"]

    def __str__(self) -> str:
        return f"Quota {self.date}: {self.sent_count}/{self.daily_limit} (Reserved: {self.reserved_count})"

    @property
    def total_consumed(self) -> int:
        return self.sent_count + self.reserved_count

    @property
    def remaining_capacity(self) -> int:
        return max(0, self.daily_limit - self.total_consumed)

    @property
    def is_target_reached(self) -> bool:
        return self.total_consumed >= self.daily_target

    @property
    def is_limit_reached(self) -> bool:
        return self.total_consumed >= self.daily_limit


# ===========================================================================
# Bulk Job Alerts Based on Candidate Professional Profiles
# ===========================================================================
class JobAlertCampaign(BaseModel):
    """
    Campaign metadata for bulk job alerts dispatched to candidates based on professional profiles.
    Tracks targeting criteria, matching mode, subject/body snapshot, metrics, and lifecycle.
    """

    class AlertType(models.TextChoices):
        DAILY_DIGEST = "daily_digest", "Daily Job Alert (General)"
        INTERVIEW_ALERT = "interview_alert", "Interview Alert (Personal)"
        WALKIN_ALERT = "walkin_alert", "Walk-in Alert (Urgent)"
        EMPLOYER_ALERT = "employer_alert", "Employer Alert (For Earning)"
        REQUIREMENT_ALERT = "requirement_alert", "Job Requirement Alert (VIP Urgent)"

    class Priority(models.IntegerChoices):
        P1_INTERVIEW = 1, "P1 — Interview Alert"
        P2_WALKIN = 2, "P2 — Walk-in Alert"
        P3_REQUIREMENT = 3, "P3 — Job Requirement Alert"
        P4_DAILY_DIGEST = 4, "P4 — Daily Job Alert"
        P5_EMPLOYER = 5, "P5 — Employer Alert"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        QUEUED = "queued", "Queued"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        PARTIALLY_FAILED = "partially_failed", "Partially Failed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    class MatchingStrategy(models.TextChoices):
        AUTO = "auto", "Auto Match to Eligible Jobs"
        SPECIFIC_JOBS = "specific_jobs", "Selected Specific Vacancies"

    VALID_TRANSITIONS = {
        Status.DRAFT: {Status.QUEUED, Status.PROCESSING, Status.CANCELLED},
        Status.QUEUED: {Status.PROCESSING, Status.CANCELLED, Status.FAILED},
        Status.PROCESSING: {Status.COMPLETED, Status.PARTIALLY_FAILED, Status.FAILED, Status.CANCELLED},
        Status.COMPLETED: set(),
        Status.PARTIALLY_FAILED: set(),
        Status.FAILED: {Status.QUEUED},
        Status.CANCELLED: set(),
    }

    name = models.CharField(max_length=255)
    alert_type = models.CharField(
        max_length=30,
        choices=AlertType.choices,
        default=AlertType.DAILY_DIGEST,
        db_index=True,
    )
    priority = models.PositiveSmallIntegerField(
        choices=Priority.choices,
        default=Priority.P4_DAILY_DIGEST,
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_job_alert_campaigns",
    )
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    matching_strategy = models.CharField(
        max_length=30,
        choices=MatchingStrategy.choices,
        default=MatchingStrategy.AUTO,
    )
    is_recurring = models.BooleanField(default=False, db_index=True)
    recurring_enabled = models.BooleanField(default=True, db_index=True)
    recurring_time = models.TimeField(default="10:00:00", null=True, blank=True)
    requirement = models.ForeignKey(
        "jobs.InstitutionRequirement",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="job_alert_campaigns",
    )
    walkin_job = models.ForeignKey(
        "jobs.Job",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="walkin_alert_campaigns",
    )
    selected_job_ids = models.JSONField(
        default=list,
        blank=True,
        help_text="IDs of specifically approved vacancies if strategy is specific_jobs.",
    )
    targeting_criteria = models.JSONField(
        default=dict,
        blank=True,
        help_text="Targeting filters snapshot (subject, profession, location, experience, salary, etc.).",
    )
    subject = models.CharField(max_length=255)
    body_html = models.TextField()
    body_plain = models.TextField(blank=True)

    # Recipient metrics counters
    total_recipients = models.PositiveIntegerField(default=0)
    pending_count = models.PositiveIntegerField(default=0)
    sent_count = models.PositiveIntegerField(default=0)
    delivered_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    suppressed_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)

    scheduled_at = models.DateTimeField(null=True, blank=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_summary = models.TextField(blank=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Job Alert Campaign"
        verbose_name_plural = "Job Alert Campaigns"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_status_display()})"

    def can_transition_to(self, new_status: str) -> bool:
        allowed = self.VALID_TRANSITIONS.get(self.status, set())
        return new_status in allowed

    def transition_to(self, new_status: str, save: bool = True) -> None:
        if not self.can_transition_to(new_status):
            raise ValueError(f"Illegal campaign transition from '{self.status}' to '{new_status}'")
        self.status = new_status
        now = timezone.now()
        if new_status == self.Status.PROCESSING and not self.started_at:
            self.started_at = now
        elif new_status in (self.Status.COMPLETED, self.Status.PARTIALLY_FAILED, self.Status.FAILED, self.Status.CANCELLED):
            self.completed_at = now
        if save:
            self.save(update_fields=["status", "started_at", "completed_at", "updated_at"])


class JobAlertRecipient(BaseModel):
    """
    Delivery record for a single candidate recipient in a Job Alert campaign.
    Captures snapshot of matching vacancies, delivery state, provider message ID, and audit trail.
    """

    class RecipientStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        QUEUED = "queued", "Queued"
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Failed"
        SUPPRESSED = "suppressed", "Suppressed"
        SKIPPED = "skipped", "Skipped"
        CANCELLED = "cancelled", "Cancelled"

    class RecipientType(models.TextChoices):
        CANDIDATE = "candidate", "Job Seeker"
        EMPLOYER = "employer", "Employer / Recruiter"

    campaign = models.ForeignKey(
        JobAlertCampaign,
        on_delete=models.CASCADE,
        related_name="recipients",
    )
    candidate = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="job_alert_deliveries",
    )
    recipient_type = models.CharField(
        max_length=20,
        default=RecipientType.CANDIDATE,
        choices=RecipientType.choices,
        db_index=True,
    )
    employer = models.ForeignKey(
        "recruiters.RecruiterProfile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="employer_alert_deliveries",
    )
    recipient_name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(db_index=True)
    profession = models.CharField(max_length=150, blank=True)
    subject = models.CharField(max_length=150, blank=True)
    location = models.CharField(max_length=200, blank=True)

    matched_job_count = models.PositiveSmallIntegerField(default=0)
    matched_jobs_data = models.JSONField(
        default=list,
        blank=True,
        help_text="Snapshot list of matched vacancies dicts: {id, title, organization, location, salary, url, job_type}",
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Contextual details (interview details, walkin data, requirement code, etc.)",
    )

    status = models.CharField(
        max_length=30,
        choices=RecipientStatus.choices,
        default=RecipientStatus.PENDING,
        db_index=True,
    )
    provider_message_id = models.CharField(max_length=150, blank=True, db_index=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True)
    exclusion_reason = models.CharField(max_length=255, blank=True)

    queued_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Job Alert Recipient"
        verbose_name_plural = "Job Alert Recipients"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "email"],
                name="unique_candidate_per_job_alert_campaign",
            ),
        ]
        indexes = [
            models.Index(fields=["campaign", "status"]),
            models.Index(fields=["email", "status"]),
            models.Index(fields=["provider_message_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.email} - {self.campaign.name} ({self.status}) [{self.matched_job_count} jobs]"


class CandidateJobAlertDelivery(BaseModel):
    """
    Persistent audit record of every job alert sent to a candidate for a specific vacancy.
    Enforces deduplication policy to prevent candidates receiving repeated alerts for the same job.
    """

    class JobType(models.TextChoices):
        RECRUITER = "recruiter", "Recruiter Job"
        STAFF = "staff", "Staff Job"
        REQUIREMENT = "requirement", "Institution Requirement"
        WALKIN = "walkin", "Walk-in Vacancy"
        INTERVIEW = "interview", "Interview Notice"

    candidate = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="job_alert_history",
    )
    job_type = models.CharField(
        max_length=20,
        choices=JobType.choices,
        default=JobType.RECRUITER,
        db_index=True,
    )
    job_id = models.UUIDField(db_index=True)
    campaign = models.ForeignKey(
        JobAlertCampaign,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deliveries",
    )
    recipient = models.ForeignKey(
        JobAlertRecipient,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="job_deliveries",
    )
    status = models.CharField(max_length=30, default="sent", db_index=True)
    provider_message_id = models.CharField(max_length=150, blank=True, db_index=True)
    dedup_key = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Format: candidate_uuid:job_uuid",
    )
    sent_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Candidate Job Alert Delivery"
        verbose_name_plural = "Candidate Job Alert Deliveries"
        ordering = ["-sent_at"]
        indexes = [
            models.Index(fields=["candidate", "job_id", "-sent_at"]),
            models.Index(fields=["dedup_key", "-sent_at"]),
        ]

    def __str__(self) -> str:
        return f"Delivery to {self.candidate_id} for Job {self.job_id} at {self.sent_at}"

    @classmethod
    def record_delivery(
        cls,
        *,
        candidate,
        job_id,
        job_type: str = "recruiter",
        campaign=None,
        recipient=None,
        status: str = "sent",
        provider_message_id: str = "",
        sent_at=None,
    ) -> CandidateJobAlertDelivery:
        cand_id = getattr(candidate, "id", candidate)
        j_id = str(job_id)
        dedup_key = f"{cand_id}:{j_id}"
        create_kwargs = {
            "job_type": job_type,
            "job_id": j_id,
            "campaign": campaign,
            "recipient": recipient,
            "status": status,
            "provider_message_id": provider_message_id,
            "dedup_key": dedup_key,
            "sent_at": sent_at or timezone.now(),
        }
        if hasattr(candidate, "id"):
            create_kwargs["candidate"] = candidate
        else:
            create_kwargs["candidate_id"] = cand_id
        return cls.objects.create(**create_kwargs)

    @classmethod
    def is_duplicate(
        cls,
        *,
        candidate_id,
        job_id,
        dedup_window_days: int = 14,
    ) -> bool:
        """
        Returns True if this vacancy was already delivered to this candidate within dedup_window_days.
        """
        if not dedup_window_days or int(dedup_window_days) <= 0:
            return False
        from datetime import timedelta
        cutoff = timezone.now() - timedelta(days=int(dedup_window_days))
        dedup_key = f"{str(candidate_id)}:{str(job_id)}"
        return cls.objects.filter(
            dedup_key=dedup_key,
            status__in=["sent", "delivered"],
            sent_at__gte=cutoff,
        ).exists()



