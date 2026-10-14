"""Template views for public pages and core functionality."""

from django.views.generic import TemplateView, DetailView
from django.db.models import Q, Count, Sum
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.db import connection
from django.core.paginator import Paginator

from apps.jobs.models import Job, JobCategory, StaffJob
from apps.recruiters.models import Company
from apps.core.models import Advertisement


class HomeView(TemplateView):
    template_name = "pages/home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from django.utils import timezone
        today = timezone.now().date()

        # Merged active, publicly visible jobs from recruiter & staff jobs (ordered by publication date)
        recruiter_jobs = list(
            Job.objects.filter(
                status=Job.Status.ACTIVE,
                approval_status=Job.ApprovalStatus.APPROVED,
                is_active=True,
            )
            .filter(Q(deadline__isnull=True) | Q(deadline__gte=today))
            .select_related("company", "category", "minimum_qualification")
            .order_by("-published_at", "-created_at", "-id")[:6]
        )
        active_staff = list(
            StaffJob.objects.filter(
                status=StaffJob.Status.ACTIVE,
                is_active=True,
            )
            .order_by("-published_at", "-created_at", "-id")[:6]
        )
        combined_jobs = recruiter_jobs + active_staff
        combined_jobs.sort(key=lambda j: (j.published_at or j.created_at, str(j.id)), reverse=True)
        latest_jobs = combined_jobs[:6]
        ctx["featured_jobs"] = latest_jobs
        ctx["latest_jobs"] = latest_jobs

        ctx["categories"] = JobCategory.objects.filter(is_active=True, parent__isnull=True)[:8]
        
        total_recruiter = Job.objects.filter(status=Job.Status.ACTIVE, approval_status=Job.ApprovalStatus.APPROVED).count()
        total_staff = StaffJob.objects.filter(status=StaffJob.Status.ACTIVE, is_active=True).count()
        ctx["total_jobs"] = total_recruiter + total_staff
        
        ctx["total_companies"] = Company.objects.filter(is_verified=True).count()
        ctx["featured_companies"] = Company.objects.filter(is_verified=True).order_by("-created_at")[:6]
        
        from apps.accounts.models import User
        from apps.applications.models import JobApplication
        ctx["total_teachers"] = User.objects.filter(role=User.Role.JOB_SEEKER, is_active=True).count()
        ctx["total_placements"] = JobApplication.objects.filter(status=JobApplication.Status.SELECTED).count()
        
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


class BaseJobDiscoveryView(TemplateView):
    template_name = "pages/jobs.html"

    def get_discovery_kwargs(self) -> dict:
        return {}

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        params = self.request.GET

        def _to_int(val):
            try:
                return int(val) if val else None
            except (ValueError, TypeError):
                return None

        discovery_args = self.get_discovery_kwargs()

        search_args = {
            "q": params.get("q", "").strip() or None,
            "location_query": params.get("location", "").strip() or None,
            "experience": params.get("experience", "").strip() or None,
            "city_slug": params.get("city", "").strip() or discovery_args.get("city_slug"),
            "state_slug": params.get("state", "").strip() or discovery_args.get("state_slug"),
            "subject_slug": discovery_args.get("subject_slug"),
            "location_slug": discovery_args.get("location_slug"),
            "grade": params.get("grade", "").strip() or discovery_args.get("grade"),
            "job_types": params.getlist("job_type") or None,
            "experience_levels": params.getlist("experience_level") or None,
            "is_remote": True if params.get("is_remote") in ["true", "on", "1"] else None,
            "salary_min": _to_int(params.get("salary_min")),
            "salary_max": _to_int(params.get("salary_max")),
            "category_slug": params.get("category", "").strip() or None,
            "sort": params.get("sort", "-published_at"),
            "page": _to_int(params.get("page")) or 1,
            "request": self.request,
        }

        from apps.jobs.discovery_service import JobDiscoveryService
        search_result = JobDiscoveryService.search_jobs(**search_args)
        ctx.update(search_result)

        # Active regional dropdown lists for the filter sidebar
        active_states = list(Job.objects.filter(status=Job.Status.ACTIVE, approval_status=Job.ApprovalStatus.APPROVED).values_list('state', flat=True).distinct()) + \
                        list(StaffJob.objects.filter(status=StaffJob.Status.ACTIVE, is_active=True).values_list('state', flat=True).distinct())
        ctx["active_states"] = sorted(list(set([s for s in active_states if s])))

        active_districts = list(Job.objects.filter(status=Job.Status.ACTIVE, approval_status=Job.ApprovalStatus.APPROVED).values_list('district', flat=True).distinct()) + \
                           list(StaffJob.objects.filter(status=StaffJob.Status.ACTIVE, is_active=True).values_list('district', flat=True).distinct())
        ctx["active_districts"] = sorted(list(set([d for d in active_districts if d])))

        active_cities = list(Job.objects.filter(status=Job.Status.ACTIVE, approval_status=Job.ApprovalStatus.APPROVED).values_list('city', flat=True).distinct()) + \
                        list(StaffJob.objects.filter(status=StaffJob.Status.ACTIVE, is_active=True).values_list('city', flat=True).distinct())
        ctx["active_cities"] = sorted(list(set([c for c in active_cities if c])))

        ctx["categories"] = JobCategory.objects.filter(is_active=True)
        ctx["breadcrumbs"] = search_result["seo_meta"]["breadcrumbs"]

        return ctx


class JobSearchView(BaseJobDiscoveryView):
    """General job search page."""
    pass


class JobSubjectView(BaseJobDiscoveryView):
    """Dedicated SEO landing page for Jobs by Subject, e.g. /jobs/india/english-teacher/"""
    def get_discovery_kwargs(self) -> dict:
        return {"subject_slug": self.kwargs.get("subject_slug")}


class JobLocationView(BaseJobDiscoveryView):
    """Dedicated SEO landing page for Jobs by City or State, e.g. /jobs/hyderabad/ or /jobs/telangana/"""
    def get_discovery_kwargs(self) -> dict:
        return {"location_slug": self.kwargs.get("location_slug")}


class JobLevelView(BaseJobDiscoveryView):
    """Dedicated SEO landing page for Jobs by Level, e.g. /jobs/level/primary/"""
    def get_discovery_kwargs(self) -> dict:
        return {"grade": self.kwargs.get("level_slug")}


class CurrentVacanciesView(BaseJobDiscoveryView):
    """All Teaching Jobs & Current Vacancies page, e.g. /current-vacancies"""
    def get_discovery_kwargs(self) -> dict:
        return {"grade": self.request.GET.get("grade")}



class JobDetailPageView(DetailView):
    template_name = "pages/job_detail.html"
    model = Job
    slug_field = "slug"
    slug_url_kwarg = "slug"
    context_object_name = "job"

    def get_queryset(self):
        return Job.objects.select_related(
            "company", "category", "recruiter", "minimum_qualification"
        ).prefetch_related("preferred_qualifications")

    def get_object(self, queryset=None):
        if queryset is None:
            queryset = self.get_queryset()
        slug = self.kwargs.get(self.slug_url_kwarg)
        job = queryset.filter(slug=slug).first()
        if not job:
            try:
                import uuid
                uuid_obj = uuid.UUID(str(slug))
                job = queryset.filter(pk=uuid_obj).first()
            except (ValueError, TypeError):
                pass
        if not job:
            from django.http import Http404
            raise Http404("Job not found")
        return job

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
            .select_related("company")
            .order_by("-published_at", "-created_at")[:4]
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
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(location__icontains=q)
                | Q(headquarters__icontains=q)
                | Q(city__icontains=q)
            )
            ctx["search_query"] = q

        institute_type = self.request.GET.get("institute_type")
        if institute_type:
            qs = qs.filter(institute_type=institute_type)

        industry = self.request.GET.get("industry")
        if industry and "education" not in industry.lower():
            qs = qs.none()

        paginator = Paginator(qs.order_by("-created_at"), 12)
        page = self.request.GET.get("page", 1)
        ctx["page_obj"] = paginator.get_page(page)
        ctx["companies"] = ctx["page_obj"]
        ctx["breadcrumbs"] = [{"label": "Schools/Colleges"}]
        return ctx


class CompanyDetailPageView(DetailView):
    template_name = "pages/company_detail.html"
    model = Company
    slug_field = "slug"
    slug_url_kwarg = "slug"
    context_object_name = "company"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = Job.objects.filter(
            company=self.object,
            status=Job.Status.ACTIVE,
            approval_status=Job.ApprovalStatus.APPROVED,
        )

        aggregates = qs.aggregate(
            total_vacancies=Sum("vacancies"),
            total_applications=Sum("applications_count")
        )
        total_open_vacancies = aggregates["total_vacancies"] or 0
        total_applications = aggregates["total_applications"] or 0
        total_active_jobs = qs.count()

        # Apply filters
        category_slug = self.request.GET.get("category")
        if category_slug:
            qs = qs.filter(category__slug=category_slug)

        job_type = self.request.GET.get("job_type")
        if job_type:
            qs = qs.filter(job_type=job_type)

        experience = self.request.GET.get("experience")
        if experience:
            qs = qs.filter(experience_level=experience)

        location = self.request.GET.get("location")
        if location:
            qs = qs.filter(location__icontains=location)

        ctx["active_jobs"] = qs.select_related("category").order_by("-published_at")
        ctx["total_open_vacancies"] = total_open_vacancies
        ctx["total_active_jobs"] = total_active_jobs
        ctx["total_applications"] = total_applications
        
        ctx["job_types"] = Job.JobType.choices
        ctx["experience_levels"] = Job.ExperienceLevel.choices
        ctx["categories"] = JobCategory.objects.filter(is_active=True).order_by("name")
        
        ctx["breadcrumbs"] = [
            {"label": "Schools/Colleges", "url": "/schools/"},
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
        
        # Check if job_id refers to a StaffJob or standard Job
        is_staff = StaffJob.objects.filter(id=job_id).exists()
        
        if is_staff:
            job = get_object_or_404(StaffJob, id=job_id)
        else:
            job = get_object_or_404(Job, id=job_id)
            
        resume = get_object_or_404(Resume, id=resume_id, job_seeker=request.user)
        
        try:
            if is_staff:
                ApplicationService().submit(
                    staff_job=job,
                    applicant=request.user,
                    resume=resume,
                    cover_letter=cover_letter,
                    expected_salary=expected_salary
                )
                messages.success(request, f"Successfully applied to {job.designation}!")
            else:
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
            
        if is_staff:
            return redirect("core:staff-job-detail", pk=job.id)
        else:
            return redirect("core:job-detail", slug=job.slug)


class StaffJobDetailPageView(DetailView):
    template_name = "pages/staff_job_detail.html"
    model = StaffJob
    context_object_name = "job"

    def get_queryset(self):
        return StaffJob.objects.select_related("created_by")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        job = self.object
        
        # Similar staff jobs
        ctx["similar_jobs"] = (
            StaffJob.objects.filter(
                status=StaffJob.Status.ACTIVE,
                is_active=True,
            )
            .exclude(pk=job.pk)
            .order_by("-published_at", "-created_at")[:4]
        )

        # Resumes for apply modal
        if self.request.user.is_authenticated and self.request.user.is_job_seeker:
            ctx["resumes"] = self.request.user.resumes.all()
            ctx["has_applied"] = job.applications.filter(applicant=self.request.user).exists()

        ctx["breadcrumbs"] = [
            {"label": "Find Jobs", "url": "/jobs/"},
            {"label": job.designation},
        ]
        return ctx
