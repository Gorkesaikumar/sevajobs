from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.views.generic import TemplateView, CreateView, UpdateView, View
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.urls import reverse_lazy, reverse
from django.utils import timezone
from django.db.models import Q
from django.core.paginator import Paginator
import random
import string

from apps.accounts.models import User, AuditLog
from apps.jobs.models import StaffJob, JobAssignment
from apps.applications.models import JobApplication
from apps.jobs.forms import StaffJobForm
from apps.accounts.middleware import get_client_ip


def get_staff_job_for_user(request, pk):
    """Resolve a StaffJob and the requesting staff member's relationship to it.

    Returns a tuple ``(job, is_owner, is_assigned)``.

    * Raises ``Http404`` only when the job genuinely does not exist.
    * Raises ``PermissionDenied`` (403) when the staff member neither created
      the job nor has an active assignment to it — this is what prevents the
      previous behaviour of silently 404-ing on Admin-assigned jobs.
    """
    job = get_object_or_404(StaffJob, id=pk)
    is_owner = job.created_by_id == request.user.id
    is_assigned = JobAssignment.objects.filter(
        job=job,
        assigned_staff=request.user,
        status__in=[JobAssignment.Status.ASSIGNED, JobAssignment.Status.IN_PROGRESS],
    ).exists()
    if not (is_owner or is_assigned):
        raise PermissionDenied("You do not have permission to access this job.")
    return job, is_owner, is_assigned


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Enforces that the user is logged in as a staff member with staff active scope."""
    login_url = "/staff/login/"

    def test_func(self) -> bool:
        user = self.request.user
        scope = self.request.session.get('current_role_scope')
        return bool(user.is_authenticated and user.role == User.Role.STAFF and scope == 'staff')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["sidebar_section"] = getattr(self, "sidebar_section", "")
        return ctx


class StaffDashboardView(StaffRequiredMixin, TemplateView):
    template_name = "dashboard/staff/dashboard.html"
    sidebar_section = "dashboard"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        from apps.jobs.models import JobAssignment
        
        # Get active assignments
        assigned_job_ids = list(JobAssignment.objects.filter(
            assigned_staff=user,
            status__in=["assigned", "in_progress"]
        ).values_list("job_id", flat=True))
        
        # Jobs filter
        staff_jobs_qs = StaffJob.objects.filter(
            Q(created_by=user) | Q(id__in=assigned_job_ids)
        ).distinct()
        
        # Dashboard cards metrics
        ctx["assigned_jobs_count"] = len(assigned_job_ids)
        
        apps_qs = JobApplication.objects.filter(staff_job__in=staff_jobs_qs).distinct()
        ctx["new_applications_count"] = apps_qs.filter(status=JobApplication.Status.APPLIED).count()
        ctx["interviews_scheduled_count"] = apps_qs.filter(status=JobApplication.Status.INTERVIEW_SCHEDULED).count()
        
        progress_statuses = [
            JobApplication.Status.UNDER_REVIEW,
            JobApplication.Status.SHORTLISTED,
            JobApplication.Status.INTERVIEWING,
            JobApplication.Status.INTERVIEW_COMPLETED,
            JobApplication.Status.DECISION_PENDING
        ]
        ctx["recruitment_progress_count"] = apps_qs.filter(status__in=progress_statuses).count()

        # Keep these variables for template legacy compatibility if needed
        ctx["total_jobs"] = staff_jobs_qs.count()
        ctx["active_jobs"] = staff_jobs_qs.filter(status="active", is_active=True).count()
        ctx["closed_jobs"] = staff_jobs_qs.filter(status="closed", is_active=True).count()
        ctx["total_applications"] = apps_qs.count()
        
        # Recent Jobs
        ctx["recent_jobs"] = staff_jobs_qs.order_by("-created_at")[:5]
        
        # Recent Applications
        ctx["recent_applications"] = apps_qs.select_related("applicant", "staff_job").order_by("-applied_at")[:5]
        
        return ctx


class StaffMyJobsView(StaffRequiredMixin, TemplateView):
    template_name = "dashboard/staff/manage_jobs.html"
    sidebar_section = "jobs"

    def get(self, request, *args, **kwargs):
        # Opening "My Jobs" acknowledges the assignment alerts: clear the
        # unread "job assigned" notifications that drive the sidebar badge.
        from apps.notifications.models import Notification
        Notification.objects.filter(
            recipient=request.user,
            notification_type=Notification.Type.JOB_ASSIGNED,
            is_read=False,
        ).update(is_read=True, read_at=timezone.now())
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user

        assigned_job_ids = list(JobAssignment.objects.filter(
            assigned_staff=user,
            status__in=["assigned", "in_progress"]
        ).values_list("job_id", flat=True))

        qs = StaffJob.objects.select_related("created_by").filter(
            Q(created_by=user) | Q(id__in=assigned_job_ids)
        ).distinct()

        # Search
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(designation__icontains=q) |
                Q(organization_name__icontains=q) |
                Q(job_location__icontains=q)
            )

        # Filters
        status = self.request.GET.get("status", "").strip()
        if status in ["active", "closed"]:
            qs = qs.filter(status=status)

        # Pagination
        paginator = Paginator(qs.order_by("-created_at"), 10)
        page_number = self.request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        # Tag each job with its source relative to the current staff member so
        # the template can show "Assigned by Admin" vs "Created by You".
        for job in page_obj:
            job.is_assigned_to_me = job.created_by_id != user.id

        ctx["page_obj"] = page_obj
        ctx["jobs"] = page_obj

        return ctx


class StaffAddJobView(StaffRequiredMixin, View):
    template_name = "dashboard/staff/post_job.html"
    sidebar_section = "add-job"

    def get(self, request):
        form = StaffJobForm()
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        form = StaffJobForm(request.POST, request=request)
        if form.is_valid():
            # Save the job
            job = form.save(commit=False)
            job.created_by = request.user
            
            # Inherit location fields from the Staff member's profile
            if hasattr(request.user, "staff_profile"):
                profile = request.user.staff_profile
                job.country = profile.country
                job.state = profile.state
                job.district = profile.district
                job.city = profile.city
            
            # Generate unique job_id: SJOB- + random 6 digits
            while True:
                job_id = "SJOB-" + "".join(random.choices(string.digits, k=6))
                if not StaffJob.objects.filter(job_id=job_id).exists():
                    job.job_id = job_id
                    break

            job.status = StaffJob.Status.ACTIVE
            job.published_at = timezone.now()
            job.is_active = True
            job.save()

            # Audit Log
            AuditLog.objects.create(
                user=request.user,
                role=request.user.role,
                action="Job Created",
                module="Staff Job Posting",
                ip_address=get_client_ip(request),
                details={"job_id": job.job_id, "designation": job.designation}
            )

            messages.success(request, f"Job '{job.designation}' posted successfully! It is now live on the site.")
            return redirect("staff:my-jobs")
        else:
            return render(request, self.template_name, {"form": form})


class StaffEditJobView(StaffRequiredMixin, View):
    template_name = "dashboard/staff/post_job.html"
    sidebar_section = "jobs"

    def get(self, request, pk):
        job, is_owner, is_assigned = get_staff_job_for_user(request, pk)
        if not is_owner:
            # Admin-assigned jobs are read-only for staff: the posting belongs
            # to the Admin. Staff manage recruitment via the Applications page.
            messages.info(
                request,
                "This job was assigned to you by Admin and is read-only. "
                "You can manage its applications, but only the job owner can edit the posting.",
            )
            return redirect("staff:my-jobs")
        form = StaffJobForm(instance=job, request=request)
        return render(request, self.template_name, {"form": form, "is_edit": True, "job": job})

    def post(self, request, pk):
        job, is_owner, is_assigned = get_staff_job_for_user(request, pk)
        if not is_owner:
            raise PermissionDenied("You cannot edit a job that was assigned to you by Admin.")
        form = StaffJobForm(request.POST, instance=job, request=request)
        if form.is_valid():
            form.save()
            
            # Audit Log
            AuditLog.objects.create(
                user=request.user,
                role=request.user.role,
                action="Job Updated",
                module="Staff Job Posting",
                ip_address=get_client_ip(request),
                details={"job_id": job.job_id, "designation": job.designation}
            )

            messages.success(request, f"Job '{job.designation}' updated successfully.")
            return redirect("staff:my-jobs")
        else:
            return render(request, self.template_name, {"form": form, "is_edit": True, "job": job})


class StaffJobToggleView(StaffRequiredMixin, View):
    def post(self, request, pk):
        job, is_owner, is_assigned = get_staff_job_for_user(request, pk)
        if not is_owner:
            messages.error(request, "Only the job owner can close or reopen this posting.")
            return redirect("staff:my-jobs")
        action = request.POST.get("action")
        
        if action == "close":
            job.status = StaffJob.Status.CLOSED
            job.save(update_fields=["status"])
            
            # Audit Log
            AuditLog.objects.create(
                user=request.user,
                role=request.user.role,
                action="Job Closed",
                module="Staff Job Posting",
                ip_address=get_client_ip(request),
                details={"job_id": job.job_id, "designation": job.designation}
            )
            messages.success(request, f"Job '{job.designation}' has been closed.")
            
        elif action == "reopen":
            job.status = StaffJob.Status.ACTIVE
            job.published_at = timezone.now()
            job.save(update_fields=["status", "published_at"])
            
            # Audit Log
            AuditLog.objects.create(
                user=request.user,
                role=request.user.role,
                action="Job Reopened",
                module="Staff Job Posting",
                ip_address=get_client_ip(request),
                details={"job_id": job.job_id, "designation": job.designation}
            )
            messages.success(request, f"Job '{job.designation}' has been reopened and is live.")
            
        return redirect("staff:my-jobs")


class StaffApplicationsView(StaffRequiredMixin, TemplateView):
    template_name = "dashboard/staff/applications.html"
    sidebar_section = "applications"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        from apps.jobs.models import JobAssignment
        
        assigned_job_ids = list(JobAssignment.objects.filter(
            assigned_staff=user,
            status__in=["assigned", "in_progress"]
        ).values_list("job_id", flat=True))
        
        qs = JobApplication.objects.filter(
            Q(staff_job__created_by=user) | Q(staff_job_id__in=assigned_job_ids)
        ).select_related("applicant", "staff_job", "resume").distinct()
        
        # Search candidate name / email
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(applicant__first_name__icontains=q) | 
                Q(applicant__last_name__icontains=q) | 
                Q(applicant__email__icontains=q)
            )

        # Filters
        status = self.request.GET.get("status", "").strip()
        if status:
            qs = qs.filter(status=status)

        paginator = Paginator(qs.order_by("-applied_at"), 10)
        page_number = self.request.GET.get("page", 1)
        ctx["page_obj"] = paginator.get_page(page_number)
        ctx["applications"] = ctx["page_obj"]
        
        return ctx


class StaffProfileView(StaffRequiredMixin, View):
    template_name = "dashboard/staff/profile.html"
    sidebar_section = "profile"

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        phone = request.POST.get("phone", "").strip()
        country = request.POST.get("country", "").strip()
        state = request.POST.get("state", "").strip()
        district = request.POST.get("district", "").strip()
        city = request.POST.get("city", "").strip()
        
        if not first_name or not last_name:
            messages.error(request, "First name and last name are required.")
            return render(request, self.template_name)

        if not country or not state or not district or not city:
            messages.error(request, "Location fields (Country, State, District, City) are required.")
            return render(request, self.template_name)

        user = request.user
        
        # Check if phone number is unique
        if phone and User.objects.filter(phone=phone).exclude(id=user.id).exists():
            messages.error(request, "This phone number is already registered by another user.")
            return render(request, self.template_name)

        user.first_name = first_name
        user.last_name = last_name
        user.phone = phone or None
        user.save(update_fields=["first_name", "last_name", "phone"])

        # Also update StaffProfile if it exists
        if hasattr(user, "staff_profile"):
            profile = user.staff_profile
            profile.full_name = f"{first_name} {last_name}".strip()
            profile.phone_number = phone
            profile.country = country
            profile.state = state
            profile.district = district
            profile.city = city
            profile.save()

        messages.success(request, "Profile updated successfully.")
        return redirect("staff:profile")
