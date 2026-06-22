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
        # Merged active featured jobs from recruiter & staff jobs
        featured_recruiter = list(
            Job.objects.filter(
                status=Job.Status.ACTIVE,
                approval_status=Job.ApprovalStatus.APPROVED,
                is_featured=True,
            )
            .select_related("company", "category")
            .order_by("-published_at")[:6]
        )
        active_staff = list(
            StaffJob.objects.filter(
                status=StaffJob.Status.ACTIVE,
                is_active=True,
            )
            .order_by("-published_at")[:6]
        )
        combined_featured = featured_recruiter + active_staff
        combined_featured.sort(key=lambda j: j.published_at or j.created_at, reverse=True)
        ctx["featured_jobs"] = combined_featured[:6]

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


class JobSearchView(TemplateView):
    template_name = "pages/jobs.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        
        # Recruiter Jobs queryset
        rqs = Job.objects.filter(
            status=Job.Status.ACTIVE,
            approval_status=Job.ApprovalStatus.APPROVED,
        ).select_related("company", "category")

        # Staff Jobs queryset
        sqs = StaffJob.objects.filter(
            status=StaffJob.Status.ACTIVE,
            is_active=True
        )

        # Search Query q
        q = self.request.GET.get("q", "").strip()
        if q:
            rqs = rqs.filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(location__icontains=q) | Q(state__icontains=q) | Q(district__icontains=q) | Q(city__icontains=q))
            sqs = sqs.filter(Q(designation__icontains=q) | Q(organization_name__icontains=q) | Q(job_location__icontains=q) | Q(state__icontains=q) | Q(district__icontains=q) | Q(city__icontains=q))
            ctx["search_query"] = q

        # Location filter (workplace address search)
        location = self.request.GET.get("location", "").strip()
        if location:
            rqs = rqs.filter(Q(location__icontains=location) | Q(city__icontains=location) | Q(district__icontains=location) | Q(state__icontains=location))
            sqs = sqs.filter(Q(job_location__icontains=location) | Q(city__icontains=location) | Q(district__icontains=location) | Q(state__icontains=location))

        # Specific regional dropdown filters
        state_filter = self.request.GET.get("state", "").strip()
        if state_filter:
            rqs = rqs.filter(state__iexact=state_filter)
            sqs = sqs.filter(state__iexact=state_filter)

        district_filter = self.request.GET.get("district", "").strip()
        if district_filter:
            rqs = rqs.filter(district__iexact=district_filter)
            sqs = sqs.filter(district__iexact=district_filter)

        city_filter = self.request.GET.get("city", "").strip()
        if city_filter:
            rqs = rqs.filter(city__iexact=city_filter)
            sqs = sqs.filter(city__iexact=city_filter)

        # Get active states, districts, and cities for the filter sidebar
        active_states = list(Job.objects.filter(status=Job.Status.ACTIVE, approval_status=Job.ApprovalStatus.APPROVED).values_list('state', flat=True).distinct()) + \
                        list(StaffJob.objects.filter(status=StaffJob.Status.ACTIVE, is_active=True).values_list('state', flat=True).distinct())
        active_states = sorted(list(set([s for s in active_states if s])))

        active_districts = list(Job.objects.filter(status=Job.Status.ACTIVE, approval_status=Job.ApprovalStatus.APPROVED).values_list('district', flat=True).distinct()) + \
                           list(StaffJob.objects.filter(status=StaffJob.Status.ACTIVE, is_active=True).values_list('district', flat=True).distinct())
        active_districts = sorted(list(set([d for d in active_districts if d])))

        active_cities = list(Job.objects.filter(status=Job.Status.ACTIVE, approval_status=Job.ApprovalStatus.APPROVED).values_list('city', flat=True).distinct()) + \
                        list(StaffJob.objects.filter(status=StaffJob.Status.ACTIVE, is_active=True).values_list('city', flat=True).distinct())
        active_cities = sorted(list(set([c for c in active_cities if c])))

        ctx["active_states"] = active_states
        ctx["active_districts"] = active_districts
        ctx["active_cities"] = active_cities

        # Salary Min filter
        salary_min = self.request.GET.get("salary_min", "").strip()
        if salary_min:
            rqs = rqs.filter(salary_min__gte=salary_min)
            sqs = sqs.filter(offered_salary__gte=salary_min)

        # Salary Max filter
        salary_max = self.request.GET.get("salary_max", "").strip()
        if salary_max:
            rqs = rqs.filter(salary_max__lte=salary_max)
            sqs = sqs.filter(offered_salary__lte=salary_max)

        # Recruiter-only filters (exclude staff jobs if set)
        job_types = self.request.GET.getlist("job_type")
        has_recruiter_filters = False
        if job_types:
            rqs = rqs.filter(job_type__in=job_types)
            has_recruiter_filters = True

        exp_levels = self.request.GET.getlist("experience_level")
        if exp_levels:
            rqs = rqs.filter(experience_level__in=exp_levels)
            has_recruiter_filters = True

        is_remote = self.request.GET.get("is_remote")
        if is_remote:
            rqs = rqs.filter(is_remote=True)
            has_recruiter_filters = True

        category = self.request.GET.get("category")
        if category:
            rqs = rqs.filter(category__slug=category)
            has_recruiter_filters = True

        # Ordering
        sort = self.request.GET.get("sort", "-published_at")
        
        # Apply database-level sorting to querysets for performance
        if sort == "published_at": # Oldest First
            rqs = rqs.order_by("published_at", "created_at")
            sqs = sqs.order_by("published_at", "created_at")
        elif sort == "salary_min": # Salary Low to High
            rqs = rqs.order_by("salary_min", "-published_at", "-created_at")
            sqs = sqs.order_by("offered_salary", "-published_at", "-created_at")
        elif sort == "-salary_min": # Salary High to Low
            rqs = rqs.order_by("-salary_min", "-published_at", "-created_at")
            sqs = sqs.order_by("-offered_salary", "-published_at", "-created_at")
        elif sort == "-applications_count": # Most Applied
            rqs = rqs.order_by("-applications_count", "-published_at", "-created_at")
            sqs = sqs.annotate(num_apps=Count("applications")).order_by("-num_apps", "-published_at", "-created_at")
        elif sort == "featured": # Featured First
            rqs = rqs.order_by("-is_featured", "-published_at", "-created_at")
            sqs = sqs.order_by("-published_at", "-created_at")
        else: # Default: Newest First ("-published_at")
            # If Featured Jobs exist: Featured Jobs (Newest First) then Regular Jobs (Newest First)
            rqs = rqs.order_by("-is_featured", "-published_at", "-created_at")
            sqs = sqs.order_by("-published_at", "-created_at")

        # Convert to list & Combine
        r_jobs = list(rqs)
        s_jobs = [] if has_recruiter_filters else list(sqs)
        combined = r_jobs + s_jobs

        # Python-level sorting to merge the two sorted lists correctly
        if sort == "published_at": # Oldest First
            combined.sort(key=lambda j: j.published_at or j.created_at)
        elif sort == "salary_min": # Salary Low to High
            combined.sort(key=lambda j: getattr(j, "salary_min", None) or getattr(j, "offered_salary", 0))
        elif sort == "-salary_min": # Salary High to Low
            combined.sort(key=lambda j: getattr(j, "salary_min", None) or getattr(j, "offered_salary", 0), reverse=True)
        elif sort == "-applications_count": # Most Applied
            combined.sort(key=lambda j: getattr(j, "num_apps", None) or getattr(j, "applications_count", 0) or j.applications.count(), reverse=True)
        elif sort == "featured": # Featured First
            combined.sort(key=lambda j: (getattr(j, "is_featured", False), j.published_at or j.created_at), reverse=True)
        else: # Default / Newest First ("-published_at")
            # Pins Featured Jobs (Newest First) then Regular Jobs (Newest First)
            combined.sort(key=lambda j: (getattr(j, "is_featured", False), j.published_at or j.created_at), reverse=True)

        paginator = Paginator(combined, 12)
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
        ).prefetch_related("preferred_qualifications")

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
            qs = qs.filter(Q(name__icontains=q) | Q(industry__icontains=q))
            ctx["search_query"] = q

        industry = self.request.GET.get("industry")
        if industry:
            qs = qs.filter(industry__icontains=industry)

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
