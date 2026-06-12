"""Job Seeker dashboard template views."""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import TemplateView
from django.core.paginator import Paginator

from apps.jobs.models import Job
from apps.applications.models import JobApplication


class SeekerMixin(LoginRequiredMixin, UserPassesTestMixin):
    login_url = "/jobseeker/login/"

    def test_func(self):
        scope = self.request.session.get('current_role_scope')
        if scope == 'job_seeker':
            return self.request.user.is_job_seeker or getattr(self.request.user, 'is_admin_role', False)
        return False

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["sidebar_section"] = self.sidebar_section if hasattr(self, "sidebar_section") else ""
        return ctx


class SeekerDashboardView(SeekerMixin, TemplateView):
    template_name = "dashboard/seeker/dashboard.html"
    sidebar_section = "dashboard"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        profile = getattr(user, "job_seeker_profile", None)

        ctx["profile"] = profile
        applications = JobApplication.objects.filter(applicant=user).select_related("job", "job__company")
        ctx["applied_count"] = applications.count()
        ctx["saved_count"] = 0  # placeholder
        ctx["shortlisted_count"] = applications.filter(status="shortlisted").count()
        ctx["interview_count"] = applications.filter(status="interview_scheduled").count()
        ctx["recent_applications"] = applications.order_by("-applied_at")[:5]
        ctx["profile_completion"] = profile.profile_completion if profile else 25
        ctx["has_resume"] = user.resumes.exists() if hasattr(user, 'resumes') else False
        ctx["has_skills"] = profile.skills.exists() if profile else False

        # Recommended jobs
        ctx["recommended_jobs"] = (
            Job.objects.filter(status=Job.Status.ACTIVE, approval_status=Job.ApprovalStatus.APPROVED)
            .select_related("company")[:4]
        )
        return ctx


class SeekerProfileView(SeekerMixin, TemplateView):
    template_name = "dashboard/seeker/profile.html"
    sidebar_section = "profile"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["profile"] = getattr(self.request.user, "job_seeker_profile", None)
        return ctx


class SeekerEditProfileView(SeekerMixin, TemplateView):
    template_name = "dashboard/seeker/edit_profile.html"
    sidebar_section = "profile"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["profile"] = getattr(self.request.user, "job_seeker_profile", None)
        return ctx

    def post(self, request, *args, **kwargs):
        from django.contrib import messages
        from django.shortcuts import redirect
        from apps.accounts.seeker_services import ProfileService
        from apps.accounts.models import JobSeekerProfile
        from apps.jobs.models import Skill
        
        user = request.user
        profile = getattr(user, "job_seeker_profile", None)
        if not profile:
            profile = JobSeekerProfile.objects.create(user=user)
            
        user_fields = {
            "first_name": request.POST.get("first_name", user.first_name),
            "last_name": request.POST.get("last_name", user.last_name),
            "phone": request.POST.get("phone", user.phone),
        }
        
        district = request.POST.get("district", "").strip()
        taluka = request.POST.get("taluka", "").strip()
        city = request.POST.get("city", "").strip()
        state = request.POST.get("state", "").strip()
        
        loc_parts = [p for p in [taluka, district, city, state] if p]
        current_location = ", ".join(loc_parts) if loc_parts else profile.current_location

        profile_fields = {
            "date_of_birth": request.POST.get("date_of_birth") or None,
            "summary": request.POST.get("bio", profile.summary),
            "city": city or profile.city,
            "district": district or profile.district,
            "taluka": taluka or profile.taluka,
            "state": state or profile.state,
            "current_location": current_location,
            "headline": request.POST.get("headline", profile.headline),
            "linkedin_url": request.POST.get("linkedin", profile.linkedin_url),
            "github_url": request.POST.get("github", profile.github_url),
            "portfolio_url": request.POST.get("portfolio", profile.portfolio_url),
        }
        
        experience_str = request.POST.get("experience_years")
        if experience_str and experience_str.isdigit():
            profile_fields["experience_years"] = int(experience_str)

        skills_str = request.POST.get("skills", "")
        skills = []
        if skills_str:
            from django.utils.text import slugify
            skill_names = [s.strip() for s in skills_str.split(",") if s.strip()]
            for name in skill_names:
                obj = Skill.objects.filter(name__iexact=name).first()
                if not obj:
                    slug = slugify(name) or "skill"
                    original_slug = slug
                    counter = 1
                    while Skill.objects.filter(slug=slug).exists():
                        slug = f"{original_slug}-{counter}"
                        counter += 1
                    obj = Skill.objects.create(name=name, slug=slug)
                skills.append(obj)

        ProfileService().update(
            profile,
            user_fields=user_fields,
            profile_fields=profile_fields,
            skills=skills
        )
        
        messages.success(request, "Profile updated successfully.")
        return redirect("seeker:profile")


class SeekerResumesView(SeekerMixin, TemplateView):
    template_name = "dashboard/seeker/resumes.html"
    sidebar_section = "resumes"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["resumes"] = self.request.user.resumes.all() if hasattr(self.request.user, "resumes") else []
        return ctx

    def post(self, request, *args, **kwargs):
        from django.contrib import messages
        from django.shortcuts import redirect
        from apps.accounts.seeker_services import ResumeService
        from rest_framework.exceptions import ValidationError

        title = request.POST.get("title")
        file = request.FILES.get("file")
        
        if not title or not file:
            messages.error(request, "Please provide a title and select a file.")
            return redirect("seeker:resumes")
            
        try:
            ResumeService().upload(request.user, title=title, file=file)
            messages.success(request, "Resume uploaded successfully.")
        except ValidationError as e:
            if isinstance(e.detail, dict):
                msgs = []
                for k, v in e.detail.items():
                    if isinstance(v, list):
                        msgs.extend(str(item) for item in v)
                    else:
                        msgs.append(str(v))
                msg = " ".join(msgs)
            else:
                msg = str(e)
            messages.error(request, f"Error: {msg}")
        except Exception as e:
            messages.error(request, "An error occurred while uploading.")
            
        return redirect("seeker:resumes")


class SeekerAppliedJobsView(SeekerMixin, TemplateView):
    template_name = "dashboard/seeker/applied_jobs.html"
    sidebar_section = "applied"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = JobApplication.objects.filter(applicant=self.request.user).select_related("job", "job__company").order_by("-applied_at")
        status = self.request.GET.get("status")
        if status:
            qs = qs.filter(status=status)
        paginator = Paginator(qs, 10)
        ctx["page_obj"] = paginator.get_page(self.request.GET.get("page", 1))
        ctx["applications"] = ctx["page_obj"]
        ctx["active_status"] = status or "all"
        ctx["status_counts"] = {
            s: JobApplication.objects.filter(applicant=self.request.user, status=s).count()
            for s in ["applied", "under_review", "shortlisted", "interview_scheduled", "selected", "rejected"]
        }
        return ctx


class SeekerSavedJobsView(SeekerMixin, TemplateView):
    template_name = "dashboard/seeker/saved_jobs.html"
    sidebar_section = "saved"


class SeekerJobAlertsView(SeekerMixin, TemplateView):
    template_name = "dashboard/seeker/job_alerts.html"
    sidebar_section = "alerts"


class SeekerSettingsView(SeekerMixin, TemplateView):
    template_name = "dashboard/seeker/settings.html"
    sidebar_section = "settings"
