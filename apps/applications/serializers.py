from rest_framework import serializers
from .models import JobApplication, ApplicationStatusHistory


class ApplicationSubmitSerializer(serializers.Serializer):
    job_id = serializers.UUIDField()
    resume_id = serializers.UUIDField()
    cover_letter = serializers.CharField(required=False, allow_blank=True)
    expected_salary = serializers.IntegerField(required=False, min_value=0)


class ApplicationStatusUpdateSerializer(serializers.Serializer):
    """Recruiter moves a candidate to a new pipeline stage."""

    status = serializers.ChoiceField(choices=JobApplication.Status.choices)
    note = serializers.CharField(required=False, allow_blank=True)
    # Required only when status == interview_scheduled (validated in the service).
    interview_at = serializers.DateTimeField(required=False)
    interview_mode = serializers.ChoiceField(
        choices=JobApplication.InterviewMode.choices, required=False, allow_blank=True
    )
    interview_location = serializers.CharField(required=False, allow_blank=True)


class ApplicationStatusHistorySerializer(serializers.ModelSerializer):
    from_status_display = serializers.SerializerMethodField()
    to_status_display = serializers.SerializerMethodField()
    changed_by_name = serializers.CharField(source="changed_by.full_name", read_only=True, default=None)

    class Meta:
        model = ApplicationStatusHistory
        fields = [
            "id", "from_status", "from_status_display",
            "to_status", "to_status_display",
            "changed_by_name", "note", "created_at",
        ]

    def _label(self, value):
        return dict(JobApplication.Status.choices).get(value, value)

    def get_from_status_display(self, obj):
        return self._label(obj.from_status) if obj.from_status else None

    def get_to_status_display(self, obj):
        return self._label(obj.to_status)


class ApplicationSerializer(serializers.ModelSerializer):
    job_title = serializers.CharField(source="job.title", read_only=True)
    applicant_name = serializers.CharField(source="applicant.full_name", read_only=True)
    applicant_email = serializers.EmailField(source="applicant.email", read_only=True)
    resume_title = serializers.CharField(source="resume.title", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    interview_mode_display = serializers.CharField(source="get_interview_mode_display", read_only=True)
    history = ApplicationStatusHistorySerializer(many=True, read_only=True)

    class Meta:
        model = JobApplication
        fields = [
            "id", "job_title", "applicant_name", "applicant_email", "resume_title",
            "cover_letter", "expected_salary",
            "status", "status_display", "recruiter_notes",
            "interview_at", "interview_mode", "interview_mode_display", "interview_location",
            "applied_at", "history",
        ]
        read_only_fields = ["id", "applied_at"]
