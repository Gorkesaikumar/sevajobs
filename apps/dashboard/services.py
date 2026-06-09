"""Aggregated statistics for role-specific dashboards."""

from __future__ import annotations
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from apps.jobs.models import Job
from apps.applications.models import JobApplication
from apps.advertisements.models import Advertisement

User = get_user_model()


class JobSeekerDashboardService:
    def get_stats(self, user) -> dict:
        qs = JobApplication.objects.filter(applicant=user)
        return {
            "total_applications": qs.count(),
            "by_status": list(
                qs.values("status").annotate(count=Count("id")).order_by("status")
            ),
        }


class RecruiterDashboardService:
    def get_stats(self, recruiter_profile) -> dict:
        jobs_qs = Job.objects.filter(recruiter=recruiter_profile)
        apps_qs = JobApplication.objects.filter(job__recruiter=recruiter_profile)
        return {
            "total_jobs": jobs_qs.count(),
            "active_jobs": jobs_qs.filter(status=Job.Status.ACTIVE).count(),
            "total_applications": apps_qs.count(),
            "pending_review": apps_qs.filter(status=JobApplication.Status.APPLIED).count(),
            "shortlisted": apps_qs.filter(status=JobApplication.Status.SHORTLISTED).count(),
        }


class AdminDashboardService:
    def get_stats(self) -> dict:
        return {
            "total_users": User.objects.count(),
            "total_jobs": Job.objects.count(),
            "active_jobs": Job.objects.filter(status=Job.Status.ACTIVE).count(),
            "total_applications": JobApplication.objects.count(),
            "pending_ads": Advertisement.objects.filter(status=Advertisement.Status.PENDING).count(),
        }
