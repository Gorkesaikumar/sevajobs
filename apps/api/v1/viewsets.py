"""
Consolidated v1 ViewSets for the SevaJobs platform.

Conventions (REST best practices):
* JWT auth + session auth (configured globally in settings).
* Pagination, DjangoFilterBackend, SearchFilter and OrderingFilter are applied
  globally; each ViewSet declares its own filterset / search / ordering fields.
* ``lookup_value_regex`` is constrained to a UUID so these routes never shadow
  the action sub-paths (``/mine/``, ``/admin/`` …) served by the domain apps.
"""

from __future__ import annotations

from django.utils import timezone
from rest_framework import viewsets, mixins, status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

# Models
from apps.jobs.models import JobCategory, Skill, Qualification
from apps.recruiters.models import Company
from apps.advertisements.models import Advertisement
from apps.notifications.models import Notification
from apps.applications.models import JobApplication

# Read serializers (reused from the domain apps)
from apps.jobs.serializers import (
    JobListSerializer, JobDetailSerializer,
    JobCategorySerializer, SkillSerializer, QualificationSerializer,
)
from apps.recruiters.serializers import CompanySerializer
from apps.advertisements.serializers import AdvertisementSerializer
from apps.notifications.serializers import NotificationSerializer
from apps.applications.serializers import ApplicationSerializer

# Write serializers (catalog slugs)
from .serializers import (
    JobCategoryWriteSerializer, SkillWriteSerializer, QualificationWriteSerializer,
)
from .permissions import IsAdminOrReadOnly, IsRecipient

from apps.jobs.repository import JobRepository
from apps.jobs.services import JobService

UUID_REGEX = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

_job_service = JobService()


# ---------------------------------------------------------------------------
# Catalog resources (admin-managed, publicly readable) — full CRUD
# ---------------------------------------------------------------------------
class JobCategoryViewSet(viewsets.ModelViewSet):
    queryset = JobCategory.objects.all().order_by("name")
    permission_classes = [IsAdminOrReadOnly]
    lookup_value_regex = UUID_REGEX
    filterset_fields = ["is_active", "parent"]
    search_fields = ["name", "description"]
    ordering_fields = ["name", "created_at"]

    def get_serializer_class(self):
        return JobCategorySerializer if self.request.method in ("GET",) else JobCategoryWriteSerializer


class SkillViewSet(viewsets.ModelViewSet):
    queryset = Skill.objects.all().order_by("name")
    permission_classes = [IsAdminOrReadOnly]
    lookup_value_regex = UUID_REGEX
    filterset_fields = ["category", "is_active"]
    search_fields = ["name"]
    ordering_fields = ["name", "created_at"]

    def get_serializer_class(self):
        return SkillSerializer if self.request.method in ("GET",) else SkillWriteSerializer


class QualificationViewSet(viewsets.ModelViewSet):
    queryset = Qualification.objects.all().order_by("level", "name")
    permission_classes = [IsAdminOrReadOnly]
    lookup_value_regex = UUID_REGEX
    filterset_fields = ["level", "is_active"]
    search_fields = ["name"]
    ordering_fields = ["level", "name"]

    def get_serializer_class(self):
        return QualificationSerializer if self.request.method in ("GET",) else QualificationWriteSerializer


# ---------------------------------------------------------------------------
# Jobs — public read (writes go through the curated recruiter workflow)
# ---------------------------------------------------------------------------
class JobViewSet(viewsets.ReadOnlyModelViewSet):
    """Browse the public job board with full filtering/search/ordering."""

    permission_classes = [AllowAny]
    lookup_field = "id"
    lookup_value_regex = UUID_REGEX
    search_fields = ["title", "description", "location"]
    ordering_fields = ["created_at", "published_at", "salary_min", "deadline"]
    ordering = ["-created_at"]

    # Imported lazily to avoid a hard import cycle at module load.
    from apps.jobs.filters import JobFilter as filterset_class  # type: ignore

    def get_queryset(self):
        return JobRepository.get_active().distinct()

    def get_serializer_class(self):
        return JobDetailSerializer if self.action == "retrieve" else JobListSerializer

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        _job_service.record_view(instance.id)
        return Response(self.get_serializer(instance).data)

    @action(detail=False, methods=["get"], permission_classes=[AllowAny])
    def featured(self, request):
        page = self.paginate_queryset(JobRepository.get_featured())
        serializer = JobListSerializer(page, many=True, context={"request": request})
        return self.get_paginated_response(serializer.data)


# ---------------------------------------------------------------------------
# Companies — public read of verified employers
# ---------------------------------------------------------------------------
class CompanyViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CompanySerializer
    permission_classes = [AllowAny]
    lookup_field = "id"
    lookup_value_regex = UUID_REGEX
    filterset_fields = ["industry", "size"]
    search_fields = ["name", "industry", "location", "headquarters"]
    ordering_fields = ["name", "created_at"]

    def get_queryset(self):
        return Company.objects.filter(is_verified=True).order_by("name")


# ---------------------------------------------------------------------------
# Advertisements — public read of currently-live ads
# ---------------------------------------------------------------------------
class AdvertisementViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AdvertisementSerializer
    permission_classes = [AllowAny]
    lookup_field = "id"
    lookup_value_regex = UUID_REGEX
    filterset_fields = ["placement"]
    ordering_fields = ["created_at", "starts_at"]

    def get_queryset(self):
        now = timezone.now()
        return Advertisement.objects.filter(
            status=Advertisement.Status.ACTIVE, starts_at__lte=now, ends_at__gte=now
        )


# ---------------------------------------------------------------------------
# Applications — read-only, scoped to the requesting user's role
# ---------------------------------------------------------------------------
class ApplicationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ApplicationSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "id"
    lookup_value_regex = UUID_REGEX
    filterset_fields = ["status", "job"]
    ordering_fields = ["applied_at"]
    ordering = ["-applied_at"]

    def get_queryset(self):
        user = self.request.user
        base = JobApplication.objects.select_related("job", "applicant", "resume").prefetch_related("history")
        if user.is_staff or user.role == "admin":
            return base
        if user.role == "recruiter":
            return base.filter(job__recruiter__user=user)
        return base.filter(applicant=user)


# ---------------------------------------------------------------------------
# Notifications — list/retrieve own + mark-read actions
# ---------------------------------------------------------------------------
class NotificationViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated, IsRecipient]
    lookup_field = "id"
    lookup_value_regex = UUID_REGEX
    filterset_fields = ["is_read", "notification_type"]
    ordering_fields = ["created_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user)

    @action(detail=True, methods=["post"], url_path="read")
    def mark_read(self, request, id=None):
        notification = self.get_object()
        notification.mark_read()
        return Response(self.get_serializer(notification).data)

    @action(detail=False, methods=["post"], url_path="read-all")
    def mark_all_read(self, request):
        updated = self.get_queryset().filter(is_read=False).update(
            is_read=True, read_at=timezone.now()
        )
        return Response({"marked_read": updated}, status=status.HTTP_200_OK)
