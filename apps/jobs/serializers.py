from rest_framework import serializers

from apps.core.models import ActivityLog
from .models import (
    Job, JobCategory, Skill, Qualification, JobApprovalHistory,
    JobContactVisibility, ContactVisibilityConfig,
)


class JobCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = JobCategory
        fields = ["id", "name", "slug", "description", "parent", "is_active"]


class SkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = Skill
        fields = ["id", "name", "slug", "category", "is_active"]


class QualificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Qualification
        fields = ["id", "name", "slug", "level", "is_active"]


class JobListSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    company_name = serializers.CharField(source="company.name", read_only=True)
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = Job
        fields = [
            "id", "title", "slug", "location", "is_remote",
            "job_type", "experience_level", "min_experience_years", "max_experience_years",
            "salary_min", "salary_max", "salary_currency", "salary_is_disclosed",
            "vacancies", "status", "approval_status", "is_featured", "is_expired",
            "deadline", "published_at", "views_count", "applications_count",
            "category_name", "company_name", "created_at",
        ]


class JobDetailSerializer(JobListSerializer):
    preferred_qualifications = QualificationSerializer(many=True, read_only=True)
    minimum_qualification = QualificationSerializer(read_only=True)
    recruiter_contact = serializers.SerializerMethodField()
    contact_visibility = serializers.SerializerMethodField()

    class Meta(JobListSerializer.Meta):
        fields = JobListSerializer.Meta.fields + [
            "description", "responsibilities", "benefits",
            "preferred_qualifications", "minimum_qualification",
            "rejection_reason", "recruiter_contact", "contact_visibility",
        ]

    def get_recruiter_contact(self, job) -> dict | None:
        """Return recruiter contact details only when policy permits."""
        from .visibility_services import ContactVisibilityService

        viewer = getattr(self.context.get("request"), "user", None)
        if not ContactVisibilityService.is_visible_for(job, viewer=viewer):
            return None
        recruiter = job.recruiter
        if not recruiter:
            return None
        user = recruiter.user
        return {
            "name": user.full_name,
            "email": user.email,
            "phone": recruiter.phone or user.phone or "",
        }

    def get_contact_visibility(self, job) -> dict:
        """Public status hint so the UI can show 'contact hidden after Day 2'."""
        vis = getattr(job, "contact_visibility", None)
        if vis is None:
            return {"state": "unknown", "is_publicly_visible": False, "expires_at": None}
        return {
            "state": vis.state,
            "is_publicly_visible": vis.is_publicly_visible,
            "expires_at": vis.expires_at,
        }


class JobWriteSerializer(serializers.ModelSerializer):
    """
    Recruiter-editable fields only. Lifecycle fields (status, approval_status,
    is_featured, published_at, …) are mutated through dedicated action endpoints,
    never by direct write.
    """

    class Meta:
        model = Job
        fields = [
            "title", "description", "responsibilities", "benefits",
            "category", "preferred_qualifications", "minimum_qualification",
            "location", "is_remote", "job_type", "experience_level",
            "min_experience_years", "max_experience_years",
            "salary_min", "salary_max", "salary_currency", "salary_is_disclosed",
            "vacancies", "deadline",
        ]

    def validate(self, attrs):
        smin, smax = attrs.get("salary_min"), attrs.get("salary_max")
        if smin is not None and smax is not None and smax < smin:
            raise serializers.ValidationError({"salary_max": "Must be greater than or equal to salary_min."})
        emin = attrs.get("min_experience_years")
        emax = attrs.get("max_experience_years")
        if emin is not None and emax is not None and emax < emin:
            raise serializers.ValidationError(
                {"max_experience_years": "Must be greater than or equal to min_experience_years."}
            )
        return attrs


# ---------------------------------------------------------------------------
# Admin workflow / featured action serializers
# ---------------------------------------------------------------------------
class JobRejectSerializer(serializers.Serializer):
    reason = serializers.CharField()

    def validate_reason(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("A rejection comment is required.")
        return value


class JobFeatureSerializer(serializers.Serializer):
    featured = serializers.BooleanField(default=True)
    featured_until = serializers.DateTimeField(required=False, allow_null=True)


class JobApprovalHistorySerializer(serializers.ModelSerializer):
    action_display = serializers.CharField(source="get_action_display", read_only=True)
    actor_name = serializers.CharField(source="actor.full_name", read_only=True, default=None)

    class Meta:
        model = JobApprovalHistory
        fields = ["id", "action", "action_display", "actor_name", "comment", "created_at"]


class JobContactVisibilitySerializer(serializers.ModelSerializer):
    """Admin read view of a job's contact visibility state."""

    job_title = serializers.CharField(source="job.title", read_only=True)
    state_display = serializers.CharField(source="get_state_display", read_only=True)
    overridden_by_email = serializers.EmailField(source="overridden_by.email", read_only=True, default=None)
    is_publicly_visible = serializers.BooleanField(read_only=True)

    class Meta:
        model = JobContactVisibility
        fields = [
            "id", "job", "job_title", "state", "state_display",
            "expires_at", "is_publicly_visible",
            "overridden_by_email", "last_changed_at", "created_at",
        ]
        read_only_fields = fields


class VisibilityOverrideSerializer(serializers.Serializer):
    """Body for force-show / force-hide admin actions."""

    reason = serializers.CharField(required=False, allow_blank=True)


class ContactVisibilityConfigSerializer(serializers.ModelSerializer):
    updated_by_email = serializers.EmailField(source="updated_by.email", read_only=True, default=None)

    class Meta:
        model = ContactVisibilityConfig
        fields = [
            "id", "default_visibility_days", "is_globally_disabled",
            "updated_by_email", "updated_at",
        ]
        read_only_fields = ["id", "updated_by_email", "updated_at"]

    def validate_default_visibility_days(self, value: int) -> int:
        if not 1 <= value <= 60:
            raise serializers.ValidationError("Must be between 1 and 60 days.")
        return value


class AuditLogSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True, default=None)

    class Meta:
        model = ActivityLog
        fields = [
            "id", "user_email", "action", "entity_type", "entity_id",
            "description", "metadata", "ip_address", "created_at",
        ]
