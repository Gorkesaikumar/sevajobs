"""Job application models: JobApplication and its status history."""

from django.conf import settings
from django.db import models
from apps.core.models import BaseModel


# ===========================================================================
# Table #7 — JobApplication
# ===========================================================================
class JobApplication(BaseModel):
    """
    A job seeker's application to a single job (table #7).

    The (job, applicant) pair is unique — a candidate cannot apply twice to the
    same posting. A snapshot of the chosen Resume is referenced via FK.
    """

    class Status(models.TextChoices):
        APPLIED = "applied", "Applied"
        UNDER_REVIEW = "under_review", "Under Review"
        SHORTLISTED = "shortlisted", "Shortlisted"
        INTERVIEW_SCHEDULED = "interview_scheduled", "Interview Scheduled"
        INTERVIEWING = "interviewing", "Interviewing"
        INTERVIEW_COMPLETED = "interview_completed", "Completed"
        DECISION_PENDING = "decision_pending", "Decision Pending"
        INTERVIEW_CANCELLED = "interview_cancelled", "Cancelled"
        SELECTED = "selected", "Selected"
        OFFER_SENT = "offer_sent", "Offer Sent"
        OFFER_ACCEPTED = "offer_accepted", "Offer Accepted"
        JOINED = "joined", "Joined"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"
        ARCHIVED = "archived", "Archived"

    #: Terminal states — no further recruiter transitions allowed.
    TERMINAL_STATUSES = {Status.JOINED, Status.REJECTED, Status.WITHDRAWN, Status.ARCHIVED}

    class InterviewMode(models.TextChoices):
        ONSITE = "onsite", "On-site"
        VIDEO = "video", "Video Call"
        PHONE = "phone", "Phone"

    class InterviewType(models.TextChoices):
        ONLINE = "online", "Online"
        OFFLINE = "offline", "Offline"
        TELEPHONIC = "telephonic", "Telephonic"

    job = models.ForeignKey("jobs.Job", on_delete=models.CASCADE, related_name="applications")
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="applications",
        limit_choices_to={"role": "job_seeker"},
    )
    resume = models.ForeignKey(
        "accounts.Resume",
        on_delete=models.PROTECT,
        related_name="applications",
    )
    cover_letter = models.TextField(blank=True)
    expected_salary = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=25, choices=Status.choices, default=Status.APPLIED, db_index=True
    )
    recruiter_notes = models.TextField(blank=True)

    # Interview scheduling (populated when status → INTERVIEW_SCHEDULED)
    interview_at = models.DateTimeField(null=True, blank=True)
    interview_mode = models.CharField(max_length=10, choices=InterviewMode.choices, blank=True)
    interview_location = models.CharField(
        max_length=255, blank=True, help_text="Address or meeting link."
    )
    interview_type = models.CharField(
        max_length=12, choices=InterviewType.choices, blank=True,
        help_text="Online / Offline / Telephonic — ATS preferred classification.",
    )
    interviewer_name = models.CharField(max_length=150, blank=True)
    meeting_link = models.URLField(blank=True)
    interview_remarks = models.TextField(blank=True)

    class InterviewResponse(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        DECLINED = "declined", "Declined"
        RESCHEDULE_REQUESTED = "reschedule_requested", "Reschedule Requested"

    interview_response = models.CharField(
        max_length=25, choices=InterviewResponse.choices,
        default=InterviewResponse.PENDING, blank=True,
        help_text="Candidate's RSVP to the scheduled interview.",
    )
    interview_response_note = models.TextField(blank=True, help_text="Optional note from the candidate.")


    # Shortlist attribution — populated when status → SHORTLISTED.
    shortlisted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    shortlisted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="shortlisted_applications",
    )

    applied_at = models.DateTimeField(auto_now_add=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Job Application"
        verbose_name_plural = "Job Applications"
        constraints = [
            models.UniqueConstraint(fields=["job", "applicant"], name="unique_application_per_job"),
        ]
        indexes = [
            models.Index(fields=["status", "applied_at"]),
            models.Index(fields=["job", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.applicant.email} → {self.job.title}"


class ApplicationStatusHistory(BaseModel):
    """Append-only audit trail of every status transition on an application."""

    application = models.ForeignKey(
        JobApplication, on_delete=models.CASCADE, related_name="history"
    )
    from_status = models.CharField(max_length=25, blank=True)
    to_status = models.CharField(max_length=25)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    note = models.TextField(blank=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Application Status History"
        verbose_name_plural = "Application Status Histories"
        ordering = ["-created_at"]


class SavedJob(BaseModel):
    """
    A job a seeker has bookmarked for later. The (user, job) pair is unique so
    a job can be saved at most once per user.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_jobs",
        limit_choices_to={"role": "job_seeker"},
    )
    job = models.ForeignKey("jobs.Job", on_delete=models.CASCADE, related_name="saved_by")

    class Meta(BaseModel.Meta):
        verbose_name = "Saved Job"
        verbose_name_plural = "Saved Jobs"
        constraints = [
            models.UniqueConstraint(fields=["user", "job"], name="unique_saved_job_per_user"),
        ]
        indexes = [models.Index(fields=["user", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.user.email} ★ {self.job.title}"


class JobAlert(BaseModel):
    """
    A user's saved preferences for job notifications.
    """
    
    JOB_TYPE_CHOICES = (
        ("full_time", "Full Time"),
        ("part_time", "Part Time"),
        ("contract", "Contract"),
        ("freelance", "Freelance"),
        ("internship", "Internship"),
    )
    
    EXPERIENCE_LEVEL_CHOICES = (
        ("fresher", "Fresher"),
        ("junior", "Junior (1–3 yrs)"),
        ("mid", "Mid (3–6 yrs)"),
        ("senior", "Senior (6+ yrs)"),
        ("lead", "Lead / Principal"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="job_alerts",
        limit_choices_to={"role": "job_seeker"},
    )
    keyword = models.CharField(max_length=255, blank=True)
    location = models.CharField(max_length=255, blank=True)
    job_type = models.CharField(max_length=50, choices=JOB_TYPE_CHOICES, blank=True)
    experience_level = models.CharField(max_length=50, choices=EXPERIENCE_LEVEL_CHOICES, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Job Alert"
        verbose_name_plural = "Job Alerts"
        indexes = [models.Index(fields=["user", "is_active"])]

    def __str__(self) -> str:
        return f"Alert for {self.user.email}: {self.keyword} @ {self.location}"


class RecruiterNote(BaseModel):
    """
    A recruiter-authored note attached to a single application.

    Multi-note model — recruiters can add, edit, and delete individual notes.
    Soft-edit: `updated_at` tracks revisions; deletion is hard (with audit trail
    captured via the parent application's history if desired).
    """

    application = models.ForeignKey(
        JobApplication, on_delete=models.CASCADE, related_name="notes"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="authored_application_notes",
    )
    body = models.TextField()

    class Meta(BaseModel.Meta):
        verbose_name = "Recruiter Note"
        verbose_name_plural = "Recruiter Notes"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["application", "-created_at"])]

    def __str__(self) -> str:
        return f"Note on {self.application_id} by {self.author_id}"


class CandidateSelection(BaseModel):
    """
    Represents the event when a candidate is selected for a job.
    """
    application = models.OneToOneField(
        JobApplication, on_delete=models.CASCADE, related_name="selection"
    )
    selected_at = models.DateTimeField(auto_now_add=True)
    selected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )

    class Meta(BaseModel.Meta):
        verbose_name = "Candidate Selection"
        verbose_name_plural = "Candidate Selections"

    def __str__(self) -> str:
        return f"Selection for {self.application_id}"


class OfferDetails(BaseModel):
    """
    Stores offer information generated when a candidate is selected.
    """
    class OfferStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        VIEWED = "viewed", "Viewed"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"
        EXPIRED = "expired", "Expired"
        JOINED = "joined", "Joined"

    application = models.OneToOneField(
        JobApplication, on_delete=models.CASCADE, related_name="offer_details"
    )
    status = models.CharField(
        max_length=20, choices=OfferStatus.choices, default=OfferStatus.DRAFT, db_index=True
    )
    monthly_salary = models.PositiveIntegerField(default=0)
    annual_ctc = models.PositiveIntegerField(default=0)
    probation_period = models.CharField(max_length=100, blank=True)
    benefits = models.TextField(blank=True)
    working_hours = models.CharField(max_length=100, blank=True)
    joining_date = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)  # Expiry date

    # Custom Builder fields
    institution_name = models.CharField(max_length=255, blank=True)
    institution_address = models.TextField(blank=True)
    institution_contact = models.CharField(max_length=100, blank=True)
    salary_package = models.CharField(max_length=100, blank=True)
    additional_terms = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    # Joining details
    employee_id = models.CharField(max_length=50, blank=True)
    remarks = models.TextField(blank=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Offer Detail"
        verbose_name_plural = "Offer Details"

    def __str__(self) -> str:
        return f"Offer {self.status} for {self.application_id}"


class CandidateRejection(BaseModel):
    """
    Represents the event when a candidate is rejected.
    """
    application = models.OneToOneField(
        JobApplication, on_delete=models.CASCADE, related_name="rejection"
    )
    rejected_at = models.DateTimeField(auto_now_add=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    reason = models.TextField(blank=True, help_text="Reason for rejection.")

    class Meta(BaseModel.Meta):
        verbose_name = "Candidate Rejection"
        verbose_name_plural = "Candidate Rejections"

    def __str__(self) -> str:
        return f"Rejection for {self.application_id}"


class WhatsAppLog(BaseModel):
    class MessageType(models.TextChoices):
        COMPOSER_OPENED = "composer_opened", "WhatsApp Composer Opened"
        MESSAGE_EDITED = "message_edited", "WhatsApp Message Edited"
        REDIRECT_TRIGGERED = "redirect_triggered", "WhatsApp Redirect Triggered"
        OFFER_SENT = "offer_sent", "Offer Message Sent"

    recruiter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="whatsapp_sent_logs",
        help_text="The recruiter who triggered/sent the message."
    )
    candidate = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="whatsapp_received_logs",
        help_text="The candidate to whom the message was targeted."
    )
    job = models.ForeignKey(
        "jobs.Job",
        on_delete=models.CASCADE,
        related_name="whatsapp_logs",
        help_text="The job related to the selection/offer."
    )
    message_type = models.CharField(
        max_length=50,
        choices=MessageType.choices,
        help_text="The type of action tracked."
    )
    message_text = models.TextField(blank=True, help_text="The customized text message.")

    class Meta(BaseModel.Meta):
        verbose_name = "WhatsApp Log"
        verbose_name_plural = "WhatsApp Logs"

    def __str__(self) -> str:
        return f"WhatsApp Log ({self.message_type}) - Recruiter: {self.recruiter_id} to Candidate: {self.candidate_id}"



