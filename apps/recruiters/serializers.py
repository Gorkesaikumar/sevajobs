"""Serializers for the recruiter management module."""

from __future__ import annotations

from rest_framework import serializers

from apps.accounts.models import JobSeekerProfile
from .models import Company, RecruiterProfile


# ---------------------------------------------------------------------------
# Company
# ---------------------------------------------------------------------------
class CompanySerializer(serializers.ModelSerializer):
    open_jobs_count = serializers.SerializerMethodField()

    class Meta:
        model = Company
        fields = [
            "id", "name", "slug", "logo", "website", "description",
            "industry", "size", "founded_year", "headquarters", "location",
            "email", "phone", "landline", "linkedin_url", "twitter_url",
            "current_requirements", "number_of_openings",
            "is_verified", "open_jobs_count", "created_at",
        ]
        read_only_fields = ["id", "slug", "is_verified", "created_at"]

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
    email = serializers.EmailField(source="user.email", read_only=True)
    phone = serializers.CharField(source="user.phone", read_only=True)
    skills = serializers.SlugRelatedField(slug_field="name", many=True, read_only=True)
    qualifications = serializers.SlugRelatedField(slug_field="name", many=True, read_only=True)
    primary_resume = serializers.SerializerMethodField()

    class Meta:
        model = JobSeekerProfile
        fields = [
            "id", "name", "email", "phone", "headline", "designation",
            "subject", "experience_years", "current_location", "preferred_location",
            "availability", "preferred_job_type", "expected_salary",
            "is_open_to_work", "skills", "qualifications", "primary_resume",
        ]

    def get_primary_resume(self, obj) -> str | None:
        resume = obj.user.resumes.filter(is_primary=True).first() or obj.user.resumes.first()
        if not resume or not resume.file:
            return None
        request = self.context.get("request")
        url = resume.file.url
        return request.build_absolute_uri(url) if request else url
