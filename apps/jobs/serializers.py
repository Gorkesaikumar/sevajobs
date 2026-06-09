from rest_framework import serializers

from apps.core.models import ActivityLog
from .models import Job, JobCategory, Skill, Qualification, JobApprovalHistory


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
    skills_required = SkillSerializer(many=True, read_only=True)
    preferred_qualifications = QualificationSerializer(many=True, read_only=True)
    minimum_qualification = QualificationSerializer(read_only=True)

    class Meta(JobListSerializer.Meta):
        fields = JobListSerializer.Meta.fields + [
            "description", "responsibilities", "requirements", "benefits",
            "skills_required", "preferred_qualifications", "minimum_qualification",
            "rejection_reason",
        ]


class JobWriteSerializer(serializers.ModelSerializer):
    """
    Recruiter-editable fields only. Lifecycle fields (status, approval_status,
    is_featured, published_at, …) are mutated through dedicated action endpoints,
    never by direct write.
    """

    class Meta:
        model = Job
        fields = [
            "title", "description", "responsibilities", "requirements", "benefits",
            "category", "skills_required", "preferred_qualifications", "minimum_qualification",
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


class AuditLogSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True, default=None)

    class Meta:
        model = ActivityLog
        fields = [
            "id", "user_email", "action", "entity_type", "entity_id",
            "description", "metadata", "ip_address", "created_at",
        ]
