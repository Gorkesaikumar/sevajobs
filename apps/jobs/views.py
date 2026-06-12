from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from apps.core.models import ActivityLog
from apps.core.permissions import IsRecruiter
from apps.accounts.permissions import IsAdmin
from .filters import JobFilter
from .models import (
    Job, JobCategory, Skill, Qualification, JobApprovalHistory,
    JobContactVisibility, ContactVisibilityConfig,
)
from .repository import JobRepository
from .serializers import (
    JobListSerializer, JobDetailSerializer, JobWriteSerializer,
    JobCategorySerializer, SkillSerializer, QualificationSerializer,
    JobRejectSerializer, JobFeatureSerializer,
    JobApprovalHistorySerializer, AuditLogSerializer,
    JobContactVisibilitySerializer, VisibilityOverrideSerializer,
    ContactVisibilityConfigSerializer,
)
from .services import JobService
from .visibility_services import ContactVisibilityService

_service = JobService()


def _client_ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


@extend_schema(tags=["jobs"])
class JobListView(generics.ListAPIView):
    """GET /api/v1/jobs/ — public job board."""

    permission_classes = [AllowAny]
    serializer_class = JobListSerializer
    filterset_class = JobFilter
    search_fields = ["title", "description", "location"]
    ordering_fields = ["created_at", "salary_min", "deadline"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return JobRepository.get_active().distinct()


@extend_schema(tags=["jobs"])
class JobDetailView(generics.RetrieveAPIView):
    """GET /api/v1/jobs/<id>/ — public job detail."""

    permission_classes = [AllowAny]
    serializer_class = JobDetailSerializer
    lookup_field = "id"

    def get_queryset(self):
        return JobRepository._base_qs()

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        _service.record_view(instance.id)
        return Response(self.get_serializer(instance).data)


@extend_schema(tags=["jobs"])
class RecruiterJobListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/v1/jobs/mine/ — recruiter's own listings."""

    permission_classes = [IsAuthenticated, IsRecruiter]
    filterset_fields = ["status", "approval_status", "is_featured"]
    search_fields = ["title", "location"]
    ordering_fields = ["created_at", "published_at", "deadline"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        return JobWriteSerializer if self.request.method == "POST" else JobListSerializer

    def get_queryset(self):
        return JobRepository.get_by_recruiter(self.request.user.recruiter_profile.id)

    def perform_create(self, serializer):
        _service.create_job(self.request.user.recruiter_profile, serializer.validated_data)


@extend_schema(tags=["jobs"])
class RecruiterJobDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/v1/jobs/mine/<id>/"""

    permission_classes = [IsAuthenticated, IsRecruiter]
    serializer_class = JobWriteSerializer
    lookup_field = "id"

    def get_queryset(self):
        return JobRepository.get_by_recruiter(self.request.user.recruiter_profile.id)

    def perform_update(self, serializer):
        _service.update_job(self.get_object(), self.request.user.recruiter_profile, serializer.validated_data)


@extend_schema(tags=["jobs"])
class JobCategoryListView(generics.ListAPIView):
    """GET /api/v1/jobs/categories/"""

    permission_classes = [AllowAny]
    serializer_class = JobCategorySerializer
    queryset = JobCategory.objects.filter(is_active=True)
    pagination_class = None


@extend_schema(tags=["jobs"])
class SkillListView(generics.ListAPIView):
    """GET /api/v1/jobs/skills/"""

    permission_classes = [AllowAny]
    serializer_class = SkillSerializer
    queryset = Skill.objects.filter(is_active=True)
    search_fields = ["name"]


@extend_schema(tags=["jobs"])
class QualificationListView(generics.ListAPIView):
    """GET /api/v1/jobs/qualifications/"""

    permission_classes = [AllowAny]
    serializer_class = QualificationSerializer
    queryset = Qualification.objects.filter(is_active=True)


@extend_schema(tags=["jobs"])
class RecruiterJobPublishView(APIView):
    """POST /api/v1/jobs/mine/<id>/publish/ — move a draft/paused job to active."""

    permission_classes = [IsAuthenticated, IsRecruiter]

    def post(self, request, id):
        job = JobRepository.get_by_recruiter(request.user.recruiter_profile.id).filter(id=id).first()
        if not job:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        job = _service.publish_job(job, request.user.recruiter_profile)
        return Response(JobDetailSerializer(job).data)


@extend_schema(tags=["jobs"])
class RecruiterJobCloseView(APIView):
    """POST /api/v1/jobs/mine/<id>/close/ — close a job to new applications."""

    permission_classes = [IsAuthenticated, IsRecruiter]

    def post(self, request, id):
        job = JobRepository.get_by_recruiter(request.user.recruiter_profile.id).filter(id=id).first()
        if not job:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        job = _service.close_job(job, request.user.recruiter_profile)
        return Response(JobDetailSerializer(job).data)


class _RecruiterJobActionMixin:
    """Shared owner-scoped job lookup for recruiter action endpoints."""

    permission_classes = [IsAuthenticated, IsRecruiter]

    def _get_owned_job(self, request, job_id):
        return JobRepository.get_by_recruiter(request.user.recruiter_profile.id).filter(id=job_id).first()


@extend_schema(tags=["jobs"])
class RecruiterJobCloneView(_RecruiterJobActionMixin, APIView):
    """POST /api/v1/jobs/mine/<id>/clone/ — duplicate a job as a new draft."""

    def post(self, request, id):
        job = self._get_owned_job(request, id)
        if not job:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        clone = _service.clone_job(job, request.user.recruiter_profile)
        return Response(JobDetailSerializer(clone).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["jobs"])
class RecruiterJobSubmitView(_RecruiterJobActionMixin, APIView):
    """POST /api/v1/jobs/mine/<id>/submit/ — submit a draft for admin approval."""

    def post(self, request, id):
        job = self._get_owned_job(request, id)
        if not job:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        job = _service.submit_for_approval(job, request.user.recruiter_profile, ip=_client_ip(request))
        return Response(JobDetailSerializer(job).data)


@extend_schema(tags=["jobs"])
class FeaturedJobsView(generics.ListAPIView):
    """GET /api/v1/jobs/featured/ — public list of currently featured jobs."""

    permission_classes = [AllowAny]
    serializer_class = JobListSerializer
    pagination_class = None

    def get_queryset(self):
        return JobRepository.get_featured()


# ===========================================================================
# Admin approval workflow + featuring
# ===========================================================================
@extend_schema(tags=["jobs"])
class AdminPendingJobsView(generics.ListAPIView):
    """GET /api/v1/jobs/admin/pending/ — jobs awaiting approval."""

    permission_classes = [IsAuthenticated, IsAdmin]
    serializer_class = JobListSerializer

    def get_queryset(self):
        return JobRepository.get_pending_approval()


class _AdminJobActionMixin:
    permission_classes = [IsAuthenticated, IsAdmin]

    def _get_job(self, job_id):
        return Job.objects.filter(id=job_id).first()


@extend_schema(tags=["jobs"])
class AdminApproveJobView(_AdminJobActionMixin, APIView):
    """POST /api/v1/jobs/admin/<id>/approve/ — approve (and publish) a job."""

    def post(self, request, id):
        job = self._get_job(id)
        if not job:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        job = _service.approve_job(job, request.user, ip=_client_ip(request))
        return Response(JobDetailSerializer(job).data)


@extend_schema(tags=["jobs"])
class AdminRejectJobView(_AdminJobActionMixin, APIView):
    """POST /api/v1/jobs/admin/<id>/reject/ — reject a job with a reason."""

    def post(self, request, id):
        job = self._get_job(id)
        if not job:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = JobRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        job = _service.reject_job(
            job, request.user, serializer.validated_data["reason"], ip=_client_ip(request)
        )
        return Response(JobDetailSerializer(job).data)


@extend_schema(tags=["jobs"])
class AdminFeatureJobView(_AdminJobActionMixin, APIView):
    """POST /api/v1/jobs/admin/<id>/feature/ — toggle featured placement."""

    def post(self, request, id):
        job = self._get_job(id)
        if not job:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = JobFeatureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        job = _service.set_featured(
            job,
            featured=serializer.validated_data["featured"],
            featured_until=serializer.validated_data.get("featured_until"),
        )
        return Response(JobDetailSerializer(job).data)


@extend_schema(tags=["jobs"])
class JobApprovalHistoryView(generics.ListAPIView):
    """
    GET /api/v1/jobs/<id>/approval-history/

    Readable by an admin or by the recruiter who owns the job.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = JobApprovalHistorySerializer
    pagination_class = None

    def get_queryset(self):
        job = Job.objects.filter(id=self.kwargs["id"]).select_related("recruiter").first()
        if not job:
            return JobApprovalHistory.objects.none()
        user = self.request.user
        is_owner = job.recruiter and job.recruiter.user_id == user.id
        if not (user.is_staff or user.role == "admin" or is_owner):
            return JobApprovalHistory.objects.none()
        return job.approval_history.select_related("actor")


@extend_schema(tags=["jobs"])
class AdminAuditLogView(generics.ListAPIView):
    """GET /api/v1/jobs/admin/audit/ — system audit trail for job moderation."""

    permission_classes = [IsAuthenticated, IsAdmin]
    serializer_class = AuditLogSerializer
    filterset_fields = ["action", "entity_type"]

    def get_queryset(self):
        return ActivityLog.objects.filter(entity_type="Job").select_related("user")


# ===========================================================================
# Admin: recruiter-contact visibility controls
# ===========================================================================
_visibility = ContactVisibilityService()


@extend_schema(tags=["jobs"])
class AdminContactVisibilityListView(generics.ListAPIView):
    """GET /api/v1/jobs/admin/contact-visibility/ — every job's visibility state."""

    permission_classes = [IsAuthenticated, IsAdmin]
    serializer_class = JobContactVisibilitySerializer
    filterset_fields = ["state"]
    ordering_fields = ["expires_at", "last_changed_at"]
    ordering = ["-last_changed_at"]

    def get_queryset(self):
        return (
            JobContactVisibility.objects
            .select_related("job", "overridden_by")
            .all()
        )


class _AdminVisibilityActionMixin:
    permission_classes = [IsAuthenticated, IsAdmin]

    def _get_job(self, job_id):
        return Job.objects.filter(id=job_id).first()


@extend_schema(tags=["jobs"])
class AdminContactShowView(_AdminVisibilityActionMixin, APIView):
    """POST /api/v1/jobs/admin/<id>/contact/show/ — force contact visible."""

    def post(self, request, id):
        job = self._get_job(id)
        if not job:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = VisibilityOverrideSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vis = _visibility.force_show(
            job, request.user,
            reason=serializer.validated_data.get("reason", ""),
            ip=_client_ip(request),
        )
        return Response(JobContactVisibilitySerializer(vis).data)


@extend_schema(tags=["jobs"])
class AdminContactHideView(_AdminVisibilityActionMixin, APIView):
    """POST /api/v1/jobs/admin/<id>/contact/hide/ — force contact hidden."""

    def post(self, request, id):
        job = self._get_job(id)
        if not job:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = VisibilityOverrideSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vis = _visibility.force_hide(
            job, request.user,
            reason=serializer.validated_data.get("reason", ""),
            ip=_client_ip(request),
        )
        return Response(JobContactVisibilitySerializer(vis).data)


@extend_schema(tags=["jobs"])
class AdminContactResetView(_AdminVisibilityActionMixin, APIView):
    """POST /api/v1/jobs/admin/<id>/contact/reset/ — clear override, restore AUTO."""

    def post(self, request, id):
        job = self._get_job(id)
        if not job:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        vis = _visibility.reset_to_auto(job, request.user, ip=_client_ip(request))
        return Response(JobContactVisibilitySerializer(vis).data)


@extend_schema(tags=["jobs"])
class AdminContactVisibilityConfigView(APIView):
    """GET/PATCH /api/v1/jobs/admin/contact-visibility/config/ — global config."""

    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        config = ContactVisibilityConfig.get_solo()
        return Response(ContactVisibilityConfigSerializer(config).data)

    def patch(self, request):
        serializer = ContactVisibilityConfigSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        config = _visibility.configure_global(
            request.user,
            default_visibility_days=serializer.validated_data.get("default_visibility_days"),
            is_globally_disabled=serializer.validated_data.get("is_globally_disabled"),
            ip=_client_ip(request),
        )
        return Response(ContactVisibilityConfigSerializer(config).data)
