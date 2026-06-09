"""Job-domain models: JobCategory, Skill, Qualification and Job."""

from django.db import models
from apps.core.models import BaseModel


# ===========================================================================
# Table #5 — JobCategory
# ===========================================================================
class JobCategory(BaseModel):
    """
    Hierarchical job taxonomy (table #5).

    Supports one level of nesting via the self-referential `parent` FK
    (e.g. "Engineering" → "Backend Engineering").
    """

    name = models.CharField(max_length=120, unique=True, db_index=True)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.TextField(blank=True)
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subcategories",
    )
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Job Category"
        verbose_name_plural = "Job Categories"

    def __str__(self) -> str:
        return self.name


# ===========================================================================
# Table #10 — Skill
# ===========================================================================
class Skill(BaseModel):
    """
    Catalog of skills (table #10).

    Shared many-to-many with both JobSeekerProfile (skills a candidate has)
    and Job (skills a role requires).
    """

    class Category(models.TextChoices):
        TECHNICAL = "technical", "Technical"
        SOFT = "soft", "Soft Skill"
        LANGUAGE = "language", "Language"
        TOOL = "tool", "Tool / Platform"

    name = models.CharField(max_length=100, unique=True, db_index=True)
    slug = models.SlugField(max_length=120, unique=True)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.TECHNICAL)
    is_active = models.BooleanField(default=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Skill"
        verbose_name_plural = "Skills"

    def __str__(self) -> str:
        return self.name


# ===========================================================================
# Table #11 — Qualification
# ===========================================================================
class Qualification(BaseModel):
    """
    Catalog of academic qualifications (table #11).

    Used both as a candidate's held qualifications and as a job's minimum /
    preferred qualification.
    """

    class Level(models.IntegerChoices):
        HIGH_SCHOOL = 1, "High School"
        DIPLOMA = 2, "Diploma"
        BACHELOR = 3, "Bachelor's Degree"
        MASTER = 4, "Master's Degree"
        DOCTORATE = 5, "Doctorate"

    name = models.CharField(max_length=150, unique=True, db_index=True)
    slug = models.SlugField(max_length=170, unique=True)
    level = models.PositiveSmallIntegerField(choices=Level.choices, db_index=True)
    is_active = models.BooleanField(default=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Qualification"
        verbose_name_plural = "Qualifications"
        ordering = ["level", "name"]

    def __str__(self) -> str:
        return self.name


# ===========================================================================
# Table #6 — Job
# ===========================================================================
class Job(BaseModel):
    """
    A job posting (table #6).

    Belongs to a RecruiterProfile and a Company. Requires a set of Skills and
    references catalog Qualifications. Salary and experience ranges are guarded
    by check constraints.
    """

    class JobType(models.TextChoices):
        FULL_TIME = "full_time", "Full Time"
        PART_TIME = "part_time", "Part Time"
        CONTRACT = "contract", "Contract"
        FREELANCE = "freelance", "Freelance"
        INTERNSHIP = "internship", "Internship"

    class ExperienceLevel(models.TextChoices):
        FRESHER = "fresher", "Fresher"
        JUNIOR = "junior", "Junior (1–3 yrs)"
        MID = "mid", "Mid (3–6 yrs)"
        SENIOR = "senior", "Senior (6+ yrs)"
        LEAD = "lead", "Lead / Principal"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        CLOSED = "closed", "Closed"
        EXPIRED = "expired", "Expired"

    class ApprovalStatus(models.TextChoices):
        PENDING = "pending", "Pending Review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    class Segment(models.TextChoices):
        TEACHING = "teaching", "Teaching"
        HEALTHCARE = "healthcare", "Healthcare"
        MANUFACTURING = "manufacturing", "Manufacturing"
        REAL_ESTATE = "real_estate", "Real Estate"
        IT = "it", "Information Technology"
        OTHER = "other", "Other"

    recruiter = models.ForeignKey(
        "recruiters.RecruiterProfile",
        on_delete=models.CASCADE,
        related_name="jobs",
    )
    company = models.ForeignKey(
        "recruiters.Company",
        on_delete=models.CASCADE,
        related_name="jobs",
    )
    segment = models.CharField(max_length=50, choices=Segment.choices, default=Segment.OTHER, db_index=True)
    category = models.ForeignKey(
        JobCategory, on_delete=models.SET_NULL, null=True, related_name="jobs"
    )
    skills_required = models.ManyToManyField(Skill, blank=True, related_name="jobs")
    preferred_qualifications = models.ManyToManyField(
        Qualification, blank=True, related_name="jobs"
    )
    minimum_qualification = models.ForeignKey(
        Qualification,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="jobs_as_minimum",
    )

    title = models.CharField(max_length=255, db_index=True)
    slug = models.SlugField(max_length=280, unique=True, db_index=True)
    description = models.TextField()
    responsibilities = models.TextField(blank=True)
    requirements = models.TextField(blank=True)
    benefits = models.TextField(blank=True)

    location = models.CharField(max_length=200)
    is_remote = models.BooleanField(default=False, db_index=True)
    job_type = models.CharField(max_length=20, choices=JobType.choices, default=JobType.FULL_TIME, db_index=True)
    experience_level = models.CharField(max_length=20, choices=ExperienceLevel.choices, db_index=True)
    min_experience_years = models.PositiveSmallIntegerField(default=0)
    max_experience_years = models.PositiveSmallIntegerField(null=True, blank=True)

    salary_min = models.PositiveIntegerField(null=True, blank=True)
    salary_max = models.PositiveIntegerField(null=True, blank=True)
    salary_currency = models.CharField(max_length=3, default="INR")
    salary_is_disclosed = models.BooleanField(default=True)

    vacancies = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    deadline = models.DateField(null=True, blank=True, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)
    views_count = models.PositiveIntegerField(default=0)
    applications_count = models.PositiveIntegerField(default=0)

    # --- Approval workflow (admin-moderated) -------------------------------
    approval_status = models.CharField(
        max_length=10, choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING, db_index=True,
    )
    rejection_reason = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reviewed_jobs",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    # --- Featured placement (admin-controlled) -----------------------------
    is_featured = models.BooleanField(default=False, db_index=True)
    featured_until = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Job"
        verbose_name_plural = "Jobs"
        indexes = [
            models.Index(fields=["status", "deadline"]),
            models.Index(fields=["job_type", "experience_level"]),
            models.Index(fields=["company", "status"]),
            models.Index(fields=["status", "approval_status"]),
            models.Index(fields=["is_featured", "featured_until"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(salary_min__isnull=True)
                    | models.Q(salary_max__isnull=True)
                    | models.Q(salary_max__gte=models.F("salary_min"))
                ),
                name="job_salary_max_gte_min",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(max_experience_years__isnull=True)
                    | models.Q(max_experience_years__gte=models.F("min_experience_years"))
                ),
                name="job_experience_max_gte_min",
            ),
        ]

    def __str__(self) -> str:
        return self.title

    # ----- derived state ---------------------------------------------------
    @property
    def is_expired(self) -> bool:
        from django.utils import timezone

        return bool(self.deadline and self.deadline < timezone.now().date())

    @property
    def is_approved(self) -> bool:
        return self.approval_status == self.ApprovalStatus.APPROVED

    @property
    def is_published(self) -> bool:
        """Visible on the public board: active, approved, and not past its deadline."""
        return self.status == self.Status.ACTIVE and self.is_approved and not self.is_expired

    @property
    def is_currently_featured(self) -> bool:
        from django.utils import timezone

        if not self.is_featured:
            return False
        return self.featured_until is None or self.featured_until >= timezone.now()


class JobApprovalHistory(BaseModel):
    """
    Append-only record of every approval decision on a job.

    Distinct from the global ``core.ActivityLog`` (system-wide audit): this is a
    focused, per-job moderation trail that recruiters and admins can read back.
    """

    class Action(models.TextChoices):
        SUBMITTED = "submitted", "Submitted for Review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="approval_history")
    action = models.CharField(max_length=12, choices=Action.choices, db_index=True)
    actor = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, related_name="job_approval_actions"
    )
    comment = models.TextField(blank=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Job Approval History"
        verbose_name_plural = "Job Approval History"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["job", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.job_id} · {self.action}"
