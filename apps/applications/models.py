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
        SELECTED = "selected", "Selected"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"

    #: Terminal states — no further recruiter transitions allowed.
    TERMINAL_STATUSES = {Status.SELECTED, Status.REJECTED, Status.WITHDRAWN}

    class InterviewMode(models.TextChoices):
        ONSITE = "onsite", "On-site"
        VIDEO = "video", "Video Call"
        PHONE = "phone", "Phone"

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
