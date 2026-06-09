from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from apps.core.permissions import IsAdmin
from .services import JobSeekerDashboardService, RecruiterDashboardService, AdminDashboardService


@extend_schema(tags=["dashboard"])
class JobSeekerDashboardView(APIView):
    """GET /api/v1/dashboard/seeker/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        stats = JobSeekerDashboardService().get_stats(request.user)
        return Response(stats)


@extend_schema(tags=["dashboard"])
class RecruiterDashboardView(APIView):
    """GET /api/v1/dashboard/recruiter/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.recruiter_profile
        except Exception:
            return Response({"detail": "Recruiter profile not found."}, status=404)
        stats = RecruiterDashboardService().get_stats(profile)
        return Response(stats)


@extend_schema(tags=["dashboard"])
class AdminDashboardView(APIView):
    """GET /api/v1/dashboard/admin/  — staff only."""

    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        stats = AdminDashboardService().get_stats()
        return Response(stats)
