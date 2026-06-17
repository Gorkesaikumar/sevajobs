"""Recruiter-side models: Company and RecruiterProfile."""

from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
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


    class InstituteType(models.TextChoices):
        SCHOOL = "school", "School"
        COLLEGE = "college", "College"


    institute_type = models.CharField(max_length=20, choices=InstituteType.choices, default=InstituteType.SCHOOL, db_index=True)
    
    name_regex = RegexValidator(
        regex=r"^[A-Za-z0-9\s\.\-\&,']+$",
        message="Only letters, numbers, spaces, and basic punctuation (.,-&') are allowed."
    )
    

    # College Fields
    college_type = models.CharField(max_length=150, blank=True)
    university_affiliation = models.CharField(max_length=150, blank=True)
    courses_offered = models.CharField(max_length=255, blank=True)
    departments = models.TextField(blank=True)
    director_name = models.CharField(max_length=255, validators=[name_regex], blank=True)
    college_accreditation_details = models.TextField(blank=True)
    naac_grade = models.CharField(max_length=50, blank=True)
    approval_details = models.TextField(blank=True)

    name = models.CharField(max_length=255, validators=[name_regex], unique=True, db_index=True)
    slug = models.SlugField(max_length=280, unique=True)
    logo = models.ImageField(upload_to="company_logos/%Y/%m/", null=True, blank=True)
    founded_year = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1800), MaxValueValidator(2100)],
    )

    # Contact Details
    email = models.EmailField(blank=True)
    phone_regex = RegexValidator(regex=r"^\d{10,15}$", message="Mobile number must be 10-15 digits.")
    phone = models.CharField(max_length=15, validators=[phone_regex], blank=True)
    landline = models.CharField(max_length=20, blank=True)
    
    contact_person_name = models.CharField(max_length=255, validators=[name_regex], blank=True)
    contact_person_designation = models.CharField(max_length=150, blank=True)
    contact_person_mobile = models.CharField(max_length=15, validators=[phone_regex], blank=True)

    # Location Details
    headquarters = models.CharField(max_length=200, blank=True)
    location = models.CharField(max_length=200, blank=True, db_index=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, default="India", blank=True)
    pincode = models.CharField(max_length=20, blank=True)


    # Social and Meta
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
        verbose_name = "Institute"
        verbose_name_plural = "Institutes"

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
