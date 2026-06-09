"""Serializers for the job-seeker module."""

from __future__ import annotations

from rest_framework import serializers

from apps.jobs.models import Skill, Qualification, Job
from apps.applications.models import SavedJob
from .models import JobSeekerProfile, Resume, phone_validator


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------
class ResumeSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()
    preview_url = serializers.SerializerMethodField()

    class Meta:
        model = Resume
        fields = [
            "id", "title", "file", "file_size", "file_type",
            "is_primary", "download_url", "preview_url", "created_at",
        ]
        read_only_fields = ["id", "file_size", "file_type", "created_at"]

    def _url(self, obj, name: str) -> str | None:
        request = self.context.get("request")
        from django.urls import reverse

        path = reverse(name, kwargs={"pk": obj.pk})
        return request.build_absolute_uri(path) if request else path

    def get_download_url(self, obj) -> str | None:
        return self._url(obj, "seeker:resume-download")

    def get_preview_url(self, obj) -> str | None:
        return self._url(obj, "seeker:resume-preview")


class ResumeUploadSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=150)
    file = serializers.FileField()
    is_primary = serializers.BooleanField(required=False, default=False)


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------
class _SkillBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Skill
        fields = ["id", "name"]


class _QualificationBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Qualification
        fields = ["id", "name", "level"]


class JobSeekerProfileSerializer(serializers.ModelSerializer):
    """Read representation, including computed completion and contact fields."""

    name = serializers.CharField(source="user.full_name", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    phone = serializers.CharField(source="user.phone", read_only=True)
    skills = _SkillBriefSerializer(many=True, read_only=True)
    qualifications = _QualificationBriefSerializer(many=True, read_only=True)
    profile_completion = serializers.IntegerField(read_only=True)
    resume_count = serializers.SerializerMethodField()

    class Meta:
        model = JobSeekerProfile
        fields = [
            "id", "name", "email", "phone", "alternate_phone",
            "headline", "summary", "date_of_birth", "gender",
            "subject", "designation", "preferred_job_type",
            "experience_years", "current_salary", "expected_salary",
            "availability", "city", "state", "country",
            "current_location", "preferred_location",
            "linkedin_url", "portfolio_url", "github_url",
            "is_open_to_work", "skills", "qualifications",
            "profile_completion", "resume_count", "created_at", "updated_at",
        ]

    def get_resume_count(self, obj) -> int:
        return obj.user.resumes.count()


class JobSeekerProfileWriteSerializer(serializers.ModelSerializer):
    """Writable profile fields plus pass-through to a few User fields."""

    first_name = serializers.CharField(source="user.first_name", required=False)
    last_name = serializers.CharField(source="user.last_name", required=False)
    phone = serializers.CharField(
        source="user.phone", required=False, allow_blank=True, validators=[phone_validator]
    )
    skills = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Skill.objects.all(), required=False
    )
    qualifications = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Qualification.objects.all(), required=False
    )

    class Meta:
        model = JobSeekerProfile
        fields = [
            "first_name", "last_name", "phone", "alternate_phone",
            "headline", "summary", "date_of_birth", "gender",
            "subject", "designation", "preferred_job_type",
            "experience_years", "current_salary", "expected_salary",
            "availability", "city", "state", "country",
            "current_location", "preferred_location",
            "linkedin_url", "portfolio_url", "github_url",
            "is_open_to_work", "skills", "qualifications",
        ]

    def to_internal_value(self, data):
        validated = super().to_internal_value(data)
        # Split the nested "user" payload back out for the service layer.
        validated["_user_fields"] = validated.pop("user", {})
        return validated


# ---------------------------------------------------------------------------
# Saved jobs
# ---------------------------------------------------------------------------
class _JobBriefSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source="company.name", read_only=True)

    class Meta:
        model = Job
        fields = ["id", "title", "slug", "company_name", "location", "job_type", "status"]


class SavedJobSerializer(serializers.ModelSerializer):
    job = _JobBriefSerializer(read_only=True)

    class Meta:
        model = SavedJob
        fields = ["id", "job", "created_at"]


class SaveJobRequestSerializer(serializers.Serializer):
    job_id = serializers.UUIDField()
