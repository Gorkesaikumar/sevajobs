"""Account-related models: custom User, JobSeekerProfile and Resume."""

import uuid
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
import secrets
from datetime import timedelta

from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
from django.db import models
from django.utils import timezone
from apps.core.models import BaseModel, TimeStampedModel

phone_validator = RegexValidator(
    regex=r"^\+?[1-9]\d{7,14}$",
    message="Enter a valid phone number in E.164 format, e.g. +919876543210.",
)


# ===========================================================================
# Table #1 — Users
# ===========================================================================
class UserManager(BaseUserManager):
    """Custom manager — email is the unique identifier, not username."""

    def create_user(self, email: str, password: str | None = None, **extra_fields) -> "User":
        if not email:
            raise ValueError("Email address is required.")
        email = self.normalize_email(email)
        extra_fields.setdefault("is_active", True)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str, **extra_fields) -> "User":
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.ADMIN)
        if not extra_fields.get("is_staff"):
            raise ValueError("Superuser must have is_staff=True.")
        if not extra_fields.get("is_superuser"):
            raise ValueError("Superuser must have is_superuser=True.")
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    """
    Project-wide user (table #1).

    * UUID pk prevents ID-enumeration attacks.
    * `email` is the login identifier and is globally unique.
    * `role` drives every permission gate in the application.
    """

    class Role(models.TextChoices):
        JOB_SEEKER = "job_seeker", "Job Seeker"
        RECRUITER = "recruiter", "Recruiter"
        ADMIN = "admin", "Admin"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, db_index=True)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.JOB_SEEKER, db_index=True)
    phone = models.CharField(
        max_length=16,
        unique=True,
        null=True,
        blank=True,
        validators=[phone_validator],
        help_text="E.164 format. Unique — used as an alternate login identifier.",
    )
    avatar = models.ImageField(upload_to="avatars/%Y/%m/", null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_email_verified = models.BooleanField(default=False)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    date_joined = models.DateTimeField(default=timezone.now)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    objects = UserManager()

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ["-date_joined"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=["job_seeker", "recruiter", "admin"]),
                name="user_role_valid",
            ),
        ]

    def __str__(self) -> str:
        return self.email

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_job_seeker(self) -> bool:
        return self.role == self.Role.JOB_SEEKER

    @property
    def is_recruiter(self) -> bool:
        return self.role == self.Role.RECRUITER

    @property
    def is_admin_role(self) -> bool:
        return self.role == self.Role.ADMIN


# ===========================================================================
# Table #2 — JobSeekerProfile
# ===========================================================================
class JobSeekerProfile(BaseModel):
    """
    Extended profile for users whose role is `job_seeker` (table #2).

    One-to-one with User. Holds the data a recruiter needs to evaluate a
    candidate. Skills and qualifications are many-to-many catalogs shared
    with the Job model.
    """

    class Gender(models.TextChoices):
        MALE = "male", "Male"
        FEMALE = "female", "Female"
        OTHER = "other", "Other"
        UNDISCLOSED = "undisclosed", "Prefer not to say"

    class Availability(models.TextChoices):
        IMMEDIATE = "immediate", "Immediately Available"
        FIFTEEN_DAYS = "15_days", "15 Days Notice"
        THIRTY_DAYS = "30_days", "30 Days Notice"
        SIXTY_DAYS = "60_days", "60 Days Notice"
        NOT_AVAILABLE = "not_available", "Not Available"

    class JobType(models.TextChoices):
        FULL_TIME = "full_time", "Full Time"
        PART_TIME = "part_time", "Part Time"
        CONTRACT = "contract", "Contract"
        FREELANCE = "freelance", "Freelance"
        INTERNSHIP = "internship", "Internship"

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="job_seeker_profile",
    )
    headline = models.CharField(max_length=255, blank=True, help_text="e.g. 'Senior Python Developer'.")
    summary = models.TextField(blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=15, choices=Gender.choices, blank=True)

    # Contact (name/email/phone live on User; this is the secondary number)
    alternate_phone = models.CharField(
        max_length=16, blank=True, validators=[phone_validator]
    )

    # Education & role
    subject = models.CharField(
        max_length=150, blank=True, help_text="Primary field of study, e.g. 'Computer Science'."
    )
    designation = models.CharField(
        max_length=150, blank=True, help_text="Current or most recent job title."
    )
    preferred_job_type = models.CharField(
        max_length=20, choices=JobType.choices, blank=True, db_index=True
    )

    city = models.CharField(max_length=120, blank=True)
    district = models.CharField(max_length=120, blank=True)
    taluka = models.CharField(max_length=120, blank=True)
    state = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=120, blank=True, default="India")
    current_location = models.CharField(max_length=200, blank=True, db_index=True)
    preferred_location = models.CharField(max_length=200, blank=True, db_index=True)

    experience_years = models.PositiveSmallIntegerField(
        default=0, validators=[MaxValueValidator(60)]
    )
    current_salary = models.PositiveIntegerField(null=True, blank=True)
    expected_salary = models.PositiveIntegerField(null=True, blank=True)
    availability = models.CharField(
        max_length=15, choices=Availability.choices, default=Availability.IMMEDIATE, db_index=True
    )

    linkedin_url = models.URLField(blank=True)
    portfolio_url = models.URLField(blank=True)
    github_url = models.URLField(blank=True)

    is_open_to_work = models.BooleanField(default=True, db_index=True)

    # Shared catalogs (defined in the jobs app)
    skills = models.ManyToManyField("jobs.Skill", blank=True, related_name="job_seekers")
    qualifications = models.ManyToManyField("jobs.Qualification", blank=True, related_name="job_seekers")

    #: Fields that count toward the profile-completion score. Each weighs equally.
    COMPLETION_FIELDS = (
        "headline", "summary", "designation", "subject",
        "current_location", "preferred_location", "preferred_job_type",
        "experience_years", "expected_salary",
    )

    class Meta(BaseModel.Meta):
        verbose_name = "Job Seeker Profile"
        verbose_name_plural = "Job Seeker Profiles"

    def __str__(self) -> str:
        return f"{self.user.full_name} — Seeker Profile"

    @property
    def profile_completion(self) -> int:
        """
        Percentage (0–100) of the profile that is filled in.
        Based on the 4 core steps: Account Created, Profile Exists, Resume Uploaded, Skills Added.
        """
        # Step 1: Account created (always True if they have an account)
        steps_completed = 1
        
        if self.pk:
            # Step 2: Personal details added (Profile exists)
            steps_completed += 1
            
            # Step 3: Resume uploaded
            if self.user.resumes.exists():
                steps_completed += 1
                
            # Step 4: Skills & experience added
            if self.skills.exists() or self.experience_years > 0:
                steps_completed += 1
                
        return int((steps_completed / 4) * 100)

    @property
    def skills_list(self) -> str:
        """Returns a comma-separated string of the seeker's skills."""
        if not self.pk:
            return ""
        return ",".join(self.skills.values_list("name", flat=True))


# ===========================================================================
# Table #8 — Resume
# ===========================================================================
class Resume(BaseModel):
    """
    A reusable resume document owned by a job seeker (table #8).

    A seeker may store several resumes and pick one when applying. Exactly one
    may be flagged `is_primary` — enforced by a partial unique constraint.
    """

    job_seeker = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="resumes",
        limit_choices_to={"role": User.Role.JOB_SEEKER},
    )
    title = models.CharField(max_length=150)
    file = models.FileField(upload_to="resumes/%Y/%m/")
    is_primary = models.BooleanField(default=False)
    parsed_text = models.TextField(blank=True, help_text="Extracted text for full-text search.")
    file_size = models.PositiveIntegerField(default=0, help_text="Size in bytes.")
    file_type = models.CharField(max_length=20, blank=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Resume"
        verbose_name_plural = "Resumes"
        constraints = [
            models.UniqueConstraint(
                fields=["job_seeker"],
                condition=models.Q(is_primary=True),
                name="unique_primary_resume_per_seeker",
            ),
        ]
        indexes = [models.Index(fields=["job_seeker", "is_primary"])]

    def __str__(self) -> str:
        return f"{self.title} ({self.job_seeker.email})"


# ===========================================================================
# Single-use security tokens (email verification & password reset)
# ===========================================================================
class BaseToken(BaseModel):
    """
    Abstract single-use, time-limited token.

    The raw token value is generated with :func:`secrets.token_urlsafe` and is
    high-entropy, so it can be stored and looked up directly. Tokens are
    single-use (``used_at``) and expire (``expires_at``).
    """

    #: Default validity window in hours — overridden per concrete subclass.
    DEFAULT_TTL_HOURS: int = 24

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    token = models.CharField(max_length=128, unique=True, db_index=True, editable=False)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]

    @classmethod
    def issue(cls, user: "User", ttl_hours: int | None = None, **extra) -> "BaseToken":
        """Create and persist a fresh token for ``user``."""
        ttl = ttl_hours if ttl_hours is not None else cls.DEFAULT_TTL_HOURS
        return cls.objects.create(
            user=user,
            token=secrets.token_urlsafe(48),
            expires_at=timezone.now() + timedelta(hours=ttl),
            **extra,
        )

    @property
    def is_used(self) -> bool:
        return self.used_at is not None

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    def is_valid(self) -> bool:
        return not self.is_used and not self.is_expired

    def consume(self) -> None:
        """Mark the token as used so it cannot be replayed."""
        self.used_at = timezone.now()
        self.save(update_fields=["used_at"])


class EmailVerificationToken(BaseToken):
    """Confirms ownership of a user's email address."""

    DEFAULT_TTL_HOURS = 48

    class Meta(BaseToken.Meta):
        verbose_name = "Email Verification Token"
        verbose_name_plural = "Email Verification Tokens"

    def __str__(self) -> str:
        return f"EmailVerification<{self.user.email}>"


class PasswordResetToken(BaseToken):
    """Authorizes a password reset without the current password."""

    DEFAULT_TTL_HOURS = 2

    requested_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta(BaseToken.Meta):
        verbose_name = "Password Reset Token"
        verbose_name_plural = "Password Reset Tokens"

    def __str__(self) -> str:
        return f"PasswordReset<{self.user.email}>"
