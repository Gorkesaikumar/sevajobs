"""Job-domain models: JobCategory, Skill, Qualification and Job."""

from django.db import models
from django.utils import timezone
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
        FRESHER = "FRESHER", "Fresher (0 Years)"
        ONE_THREE_YEARS = "1_3_YEARS", "1 – 3 Years"
        THREE_SIX_YEARS = "3_6_YEARS", "3 – 6 Years"
        SIX_TEN_YEARS = "6_10_YEARS", "6 – 10 Years"
        TEN_FOURTEEN_YEARS = "10_14_YEARS", "10 – 14 Years"
        FOURTEEN_EIGHTEEN_YEARS = "14_18_YEARS", "14 – 18 Years"
        EIGHTEEN_PLUS_YEARS = "18_PLUS_YEARS", "18+ Years"

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
    benefits = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    location = models.CharField(max_length=200)
    country = models.CharField(max_length=100, default="India")
    state = models.CharField(max_length=100, default="", db_index=True)
    district = models.CharField(max_length=100, default="", db_index=True)
    city = models.CharField(max_length=100, default="", db_index=True)
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
    is_active = models.BooleanField(default=True, db_index=True)

    # --- Walk-in interview fields -------------------------------------------
    is_walkin = models.BooleanField(default=False, db_index=True)
    walkin_start_date = models.DateField(null=True, blank=True, db_index=True)
    walkin_end_date = models.DateField(null=True, blank=True, db_index=True)
    walkin_time = models.CharField(max_length=100, blank=True, help_text="e.g. 10:00 AM - 4:00 PM")
    walkin_venue = models.TextField(blank=True, help_text="Full address/venue for walk-in interview")
    walkin_contact_instructions = models.TextField(blank=True, help_text="Contact person, phone, or specific walk-in instructions")

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

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            import uuid
            company_name = self.company.name if getattr(self, "company", None) else "job"
            base = slugify(f"{self.title}-{company_name}") or "job"
            self.slug = f"{base[:260]}-{str(uuid.uuid4())[:8]}"
        super().save(*args, **kwargs)

    def get_absolute_url(self) -> str:
        from django.urls import reverse
        if self.slug:
            return reverse("core:job-detail", kwargs={"slug": self.slug})
        return reverse("core:job-detail", kwargs={"slug": str(self.id)})

    @property
    def company_name(self) -> str:
        """Safe property returning the company/institution name or empty string."""
        return self.company.name if getattr(self, "company", None) else ""

    @property
    def is_staff_job(self) -> bool:
        return False

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


class ContactVisibilityConfig(BaseModel):
    """
    Singleton-style global configuration for recruiter-contact visibility.

    Only one row is ever used (``id`` is fetched via :meth:`get_solo`). Admins
    update the default visibility window here; per-job overrides live on
    :class:`JobContactVisibility`.
    """

    default_visibility_days = models.PositiveSmallIntegerField(
        default=2,
        help_text="How many days a recruiter's contact details stay public "
                  "after a job is approved & published.",
    )
    is_globally_disabled = models.BooleanField(
        default=False,
        help_text="If true, contact details are never shown publicly regardless of per-job state.",
    )
    updated_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )

    class Meta(BaseModel.Meta):
        verbose_name = "Contact Visibility Config"
        verbose_name_plural = "Contact Visibility Config"

    def __str__(self) -> str:
        return f"ContactVisibilityConfig(default={self.default_visibility_days}d)"

    @classmethod
    def get_solo(cls) -> "ContactVisibilityConfig":
        obj, _ = cls.objects.get_or_create(pk=cls._singleton_pk())
        return obj

    @staticmethod
    def _singleton_pk():
        import uuid
        return uuid.UUID("00000000-0000-0000-0000-000000000001")


class JobContactVisibility(BaseModel):
    """
    Per-job visibility state for the recruiter's contact details.

    Lifecycle:
      * ``AUTO``       — visible until ``expires_at``; flipped to ``HIDDEN``
                         by the scheduled Celery task at expiry.
      * ``SHOW``       — admin override: always visible (ignores expiry).
      * ``HIDE``       — admin override: always hidden.
      * ``HIDDEN``     — automatic state after expiry (no admin involvement).
    """

    class State(models.TextChoices):
        AUTO = "auto", "Auto (visible until expiry)"
        SHOW = "show", "Force show (admin override)"
        HIDE = "hide", "Force hide (admin override)"
        HIDDEN = "hidden", "Hidden (expired)"

    job = models.OneToOneField(
        Job, on_delete=models.CASCADE, related_name="contact_visibility",
    )
    state = models.CharField(
        max_length=10, choices=State.choices, default=State.AUTO, db_index=True,
    )
    expires_at = models.DateTimeField(
        db_index=True,
        help_text="When AUTO state flips to HIDDEN. Ignored for SHOW/HIDE overrides.",
    )
    overridden_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="Admin who last overrode the automatic state.",
    )
    last_changed_at = models.DateTimeField(auto_now=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Job Contact Visibility"
        verbose_name_plural = "Job Contact Visibility"
        indexes = [models.Index(fields=["state", "expires_at"])]

    def __str__(self) -> str:
        return f"{self.job_id} · {self.state}"

    @property
    def is_publicly_visible(self) -> bool:
        if self.state == self.State.SHOW:
            return True
        if self.state in (self.State.HIDE, self.State.HIDDEN):
            return False
        # AUTO
        return timezone.now() < self.expires_at


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


# ===========================================================================
# Table #15 — StaffJob
# ===========================================================================
class StaffJob(BaseModel):
    """
    A job posting created directly by a staff member (table #15).
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        CLOSED = "closed", "Closed"

    job_id = models.CharField(max_length=50, unique=True, db_index=True)
    designation = models.CharField(max_length=255, db_index=True)
    organization_name = models.CharField(max_length=255, db_index=True)
    qualification = models.CharField(max_length=255)
    vacancies = models.PositiveIntegerField(default=1)
    offered_salary = models.PositiveIntegerField(db_index=True)
    job_location = models.CharField(max_length=255, db_index=True)
    country = models.CharField(max_length=100, default="India")
    state = models.CharField(max_length=100, default="", db_index=True)
    district = models.CharField(max_length=100, default="", db_index=True)
    city = models.CharField(max_length=100, default="", db_index=True)
    phone_number = models.CharField(max_length=16)
    email = models.EmailField()
    description = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True
    )
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="staff_jobs"
    )
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Staff Job"
        verbose_name_plural = "Staff Jobs"
        permissions = [
            ("can_create_job", "Can create job"),
            ("can_edit_job", "Can edit job"),
            ("can_close_job", "Can close job"),
        ]

    def __str__(self) -> str:
        return f"{self.designation} at {self.organization_name} ({self.job_id})"

    @property
    def display_location(self) -> str:
        if self.job_location:
            return self.job_location
        if hasattr(self.created_by, "staff_profile"):
            profile = self.created_by.staff_profile
            parts = []
            if profile.city:
                parts.append(profile.city)
            if profile.district and profile.district != profile.city:
                parts.append(profile.district)
            if profile.state:
                parts.append(profile.state)
            if parts:
                return ", ".join(parts)
        parts = []
        if self.city:
            parts.append(self.city)
        if self.district and self.district != self.city:
            parts.append(self.district)
        if self.state:
            parts.append(self.state)
        if parts:
            return ", ".join(parts)
        return ""

    @property
    def is_staff_job(self) -> bool:
        return True
        
    @property
    def is_published(self) -> bool:
        return self.is_active and self.status == self.Status.ACTIVE

    @property
    def created_by_type(self) -> str:
        if self.created_by.role in ["super_admin", "admin"]:
            return "Admin"
        return "Staff"


class JobAssignment(BaseModel):
    """
    Model linking StaffJob, assigned Staff member (User), and assigner (Admin).
    Tracks the status and history of recruitment assignments.
    """
    class Status(models.TextChoices):
        ASSIGNED = "assigned", "Assigned"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        REASSIGNED = "reassigned", "Reassigned"

    job = models.ForeignKey(
        StaffJob,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="assignments"
    )
    recruiter_job = models.ForeignKey(
        "jobs.Job",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="assignments"
    )
    assigned_staff = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="job_assignments"
    )
    assigned_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_jobs_by"
    )
    assigned_date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ASSIGNED,
        db_index=True
    )
    notes = models.TextField(blank=True, default="")

    class Meta(BaseModel.Meta):
        verbose_name = "Job Assignment"
        verbose_name_plural = "Job Assignments"

    def __str__(self) -> str:
        return f"{self.job.designation if self.job else self.recruiter_job.title} assigned to {self.assigned_staff.email}"


# ===========================================================================
# Institution Hiring Requirement & Candidate Matching Models
# ===========================================================================
class InstitutionRequirement(BaseModel):
    """
    Fast requirement submission by schools, colleges, and recruiters (<30 seconds).
    Triggers deterministic candidate matching and enters staff/admin workflow.
    """

    class RequirementStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        UNDER_REVIEW = "under_review", "Under Review"
        ASSIGNED = "assigned", "Assigned"
        IN_PROGRESS = "in_progress", "In Progress"
        MATCHING = "matching", "Matching Candidates"
        CANDIDATES_FOUND = "candidates_found", "Candidates Found"
        JOB_CREATED = "job_created", "Job Created"
        INTERVIEWING = "interviewing", "Interviewing"
        PARTIALLY_FILLED = "partially_filled", "Partially Filled"
        FULFILLED = "fulfilled", "Fulfilled"
        ON_HOLD = "on_hold", "On Hold"
        REJECTED = "rejected", "Rejected"
        CLOSED = "closed", "Closed"

    class TeachingGrade(models.TextChoices):
        PRT = "PRT", "Primary Teacher (PRT)"
        TGT = "TGT", "Trained Graduate Teacher (TGT)"
        PGT = "PGT", "Post Graduate Teacher (PGT)"
        LECTURER = "Lecturer", "Lecturer"
        ASSISTANT_PROFESSOR = "Assistant Professor", "Assistant Professor"
        PROFESSOR = "Professor", "Professor"
        NEET = "NEET", "NEET Faculty"
        JEE = "JEE", "JEE / IIT-JEE Faculty"
        CET = "CET", "CET Faculty"
        FOUNDATION = "Foundation", "Foundation Faculty"
        OTHER = "Other", "Other"

    class Priority(models.TextChoices):
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    recruiter = models.ForeignKey(
        "recruiters.RecruiterProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_requirements",
    )
    company = models.ForeignKey(
        "recruiters.Company",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_requirements",
    )
    posted_by_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="posted_requirements",
    )

    institution_name = models.CharField(max_length=255, db_index=True)
    phone_number = models.CharField(max_length=16, db_index=True)
    subject = models.CharField(max_length=150, db_index=True)
    qualification = models.CharField(max_length=150)
    teaching_grade = models.CharField(
        max_length=50, choices=TeachingGrade.choices, default=TeachingGrade.PRT, db_index=True
    )

    positions_count = models.PositiveIntegerField(default=1)
    location = models.CharField(max_length=200, db_index=True)
    state = models.CharField(max_length=100, default="", blank=True, db_index=True)
    district = models.CharField(max_length=100, default="", blank=True, db_index=True)
    city = models.CharField(max_length=100, default="", blank=True, db_index=True)

    experience_range = models.CharField(max_length=50, blank=True)
    min_experience_years = models.PositiveSmallIntegerField(default=0)
    max_experience_years = models.PositiveSmallIntegerField(null=True, blank=True)

    salary_min = models.PositiveIntegerField(null=True, blank=True)
    salary_max = models.PositiveIntegerField(null=True, blank=True)
    salary_period = models.CharField(
        max_length=20, choices=[("monthly", "Monthly ₹"), ("annual", "Annual LPA ₹")], default="monthly"
    )

    logo = models.ImageField(upload_to="requirement_logos/%Y/%m/", null=True, blank=True)
    status = models.CharField(
        max_length=30, choices=RequirementStatus.choices, default=RequirementStatus.SUBMITTED, db_index=True
    )
    priority = models.CharField(
        max_length=20, choices=Priority.choices, default=Priority.NORMAL, db_index=True
    )

    # Workflow & Assignment links
    assigned_staff = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_institution_requirements",
    )
    assigned_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requirement_assignments_made",
    )
    assigned_at = models.DateTimeField(null=True, blank=True)

    started_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    # Requirement → Job conversion
    converted_job = models.ForeignKey(
        Job,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="origin_requirement",
    )
    converted_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Institution Requirement"
        verbose_name_plural = "Institution Requirements"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["phone_number", "institution_name"]),
        ]

    def __str__(self) -> str:
        return f"{self.subject} ({self.teaching_grade}) at {self.institution_name} [{self.req_code}]"

    @property
    def req_code(self) -> str:
        """Human-readable reference identifier e.g. REQ-2026-8F2A1B."""
        year = self.created_at.year if self.created_at else 2026
        hex_id = str(self.id).replace("-", "")[:6].upper()
        return f"REQ-{year}-{hex_id}"

    @property
    def joined_count(self) -> int:
        """Count of joined candidates derived from requirement matches."""
        return self.candidate_matches.filter(status="joined").count()

    @property
    def is_fulfilled(self) -> bool:
        return self.joined_count >= self.positions_count

    @property
    def grade_level(self) -> str:
        """Alias property returning formatted teaching_grade."""
        return self.get_teaching_grade_display() if hasattr(self, "get_teaching_grade_display") else (self.teaching_grade or "High School")


class RequirementCandidateMatch(BaseModel):
    """
    Match record produced by CandidateMatchingService for an InstitutionRequirement.
    Includes score (0-100), label, and structured match explanations.
    """

    class MatchStatus(models.TextChoices):
        MATCHED = "matched", "Matched"
        SHORTLISTED = "shortlisted", "Shortlisted"
        INTERVIEW_SCHEDULED = "interview_scheduled", "Interview Scheduled"
        SELECTED = "selected", "Selected"
        JOINED = "joined", "Joined"
        REJECTED = "rejected", "Rejected"

    requirement = models.ForeignKey(
        InstitutionRequirement, on_delete=models.CASCADE, related_name="candidate_matches"
    )
    candidate = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="requirement_matches"
    )
    match_score = models.PositiveSmallIntegerField(default=0, db_index=True)
    match_label = models.CharField(max_length=30, default="Partial Match")
    match_reasons = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=30, choices=MatchStatus.choices, default=MatchStatus.MATCHED, db_index=True
    )
    rejection_reason = models.TextField(blank=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Requirement Candidate Match"
        verbose_name_plural = "Requirement Candidate Matches"
        ordering = ["-match_score", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["requirement", "candidate"], name="unique_match_per_req_candidate"),
        ]
        indexes = [
            models.Index(fields=["requirement", "-match_score"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.candidate.email} ({self.match_score}%) for {self.requirement_id}"

    @property
    def allowed_actions(self) -> dict:
        from apps.jobs.requirement_services import RequirementPipelineIntegrationService
        return RequirementPipelineIntegrationService.get_allowed_actions(self)

    @property
    def explanation_list(self) -> list[dict]:
        """
        Parses match_reasons JSON list into structured dict objects for UI template rendering.
        """
        result = []
        for r in (self.match_reasons or []):
            if ":" in r:
                parts = r.lstrip("✓△✕ ").split(":", 1)
                result.append({
                    "label": parts[0].strip(),
                    "value": parts[1].strip(),
                    "status": "matched" if r.startswith("✓") else ("partial" if r.startswith("△") else "unmatched")
                })
        return result

    @property
    def candidate_display_name(self) -> str:
        """Safe display name for candidate."""
        if self.candidate:
            return self.candidate.get_full_name() or self.candidate.email or self.candidate.username
        return "Candidate"

    @property
    def candidate_qualification(self) -> str:
        """Safe qualification fallback."""
        profile = getattr(self.candidate, "job_seeker_profile", None) if self.candidate else None
        q = getattr(profile, "qualification", None) if profile else None
        return q or self.requirement.qualification or "Any"

    @property
    def candidate_experience(self) -> str:
        """Safe experience display fallback."""
        profile = getattr(self.candidate, "job_seeker_profile", None) if self.candidate else None
        if profile and profile.experience_years is not None:
            return f"{profile.experience_years} Years Exp"
        return f"{self.requirement.experience_range or '0+'} Years Exp"

    @property
    def candidate_location(self) -> str:
        """Safe location fallback."""
        profile = getattr(self.candidate, "job_seeker_profile", None) if self.candidate else None
        loc = (getattr(profile, "current_city", None) or getattr(profile, "preferred_location", None)) if profile else None
        return loc or self.requirement.location or "Location Unspecified"


class RequirementActivityLog(BaseModel):
    """
    Structured timeline audit log for an InstitutionRequirement lifecycle.
    """

    class EventType(models.TextChoices):
        SUBMITTED = "submitted", "Requirement Submitted"
        REVIEWED = "reviewed", "Under Review"
        ASSIGNED = "assigned", "Employee Assigned"
        WORK_STARTED = "work_started", "Work Started"
        MATCHING_STARTED = "matching_started", "Matching Started"
        MATCHING_COMPLETED = "matching_completed", "Matching Completed"
        SHORTLISTED = "shortlisted", "Candidate Shortlisted"
        INTERVIEW_SCHEDULED = "interview_scheduled", "Interview Scheduled"
        SELECTED = "selected", "Candidate Selected"
        JOINED = "joined", "Candidate Joined"
        JOB_CONVERTED = "job_converted", "Converted to Job"
        STATUS_CHANGED = "status_changed", "Status Changed"
        NOTE_ADDED = "note_added", "Internal Note Added"
        REJECTED = "rejected", "Requirement Rejected"
        CLOSED = "closed", "Requirement Closed"

    requirement = models.ForeignKey(
        InstitutionRequirement, on_delete=models.CASCADE, related_name="activity_logs"
    )
    actor = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="requirement_activity_actions"
    )
    event_type = models.CharField(max_length=50, choices=EventType.choices, db_index=True)
    description = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Requirement Activity Log"
        verbose_name_plural = "Requirement Activity Logs"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["requirement", "-created_at"])]

    def __str__(self) -> str:
        return f"Activity [{self.event_type}] on {self.requirement_id}"

    @property
    def actor_name(self) -> str:
        """Safe display name for the actor or 'System' if null."""
        if self.actor:
            return self.actor.get_full_name() or self.actor.email or self.actor.username
        return "System"


class RequirementInternalNote(BaseModel):
    """
    Internal recruiter/staff notes attached to an InstitutionRequirement.
    Strictly protected from candidates and non-staff recruiters.
    """

    requirement = models.ForeignKey(
        InstitutionRequirement, on_delete=models.CASCADE, related_name="internal_notes"
    )
    author = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="authored_requirement_internal_notes"
    )
    body = models.TextField()

    class Meta(BaseModel.Meta):
        verbose_name = "Requirement Internal Note"
        verbose_name_plural = "Requirement Internal Notes"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["requirement", "-created_at"])]

    def __str__(self) -> str:
        return f"Note on {self.requirement_id} by {self.author.email if self.author else 'Staff'}"

    @property
    def author_name(self) -> str:
        """Safe display name for the author or 'Staff Member' if null."""
        if self.author:
            return self.author.get_full_name() or self.author.email or self.author.username
        return "Staff Member"



