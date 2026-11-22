"""Serializers for the recruiter management module."""

from __future__ import annotations

from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

from apps.accounts.models import JobSeekerProfile
from .models import Company, RecruiterProfile


# ---------------------------------------------------------------------------
# Company
# ---------------------------------------------------------------------------
class CompanySerializer(serializers.ModelSerializer):
    open_jobs_count = serializers.SerializerMethodField()
    industry = serializers.CharField(read_only=True, default="Education")
    size = serializers.CharField(read_only=True, default="", allow_blank=True)
    website = serializers.CharField(read_only=True, default="", allow_blank=True)
    description = serializers.CharField(read_only=True, default="", allow_blank=True)

    class Meta:
        model = Company
        fields = [
            "id", "name", "slug", "logo", "website", "description",
            "industry", "size", "founded_year", "headquarters", "location",
            "email", "phone", "landline", "linkedin_url", "twitter_url",
            "current_requirements", "number_of_openings",
            "is_verified", "open_jobs_count", "created_at",
            "institute_type", "college_type", "university_affiliation",
            "courses_offered", "departments", "director_name",
            "address", "city", "state", "country", "pincode",
        ]
        read_only_fields = ["id", "slug", "is_verified", "created_at"]

    @extend_schema_field(serializers.IntegerField())
    def get_open_jobs_count(self, obj) -> int:
        return obj.jobs.filter(status="active").count()


class CompanyWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        exclude = ["id", "slug", "is_verified", "created_at", "updated_at"]


# ---------------------------------------------------------------------------
# Recruiter profile
# ---------------------------------------------------------------------------
class RecruiterProfileSerializer(serializers.ModelSerializer):
    company = CompanySerializer(read_only=True)
    recruiter_name = serializers.CharField(source="user.full_name", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = RecruiterProfile
        fields = [
            "id", "recruiter_name", "email", "company", "designation",
            "phone", "is_primary_contact", "is_verified", "created_at",
        ]
        read_only_fields = ["id", "is_verified", "created_at"]


class RecruiterProfileWriteSerializer(serializers.ModelSerializer):
    company_id = serializers.UUIDField(write_only=True)

    class Meta:
        model = RecruiterProfile
        fields = ["company_id", "designation", "phone", "is_primary_contact"]


# ---------------------------------------------------------------------------
# Candidate search (recruiter-facing view of seeker profiles)
# ---------------------------------------------------------------------------
class CandidateSearchSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="user.full_name", read_only=True)
    user_id = serializers.UUIDField(source="user.id", read_only=True)
    email = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    skills = serializers.SlugRelatedField(slug_field="name", many=True, read_only=True)
    qualifications = serializers.SlugRelatedField(slug_field="name", many=True, read_only=True)
    primary_resume = serializers.SerializerMethodField()
    is_unlocked = serializers.SerializerMethodField()
    is_contacted = serializers.SerializerMethodField()

    class Meta:
        model = JobSeekerProfile
        fields = [
            "id", "user_id", "name", "email", "phone", "headline", "designation",
            "subject", "experience_years", "current_location", "preferred_location",
            "availability", "preferred_job_type", "expected_salary",
            "is_open_to_work", "skills", "qualifications", "primary_resume",
            "is_unlocked", "is_contacted",
        ]

    def _get_company(self):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return None
        profile = getattr(request.user, "recruiter_profile", None)
        return profile.company if profile else None

    def _get_unlock(self, obj):
        if not hasattr(obj, "_cached_unlock"):
            company = self._get_company()
            if company:
                from apps.billing.services import BillingEntitlementService
                obj._cached_unlock = BillingEntitlementService.get_candidate_unlock_record(company, obj.user)
            else:
                obj._cached_unlock = None
        return obj._cached_unlock

    def get_is_unlocked(self, obj) -> bool:
        return self._get_unlock(obj) is not None

    def get_is_contacted(self, obj) -> bool:
        unlock = self._get_unlock(obj)
        return unlock.is_contacted if unlock else False

    def get_email(self, obj) -> str:
        from apps.billing.services import BillingEntitlementService
        raw_email = getattr(obj.user, "email", "")
        if self.get_is_unlocked(obj):
            return raw_email
        return BillingEntitlementService.mask_email(raw_email)

    def get_phone(self, obj) -> str:
        from apps.billing.services import BillingEntitlementService
        raw_phone = getattr(obj.user, "phone", "")
        if self.get_is_unlocked(obj):
            return raw_phone
        return BillingEntitlementService.mask_phone(raw_phone)

    def get_primary_resume(self, obj) -> str | None:
        if not self.get_is_unlocked(obj):
            return None
        resume = obj.user.resumes.filter(is_primary=True).first() or obj.user.resumes.first()
        if not resume or not resume.file:
            return None
        request = self.context.get("request")
        url = resume.file.url
        return request.build_absolute_uri(url) if request else url
