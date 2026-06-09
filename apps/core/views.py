"""Template views for public pages and core functionality."""

from django.views.generic import TemplateView, ListView, DetailView
from django.db.models import Q, Count
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.db import connection
from django.core.paginator import Paginator

from apps.jobs.models import Job, JobCategory, Skill
from apps.recruiters.models import Company
from apps.core.models import Advertisement


class HomeView(TemplateView):
    template_name = "pages/home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["featured_jobs"] = (
            Job.objects.filter(
                status=Job.Status.ACTIVE,
                approval_status=Job.ApprovalStatus.APPROVED,
                is_featured=True,
            )
            .select_related("company", "category")
            .prefetch_related("skills_required")[:6]
        )
        ctx["categories"] = JobCategory.objects.filter(is_active=True, parent__isnull=True)[:8]
        ctx["total_jobs"] = Job.objects.filter(status=Job.Status.ACTIVE, approval_status=Job.ApprovalStatus.APPROVED).count()
        ctx["total_companies"] = Company.objects.filter(is_verified=True).count()
        ctx["featured_companies"] = Company.objects.filter(is_verified=True).order_by("-created_at")[:6]
        
        # Advertisements
        import datetime
        today = datetime.date.today()
        active_ads = Advertisement.objects.filter(
            is_active=True,
        ).filter(
            Q(start_date__isnull=True) | Q(start_date__lte=today)
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=today)
        )
        
        ctx["scroll_ads"] = active_ads.filter(ad_type=Advertisement.AdType.SCROLL_BAR)
        ctx["popup_ads"] = active_ads.filter(ad_type=Advertisement.AdType.POPUP)
        ctx["display_ads"] = active_ads.filter(ad_type=Advertisement.AdType.DISPLAY_AD)
        
        return ctx


class AboutView(TemplateView):
    template_name = "pages/about.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["breadcrumbs"] = [{"label": "About Us"}]
        return ctx


class ContactView(TemplateView):
    template_name = "pages/contact.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["breadcrumbs"] = [{"label": "Contact Us"}]
        return ctx


class FAQView(TemplateView):
    template_name = "pages/faq.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["breadcrumbs"] = [{"label": "FAQ"}]
        return ctx


class PrivacyView(TemplateView):
    template_name = "pages/privacy.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["breadcrumbs"] = [{"label": "Privacy Policy"}]
        return ctx


class TermsView(TemplateView):
    template_name = "pages/terms.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["breadcrumbs"] = [{"label": "Terms & Conditions"}]
        return ctx


class JobSearchView(TemplateView):
    template_name = "pages/jobs.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = Job.objects.filter(
            status=Job.Status.ACTIVE,
            approval_status=Job.ApprovalStatus.APPROVED,
        ).select_related("company", "category").prefetch_related("skills_required")

        # Search
        q = self.request.GET.get("q", "")
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(location__icontains=q))
            ctx["search_query"] = q

        # Filters
        job_types = self.request.GET.getlist("job_type")
        if job_types:
            qs = qs.filter(job_type__in=job_types)

        exp_levels = self.request.GET.getlist("experience_level")
        if exp_levels:
            qs = qs.filter(experience_level__in=exp_levels)

        location = self.request.GET.get("location")
        if location:
            qs = qs.filter(location__icontains=location)

        is_remote = self.request.GET.get("is_remote")
        if is_remote:
            qs = qs.filter(is_remote=True)

        category = self.request.GET.get("category")
        if category:
            qs = qs.filter(category__slug=category)

        salary_min = self.request.GET.get("salary_min")
        if salary_min:
            qs = qs.filter(salary_min__gte=salary_min)

        salary_max = self.request.GET.get("salary_max")
        if salary_max:
            qs = qs.filter(salary_max__lte=salary_max)

        # Ordering
        sort = self.request.GET.get("sort", "-created_at")
        if sort in ["-created_at", "salary_min", "-salary_min", "deadline"]:
            qs = qs.order_by(sort)
        else:
            qs = qs.order_by("-is_featured", "-created_at")

        paginator = Paginator(qs, 12)
        page = self.request.GET.get("page", 1)
        ctx["page_obj"] = paginator.get_page(page)
        ctx["jobs"] = ctx["page_obj"]
        ctx["total_results"] = paginator.count
        ctx["categories"] = JobCategory.objects.filter(is_active=True)
        ctx["breadcrumbs"] = [{"label": "Find Jobs"}]
        return ctx


class JobDetailPageView(DetailView):
    template_name = "pages/job_detail.html"
    model = Job
    slug_field = "slug"
    slug_url_kwarg = "slug"
    context_object_name = "job"

    def get_queryset(self):
        return Job.objects.select_related(
            "company", "category", "recruiter", "minimum_qualification"
        ).prefetch_related("skills_required", "preferred_qualifications")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        job = self.object
        # Increment views
        Job.objects.filter(pk=job.pk).update(views_count=job.views_count + 1)

        # Similar jobs
        ctx["similar_jobs"] = (
            Job.objects.filter(
                status=Job.Status.ACTIVE,
                approval_status=Job.ApprovalStatus.APPROVED,
                category=job.category,
            )
            .exclude(pk=job.pk)
            .select_related("company")[:4]
        )

        # Resumes for apply modal
        if self.request.user.is_authenticated and self.request.user.is_job_seeker:
            ctx["resumes"] = self.request.user.resumes.all()
            ctx["has_applied"] = job.applications.filter(applicant=self.request.user).exists()
            ctx["is_saved"] = job.saved_by.filter(user=self.request.user).exists()

        ctx["breadcrumbs"] = [
            {"label": "Find Jobs", "url": "/jobs/"},
            {"label": job.title},
        ]
        return ctx


class CompanyListPageView(TemplateView):
    template_name = "pages/companies.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = Company.objects.filter(is_verified=True).annotate(
            active_jobs=Count("jobs", filter=Q(jobs__status=Job.Status.ACTIVE))
        )
        q = self.request.GET.get("q", "")
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(industry__icontains=q))
            ctx["search_query"] = q

        industry = self.request.GET.get("industry")
        if industry:
            qs = qs.filter(industry__icontains=industry)

        paginator = Paginator(qs.order_by("-created_at"), 12)
        page = self.request.GET.get("page", 1)
        ctx["page_obj"] = paginator.get_page(page)
        ctx["companies"] = ctx["page_obj"]
        ctx["breadcrumbs"] = [{"label": "Companies"}]
        return ctx


class CompanyDetailPageView(DetailView):
    template_name = "pages/company_detail.html"
    model = Company
    slug_field = "slug"
    slug_url_kwarg = "slug"
    context_object_name = "company"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["active_jobs"] = (
            Job.objects.filter(
                company=self.object,
                status=Job.Status.ACTIVE,
                approval_status=Job.ApprovalStatus.APPROVED,
            )
            .select_related("category")
            .prefetch_related("skills_required")
        )
        ctx["breadcrumbs"] = [
            {"label": "Companies", "url": "/companies/"},
            {"label": self.object.name},
        ]
        return ctx


class HealthCheckView(APIView):
    """Liveness / readiness probe for load balancers and orchestrators."""

    permission_classes = [AllowAny]

    def get(self, request):
        db_ok = self._check_db()
        status_code = 200 if db_ok else 503
        return Response(
            {
                "status": "healthy" if db_ok else "degraded",
                "database": "ok" if db_ok else "error",
            },
            status=status_code,
        )

    @staticmethod
    def _check_db() -> bool:
        try:
            connection.ensure_connection()
            return True
        except Exception as e:
            return False
        return True

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, get_object_or_404
from django.contrib import messages
from django.views import View
from apps.applications.services import ApplicationService
from apps.accounts.models import Resume

class JobApplyView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        job_id = request.POST.get("job_id")
        resume_id = request.POST.get("resume_id")
        cover_letter = request.POST.get("cover_letter", "")
        expected_salary = request.POST.get("expected_salary") or None
        
        job = get_object_or_404(Job, id=job_id)
        resume = get_object_or_404(Resume, id=resume_id, job_seeker=request.user)
        
        try:
            ApplicationService().submit(
                job=job,
                applicant=request.user,
                resume=resume,
                cover_letter=cover_letter,
                expected_salary=expected_salary
            )
            messages.success(request, f"Successfully applied to {job.title}!")
        except Exception as e:
            msg = str(e)
            if hasattr(e, 'detail'):
                # Extract inner error message if present (DRF ValidationError)
                if isinstance(e.detail, dict) and "detail" in e.detail:
                    msg = e.detail["detail"]
                elif isinstance(e.detail, list):
                    msg = e.detail[0]
                else:
                    msg = str(e.detail)
            messages.error(request, f"Application failed: {msg}")
            
        return redirect("core:job-detail", slug=job.slug)
