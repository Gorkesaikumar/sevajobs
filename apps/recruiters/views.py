from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from apps.accounts.models import JobSeekerProfile, User
from apps.accounts.permissions import IsRecruiter
from apps.applications.models import JobApplication
from apps.applications.serializers import ApplicationSerializer
from apps.dashboard.services import RecruiterDashboardService
from .filters import CandidateFilter
from .models import Company, RecruiterProfile
from .serializers import (
    CompanySerializer, CompanyWriteSerializer,
    RecruiterProfileSerializer, RecruiterProfileWriteSerializer,
    CandidateSearchSerializer,
)
from .services import CompanyService, RecruiterService

_company_service = CompanyService()
_recruiter_service = RecruiterService()


def _recruiter_profile_or_none(user):
    return getattr(user, "recruiter_profile", None)


@extend_schema(tags=["recruiters"])
class CompanyListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/v1/recruiters/companies/"""

    search_fields = ["name", "industry", "headquarters"]
    ordering_fields = ["name", "created_at"]

    def get_permissions(self):
        return [AllowAny()] if self.request.method == "GET" else [IsAuthenticated()]

    def get_serializer_class(self):
        return CompanyWriteSerializer if self.request.method == "POST" else CompanySerializer

    def get_queryset(self):
        qs = Company.objects.all()
        if self.request.method == "GET":
            qs = qs.filter(is_verified=True)
        return qs

    def perform_create(self, serializer):
        _company_service.create(serializer.validated_data)


@extend_schema(tags=["recruiters"])
class RecruiterProfileView(APIView):
    """GET/POST/PATCH /api/v1/recruiters/profile/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.recruiter_profile
        except RecruiterProfile.DoesNotExist:
            return Response({"detail": "Profile not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(RecruiterProfileSerializer(profile).data)

    def post(self, request):
        serializer = RecruiterProfileWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = _recruiter_service.create_profile(request.user, serializer.validated_data)
        return Response(RecruiterProfileSerializer(profile).data, status=status.HTTP_201_CREATED)

    def patch(self, request):
        profile = request.user.recruiter_profile
        serializer = RecruiterProfileWriteSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        profile = _recruiter_service.update_profile(profile, serializer.validated_data)
        return Response(RecruiterProfileSerializer(profile).data)


# ===========================================================================
# Feature: Institute Profile (manage the recruiter's own company)
# ===========================================================================
@extend_schema(tags=["recruiters"])
class MyCompanyView(APIView):
    """GET/PATCH /api/v1/recruiters/my-company/ — the recruiter's own company."""

    permission_classes = [IsAuthenticated, IsRecruiter]

    def _get_company(self, request):
        profile = _recruiter_profile_or_none(request.user)
        return profile.company if profile else None

    def get(self, request):
        company = self._get_company(request)
        if company is None:
            return Response({"detail": "No company linked to your profile."}, status=404)
        return Response(CompanySerializer(company, context={"request": request}).data)

    def patch(self, request):
        company = self._get_company(request)
        if company is None:
            return Response({"detail": "No company linked to your profile."}, status=404)
        serializer = CompanyWriteSerializer(company, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(CompanySerializer(company, context={"request": request}).data)


# ===========================================================================
# Feature: Recruiter Dashboard
# ===========================================================================
@extend_schema(tags=["recruiters"])
class RecruiterDashboardView(APIView):
    """GET /api/v1/recruiters/dashboard/ — hiring metrics for the recruiter."""

    permission_classes = [IsAuthenticated, IsRecruiter]

    def get(self, request):
        profile = _recruiter_profile_or_none(request.user)
        if profile is None:
            return Response({"detail": "Recruiter profile not found."}, status=404)
        stats = RecruiterDashboardService().get_stats(profile)
        stats["company"] = profile.company.name
        return Response(stats)


# ===========================================================================
# Feature: Candidate Search
# ===========================================================================
@extend_schema(tags=["recruiters"])
class CandidateSearchView(generics.ListAPIView):
    """GET /api/v1/recruiters/candidates/ — search the talent pool."""

    permission_classes = [IsAuthenticated, IsRecruiter]
    serializer_class = CandidateSearchSerializer
    filterset_class = CandidateFilter
    search_fields = ["headline", "designation", "subject", "skills__name", "user__first_name", "user__last_name"]
    ordering_fields = ["experience_years", "expected_salary", "created_at"]
    ordering = ["-experience_years"]

    def get_queryset(self):
        return (
            JobSeekerProfile.objects
            .filter(user__role=User.Role.JOB_SEEKER, user__is_active=True, is_open_to_work=True)
            .select_related("user")
            .prefetch_related("skills", "qualifications", "user__resumes")
            .distinct()
        )


# ===========================================================================
# Feature: Application Review (across all of the recruiter's jobs)
# ===========================================================================
@extend_schema(tags=["recruiters"])
class RecruiterApplicationReviewView(generics.ListAPIView):
    """GET /api/v1/recruiters/applications/ — every application to the recruiter's jobs."""

    permission_classes = [IsAuthenticated, IsRecruiter]
    serializer_class = ApplicationSerializer
    filterset_fields = ["status", "job"]
    ordering_fields = ["applied_at"]
    ordering = ["-applied_at"]

    def get_queryset(self):
        return (
            JobApplication.objects
            .filter(job__recruiter__user=self.request.user)
            .select_related("applicant", "job", "resume")
            .prefetch_related("history")
        )
