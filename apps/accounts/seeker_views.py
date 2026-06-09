"""API views for the job-seeker module."""

from __future__ import annotations

import mimetypes

from django.http import FileResponse, Http404
from rest_framework import generics, status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from apps.applications.models import JobApplication, SavedJob
from apps.applications.serializers import ApplicationSerializer
from apps.jobs.models import Job
from .permissions import IsJobSeeker
from .models import Resume
from .seeker_serializers import (
    JobSeekerProfileSerializer,
    JobSeekerProfileWriteSerializer,
    ResumeSerializer,
    ResumeUploadSerializer,
    SavedJobSerializer,
    SaveJobRequestSerializer,
)
from .seeker_services import ProfileService, ResumeService

_profiles = ProfileService()
_resumes = ResumeService()

_SEEKER = [IsAuthenticated, IsJobSeeker]


# ---------------------------------------------------------------------------
# Profile + completion %
# ---------------------------------------------------------------------------
@extend_schema(tags=["job-seeker"])
class SeekerProfileView(APIView):
    """GET/PATCH /api/v1/seeker/profile/ — the current seeker's profile."""

    permission_classes = _SEEKER

    def get(self, request):
        profile = _profiles.get_or_create(request.user)
        return Response(JobSeekerProfileSerializer(profile, context={"request": request}).data)

    def patch(self, request):
        profile = _profiles.get_or_create(request.user)
        serializer = JobSeekerProfileWriteSerializer(
            profile, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        user_fields = data.pop("_user_fields", {})
        skills = data.pop("skills", None)
        qualifications = data.pop("qualifications", None)
        profile = _profiles.update(
            profile,
            user_fields=user_fields,
            profile_fields=data,
            skills=skills,
            qualifications=qualifications,
        )
        return Response(JobSeekerProfileSerializer(profile, context={"request": request}).data)


# ---------------------------------------------------------------------------
# Resumes — list / upload / detail / delete / set-primary
# ---------------------------------------------------------------------------
@extend_schema(tags=["job-seeker"])
class ResumeListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/v1/seeker/resumes/"""

    permission_classes = _SEEKER
    parser_classes = [MultiPartParser, FormParser]

    def get_serializer_class(self):
        return ResumeUploadSerializer if self.request.method == "POST" else ResumeSerializer

    def get_queryset(self):
        return _resumes.list_for(self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = ResumeUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        resume = _resumes.upload(
            request.user,
            title=serializer.validated_data["title"],
            file=serializer.validated_data["file"],
            is_primary=serializer.validated_data.get("is_primary", False),
        )
        return Response(
            ResumeSerializer(resume, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(tags=["job-seeker"])
class ResumeDetailView(generics.RetrieveDestroyAPIView):
    """GET/DELETE /api/v1/seeker/resumes/<pk>/"""

    permission_classes = _SEEKER
    serializer_class = ResumeSerializer
    lookup_field = "pk"

    def get_queryset(self):
        return Resume.objects.filter(job_seeker=self.request.user)

    def perform_destroy(self, instance):
        _resumes.delete(instance)


@extend_schema(tags=["job-seeker"])
class ResumeSetPrimaryView(APIView):
    """POST /api/v1/seeker/resumes/<pk>/set-primary/"""

    permission_classes = _SEEKER

    def post(self, request, pk):
        resume = Resume.objects.filter(pk=pk, job_seeker=request.user).first()
        if not resume:
            raise Http404
        _resumes.set_primary(resume)
        return Response(ResumeSerializer(resume, context={"request": request}).data)


class _BaseResumeFileView(APIView):
    """Shared ownership lookup + file streaming for preview/download."""

    permission_classes = _SEEKER
    as_attachment = False

    def get(self, request, pk):
        resume = Resume.objects.filter(pk=pk, job_seeker=request.user).first()
        if not resume or not resume.file:
            raise Http404
        content_type = mimetypes.guess_type(resume.file.name)[0] or "application/octet-stream"
        filename = f"{resume.title}.{resume.file_type}" if resume.file_type else resume.title
        return FileResponse(
            resume.file.open("rb"),
            as_attachment=self.as_attachment,
            filename=filename,
            content_type=content_type,
        )


@extend_schema(tags=["job-seeker"])
class ResumePreviewView(_BaseResumeFileView):
    """GET /api/v1/seeker/resumes/<pk>/preview/ — inline (in-browser) view."""

    as_attachment = False


@extend_schema(tags=["job-seeker"])
class ResumeDownloadView(_BaseResumeFileView):
    """GET /api/v1/seeker/resumes/<pk>/download/ — force download."""

    as_attachment = True


# ---------------------------------------------------------------------------
# Saved jobs
# ---------------------------------------------------------------------------
@extend_schema(tags=["job-seeker"])
class SavedJobListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/v1/seeker/saved-jobs/"""

    permission_classes = _SEEKER
    serializer_class = SavedJobSerializer

    def get_queryset(self):
        return (
            SavedJob.objects.filter(user=self.request.user)
            .select_related("job", "job__company")
            .order_by("-created_at")
        )

    def create(self, request, *args, **kwargs):
        serializer = SaveJobRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        job = Job.objects.filter(id=serializer.validated_data["job_id"]).first()
        if not job:
            return Response({"detail": "Job not found."}, status=status.HTTP_404_NOT_FOUND)
        saved, created = SavedJob.objects.get_or_create(user=request.user, job=job)
        return Response(
            SavedJobSerializer(saved).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


@extend_schema(tags=["job-seeker"])
class SavedJobDeleteView(APIView):
    """DELETE /api/v1/seeker/saved-jobs/<job_id>/ — remove a bookmark."""

    permission_classes = _SEEKER

    def delete(self, request, job_id):
        deleted, _ = SavedJob.objects.filter(user=request.user, job_id=job_id).delete()
        if not deleted:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Applied jobs history
# ---------------------------------------------------------------------------
@extend_schema(tags=["job-seeker"])
class AppliedJobsView(generics.ListAPIView):
    """GET /api/v1/seeker/applied-jobs/ — full application history."""

    permission_classes = _SEEKER
    serializer_class = ApplicationSerializer
    filterset_fields = ["status"]
    ordering_fields = ["applied_at"]
    ordering = ["-applied_at"]

    def get_queryset(self):
        return (
            JobApplication.objects.filter(applicant=self.request.user)
            .select_related("job", "job__company", "resume")
            .prefetch_related("history")
        )
