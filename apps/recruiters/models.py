"""Recruiter-side models: Company and RecruiterProfile."""

from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from apps.core.models import BaseModel


# ===========================================================================
# Table #4 — Company
# ===========================================================================
class Company(BaseModel):
    """
    An employer organisation (table #4).

    One company can have many recruiter accounts and many jobs. Splitting the
    company out of RecruiterProfile lets multiple recruiters share a single
    verified brand.
    """

    class Size(models.TextChoices):
        STARTUP = "1-10", "Startup (1–10)"
        SMALL = "11-50", "Small (11–50)"
        MEDIUM = "51-200", "Medium (51–200)"
        LARGE = "201-1000", "Large (201–1000)"
        ENTERPRISE = "1000+", "Enterprise (1000+)"

    name = models.CharField(max_length=255, unique=True, db_index=True)
    slug = models.SlugField(max_length=280, unique=True)
    logo = models.ImageField(upload_to="company_logos/%Y/%m/", null=True, blank=True)
    website = models.URLField(blank=True)
    description = models.TextField(blank=True)
    industry = models.CharField(max_length=120, blank=True, db_index=True)
    size = models.CharField(max_length=10, choices=Size.choices, blank=True)
    founded_year = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1800), MaxValueValidator(2100)],
    )
    headquarters = models.CharField(max_length=200, blank=True)
    location = models.CharField(max_length=200, blank=True, db_index=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=15, blank=True)
    landline = models.CharField(max_length=20, blank=True)
    linkedin_url = models.URLField(blank=True)
    twitter_url = models.URLField(blank=True)
    current_requirements = models.TextField(
        blank=True, help_text="Free-text summary of active hiring needs."
    )
    number_of_openings = models.PositiveIntegerField(
        default=0, help_text="Declared total open positions across the company."
    )
    is_verified = models.BooleanField(default=False, db_index=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Company"
        verbose_name_plural = "Companies"

    def __str__(self) -> str:
        return self.name


# ===========================================================================
# Table #3 — RecruiterProfile
# ===========================================================================
class RecruiterProfile(BaseModel):
    """
    Extended profile for users whose role is `recruiter` (table #3).

    One-to-one with User, many-to-one with Company.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="recruiter_profile",
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="recruiters",
    )
    designation = models.CharField(max_length=150, blank=True, help_text="e.g. 'HR Manager'.")
    phone = models.CharField(max_length=15, blank=True)
    is_primary_contact = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False, db_index=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Recruiter Profile"
        verbose_name_plural = "Recruiter Profiles"

    def __str__(self) -> str:
        return f"{self.user.full_name} @ {self.company.name}"
