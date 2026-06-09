from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from apps.core.permissions import IsJobSeeker, IsRecruiter
from apps.jobs.models import Job
from apps.accounts.models import Resume
from .models import JobApplication
from .serializers import (
    ApplicationSerializer, ApplicationSubmitSerializer, ApplicationStatusUpdateSerializer,
)
from .services import ApplicationService

_service = ApplicationService()


@extend_schema(tags=["applications"])
class ApplyView(APIView):
    """POST /api/v1/applications/apply/ — job seeker submits application."""

    permission_classes = [IsAuthenticated, IsJobSeeker]

    def post(self, request):
        serializer = ApplicationSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        job = Job.objects.filter(id=data["job_id"]).first()
        if not job:
            return Response({"detail": "Job not found."}, status=status.HTTP_404_NOT_FOUND)
        resume = Resume.objects.filter(id=data["resume_id"], job_seeker=request.user).first()
        if not resume:
            return Response({"detail": "Resume not found."}, status=status.HTTP_404_NOT_FOUND)

        application = _service.submit(
            job=job,
            applicant=request.user,
            resume=resume,
            cover_letter=data.get("cover_letter", ""),
            expected_salary=data.get("expected_salary"),
        )
        return Response(ApplicationSerializer(application).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["applications"])
class MyApplicationListView(generics.ListAPIView):
    """GET /api/v1/applications/mine/ — applicant's own applications."""

    permission_classes = [IsAuthenticated, IsJobSeeker]
    serializer_class = ApplicationSerializer

    def get_queryset(self):
        return (
            JobApplication.objects
            .filter(applicant=self.request.user)
            .select_related("job", "resume")
            .prefetch_related("history")
        )


@extend_schema(tags=["applications"])
class WithdrawView(APIView):
    """POST /api/v1/applications/<id>/withdraw/"""

    permission_classes = [IsAuthenticated, IsJobSeeker]

    def post(self, request, pk):
        application = JobApplication.objects.filter(id=pk, applicant=request.user).first()
        if not application:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        application = _service.withdraw(application, request.user)
        return Response(ApplicationSerializer(application).data)


@extend_schema(tags=["applications"])
class RecruiterApplicationListView(generics.ListAPIView):
    """GET /api/v1/applications/job/<job_id>/ — recruiter views all applicants."""

    permission_classes = [IsAuthenticated, IsRecruiter]
    serializer_class = ApplicationSerializer

    def get_queryset(self):
        return (
            JobApplication.objects
            .filter(job__recruiter__user=self.request.user, job_id=self.kwargs["job_id"])
            .select_related("applicant", "job", "resume")
            .prefetch_related("history")
        )


@extend_schema(tags=["applications"])
class RecruiterApplicationStatusView(APIView):
    """PATCH /api/v1/applications/<id>/status/ — recruiter moves a candidate."""

    permission_classes = [IsAuthenticated, IsRecruiter]

    def patch(self, request, pk):
        application = JobApplication.objects.filter(
            id=pk, job__recruiter__user=request.user
        ).select_related("job", "applicant").first()
        if not application:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = ApplicationStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        application = _service.move_status(
            application,
            new_status=data["status"],
            changed_by=request.user,
            note=data.get("note", ""),
            interview_at=data.get("interview_at"),
            interview_mode=data.get("interview_mode", ""),
            interview_location=data.get("interview_location", ""),
        )
        return Response(ApplicationSerializer(application).data)


@extend_schema(tags=["applications"])
class JobPipelineView(APIView):
    """
    GET /api/v1/applications/job/<job_id>/pipeline/ — ATS board summary.

    Returns the count of applications in each stage for one of the recruiter's
    jobs, ready to render as a Kanban pipeline.
    """

    permission_classes = [IsAuthenticated, IsRecruiter]

    def get(self, request, job_id):
        from django.db.models import Count

        qs = JobApplication.objects.filter(
            job_id=job_id, job__recruiter__user=request.user
        )
        counts = {row["status"]: row["n"] for row in qs.values("status").annotate(n=Count("id"))}
        stages = [
            {"status": value, "label": label, "count": counts.get(value, 0)}
            for value, label in JobApplication.Status.choices
        ]
        return Response({"job_id": str(job_id), "total": qs.count(), "stages": stages})
