"""Job Seeker dashboard template views."""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import TemplateView
from django.core.paginator import Paginator
from django.utils import timezone

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
        base_qs = Job.objects.filter(status=Job.Status.ACTIVE, approval_status=Job.ApprovalStatus.APPROVED).select_related("company")
        
        if profile:
            from django.db.models import Count, Q, Case, When, Value, IntegerField, F
            
            # Score job type
            job_type_match = Case(
                When(job_type=profile.preferred_job_type, then=Value(2)),
                default=Value(0),
                output_field=IntegerField()
            ) if profile.preferred_job_type else Value(0, output_field=IntegerField())
            
            # Score skills
            skill_ids = list(profile.skills.values_list('id', flat=True)) if profile.skills.exists() else []
            
            if skill_ids:
                qs = base_qs.annotate(
                    skill_match_count=Count('skills_required', filter=Q(skills_required__in=skill_ids)),
                    type_score=job_type_match,
                ).annotate(
                    relevance_score=F('skill_match_count') * 3 + F('type_score')
                ).filter(relevance_score__gt=0).order_by('-published_at', '-relevance_score')
                
                # Fallback if no matching jobs
                if not qs.exists():
                    qs = base_qs.order_by('-published_at')
            else:
                qs = base_qs.annotate(
                    type_score=job_type_match,
                ).annotate(
                    relevance_score=F('type_score')
                ).filter(relevance_score__gt=0).order_by('-published_at', '-relevance_score')
                
                if not qs.exists():
                    qs = base_qs.order_by('-published_at')
        else:
            qs = base_qs.order_by('-published_at')
            
        ctx["recommended_jobs"] = qs[:4]
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


from django.http import JsonResponse
from django.views import View

class SaveJobView(SeekerMixin, View):
    def post(self, request, *args, **kwargs):
        job_id = request.POST.get("job_id")
        if not job_id:
            return JsonResponse({"error": "Job ID required"}, status=400)
        from apps.applications.models import SavedJob
        SavedJob.objects.get_or_create(user=request.user, job_id=job_id)
        return JsonResponse({"success": True})


class UnsaveJobView(SeekerMixin, View):
    def post(self, request, *args, **kwargs):
        job_id = request.POST.get("job_id")
        if not job_id:
            return JsonResponse({"error": "Job ID required"}, status=400)
        from apps.applications.models import SavedJob
        SavedJob.objects.filter(user=request.user, job_id=job_id).delete()
        return JsonResponse({"success": True})


class SeekerSavedJobsView(SeekerMixin, TemplateView):
    template_name = "dashboard/seeker/saved_jobs.html"
    sidebar_section = "saved"
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from apps.applications.models import SavedJob
        saved_jobs = SavedJob.objects.filter(user=self.request.user).select_related('job', 'job__company')
        # We need to monkey-patch is_saved=True onto the job instances so the template renders the button correctly
        jobs = []
        for sj in saved_jobs:
            sj.job.is_saved = True
            jobs.append(sj)
        ctx['saved_jobs'] = jobs
        return ctx


from django.shortcuts import redirect
from django.contrib import messages

class SeekerJobAlertsView(SeekerMixin, TemplateView):
    template_name = "dashboard/seeker/job_alerts.html"
    sidebar_section = "alerts"
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from apps.applications.models import JobAlert
        ctx['job_alerts'] = JobAlert.objects.filter(user=self.request.user)
        ctx['job_types'] = JobAlert.JOB_TYPE_CHOICES
        ctx['experience_levels'] = JobAlert.EXPERIENCE_LEVEL_CHOICES
        return ctx

    def post(self, request, *args, **kwargs):
        from apps.applications.models import JobAlert
        keyword = request.POST.get('keyword', '').strip()
        location = request.POST.get('location', '').strip()
        job_type = request.POST.get('job_type', '').strip()
        experience_level = request.POST.get('experience_level', '').strip()
        
        if not keyword and not location and not job_type and not experience_level:
            messages.error(request, "Please provide at least one criteria for the alert.")
            return redirect("seeker:job-alerts")
            
        JobAlert.objects.create(
            user=request.user,
            keyword=keyword,
            location=location,
            job_type=job_type,
            experience_level=experience_level
        )
        messages.success(request, "Job alert created successfully!")
        return redirect("seeker:job-alerts")


class DeleteJobAlertView(SeekerMixin, View):
    def post(self, request, pk, *args, **kwargs):
        from apps.applications.models import JobAlert
        JobAlert.objects.filter(user=request.user, pk=pk).delete()
        messages.success(request, "Job alert deleted.")
        return redirect("seeker:job-alerts")


class SeekerSettingsView(SeekerMixin, TemplateView):
    template_name = "dashboard/seeker/settings.html"
    sidebar_section = "settings"


class SeekerNotificationsView(SeekerMixin, TemplateView):
    """Full notification history with type-based filters."""

    template_name = "dashboard/seeker/notifications.html"
    sidebar_section = "notifications"

    #: UI filter slug -> set of Notification.notification_type values
    FILTER_MAP = {
        "all": None,
        "unread": "__unread__",
        "shortlisted": {"application_shortlisted"},
        "interviews": {"interview_scheduled"},
        "selected": {"application_selected"},
        "rejected": {"application_rejected"},
        "offers": {"offer_sent", "offer_accepted"},
    }

    def get_context_data(self, **kwargs):
        from apps.notifications.models import Notification
        ctx = super().get_context_data(**kwargs)
        f = (self.request.GET.get("filter") or "all").lower()
        if f not in self.FILTER_MAP:
            f = "all"
        qs = Notification.objects.filter(recipient=self.request.user).order_by("-created_at")
        spec = self.FILTER_MAP[f]
        if spec == "__unread__":
            qs = qs.filter(is_read=False)
        elif isinstance(spec, set):
            qs = qs.filter(notification_type__in=spec)
        ctx["notifications"] = qs[:200]
        ctx["active_filter"] = f
        ctx["filters"] = [
            ("all", "All"), ("unread", "Unread"),
            ("shortlisted", "Shortlisted"), ("interviews", "Interviews"),
            ("selected", "Selected"), ("rejected", "Rejected"), ("offers", "Offers"),
        ]
        return ctx


class SeekerInterviewsView(SeekerMixin, TemplateView):
    template_name = "dashboard/seeker/interviews.html"
    sidebar_section = "interviews"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        base_qs = (
            JobApplication.objects
            .filter(
                applicant=self.request.user,
                interview_at__isnull=False
            )
            .select_related("job", "job__company")
            .order_by("interview_at")
        )
        
        completed_states = [
            JobApplication.Status.INTERVIEW_COMPLETED,
            JobApplication.Status.DECISION_PENDING,
            JobApplication.Status.SELECTED,
            JobApplication.Status.OFFER_SENT,
            JobApplication.Status.OFFER_ACCEPTED,
            JobApplication.Status.JOINED,
        ]
        
        upcoming_interviews = base_qs.exclude(
            status__in=completed_states + [
                JobApplication.Status.INTERVIEW_CANCELLED,
                JobApplication.Status.REJECTED,
                JobApplication.Status.WITHDRAWN,
                JobApplication.Status.ARCHIVED
            ]
        )
        
        completed_interviews = base_qs.filter(
            status__in=completed_states
        )
        
        status_filter = self.request.GET.get("status")
        if status_filter:
            upcoming_interviews = upcoming_interviews.filter(interview_response=status_filter)
            completed_interviews = completed_interviews.filter(interview_response=status_filter)
            
        ctx["upcoming_interviews"] = upcoming_interviews
        ctx["completed_interviews"] = completed_interviews
        ctx["active_filter"] = status_filter or "all"
        ctx["response_choices"] = JobApplication.InterviewResponse.choices
        ctx["upcoming_count"] = upcoming_interviews.count()
        return ctx


class SeekerInterviewDetailView(SeekerMixin, TemplateView):
    template_name = "dashboard/seeker/interview_detail.html"
    sidebar_section = "interviews"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from django.shortcuts import get_object_or_404
        application = get_object_or_404(
            JobApplication.objects.select_related("job", "job__company", "resume"),
            pk=self.kwargs["pk"],
            applicant=self.request.user,
        )
        ctx["application"] = application
        ctx["response_choices"] = JobApplication.InterviewResponse.choices
        return ctx


class SeekerInterviewResponseView(SeekerMixin, View):
    """POST: job seeker responds to a scheduled interview (confirm/decline/reschedule)."""

    def post(self, request, pk, *args, **kwargs):
        from django.shortcuts import get_object_or_404
        from apps.notifications.services import NotificationService
        from apps.notifications.models import Notification

        application = get_object_or_404(
            JobApplication.objects.filter(interview_at__isnull=False).exclude(
                status__in=[
                    JobApplication.Status.INTERVIEW_CANCELLED,
                    JobApplication.Status.REJECTED,
                    JobApplication.Status.WITHDRAWN
                ]
            ),
            pk=pk,
            applicant=request.user,
        )

        action = request.POST.get("action")
        note = request.POST.get("note", "").strip()

        VALID_ACTIONS = {
            "confirmed":             JobApplication.InterviewResponse.CONFIRMED,
            "declined":              JobApplication.InterviewResponse.DECLINED,
            "reschedule_requested":  JobApplication.InterviewResponse.RESCHEDULE_REQUESTED,
        }

        if action not in VALID_ACTIONS:
            messages.error(request, "Invalid action.")
            return redirect("seeker:interview-detail", pk=pk)

        application.interview_response = VALID_ACTIONS[action]
        application.interview_response_note = note
        application.save(update_fields=["interview_response", "interview_response_note"])

        # Notify recruiter
        recruiter_user = getattr(getattr(application.job, "recruiter", None), "user", None)
        if recruiter_user:
            action_labels = {
                "confirmed": "confirmed",
                "declined": "declined",
                "reschedule_requested": "requested a reschedule for",
            }
            verb = action_labels.get(action, "responded to")
            NotificationService.notify(
                recipient=recruiter_user,
                actor=request.user,
                notification_type=Notification.Type.STATUS_CHANGED,
                title=f"Interview {action.replace('_', ' ').title()} — {application.job.title}",
                message=(
                    f"{request.user.full_name} has {verb} the interview for "
                    f"{application.job.title}."
                    + (f"\n\nNote: {note}" if note else "")
                ),
                entity_type="JobApplication",
                entity_id=application.id,
            )

        action_msgs = {
            "confirmed": "Great! You've confirmed your interview attendance.",
            "declined": "You've declined the interview. The recruiter has been notified.",
            "reschedule_requested": "Reschedule request sent to the recruiter.",
        }
        messages.success(request, action_msgs.get(action, "Response recorded."))
        return redirect("seeker:interviews")


class SeekerOutcomesView(SeekerMixin, TemplateView):
    template_name = "dashboard/seeker/outcomes.html"
    sidebar_section = "offers"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["selected_offers"] = JobApplication.objects.filter(
            applicant=self.request.user,
            status__in=[
                JobApplication.Status.SELECTED,
                JobApplication.Status.OFFER_SENT,
                JobApplication.Status.OFFER_ACCEPTED,
                JobApplication.Status.JOINED
            ]
        ).select_related("job", "job__company", "offer_details", "selection").order_by("-created_at")
        
        ctx["rejected_applications"] = JobApplication.objects.filter(
            applicant=self.request.user,
            status=JobApplication.Status.REJECTED
        ).select_related("job", "job__company", "rejection").order_by("-updated_at")
        return ctx


class SeekerOfferDetailView(SeekerMixin, TemplateView):
    template_name = "dashboard/seeker/offer_detail.html"
    sidebar_section = "offers"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from django.shortcuts import get_object_or_404
        application = get_object_or_404(
            JobApplication.objects.select_related(
                "job", "job__company", "job__recruiter", "job__recruiter__user",
                "applicant", "applicant__job_seeker_profile", "offer_details"
            ),
            id=self.kwargs.get("pk"),
            applicant=self.request.user
        )
        ctx["application"] = application
        ctx["offer"] = getattr(application, "offer_details", None)
        return ctx

    def post(self, request, *args, **kwargs):
        from django.shortcuts import get_object_or_404, redirect
        from django.contrib import messages
        from apps.applications.services import ApplicationService
        
        application = get_object_or_404(
            JobApplication,
            id=self.kwargs.get("pk"),
            applicant=request.user
        )
        
        action = request.POST.get("action")
        svc = ApplicationService()
        
        try:
            if action == "accept":
                svc.move_status(application, new_status=JobApplication.Status.OFFER_ACCEPTED, changed_by=request.user)
                messages.success(request, "Congratulations! You have accepted the job offer.")
            elif action == "decline":
                svc.move_status(application, new_status=JobApplication.Status.REJECTED, changed_by=request.user)
                messages.success(request, "You have declined the job offer.")
            else:
                messages.error(request, "Invalid action.")
        except Exception as e:
            messages.error(request, str(e))
            
        return redirect("seeker:offer-detail", pk=application.id)


class DownloadOfferLetterView(SeekerMixin, TemplateView):
    def get(self, request, *args, **kwargs):
        from django.shortcuts import get_object_or_404
        from django.http import HttpResponse
        from io import BytesIO
        from django.template.loader import get_template
        from xhtml2pdf import pisa
        
        application = get_object_or_404(
            JobApplication.objects.select_related("job", "job__company", "applicant", "offer_details"),
            id=self.kwargs.get("pk"),
            applicant=request.user
        )
        
        if not hasattr(application, "offer_details"):
            return HttpResponse("Offer not found", status=404)
            
        context = {
            "application": application,
            "offer": application.offer_details,
            "company": application.job.company,
            "applicant": application.applicant,
            "date": application.offer_details.created_at.date(),
        }
        
        template = get_template("dashboard/seeker/offer_letter_pdf.html")
        html = template.render(context)
        result = BytesIO()
        pdf = pisa.pisaDocument(BytesIO(html.encode("UTF-8")), result)
        
        if not pdf.err:
            response = HttpResponse(result.getvalue(), content_type='application/pdf')
            filename = f"Offer_Letter_{application.applicant.first_name}_{application.job.title.replace(' ', '_')}.pdf"
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response
            
        return HttpResponse("Error generating PDF", status=500)


