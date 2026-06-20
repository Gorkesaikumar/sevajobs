from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
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
from apps.jobs.models import StaffJob
from apps.applications.models import JobApplication
from apps.jobs.forms import StaffJobForm
from apps.accounts.middleware import get_client_ip

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
        
        # Stats
        ctx["total_jobs"] = StaffJob.objects.filter(created_by=user).count()
        ctx["active_jobs"] = StaffJob.objects.filter(created_by=user, status="active", is_active=True).count()
        ctx["closed_jobs"] = StaffJob.objects.filter(created_by=user, status="closed", is_active=True).count()
        ctx["total_applications"] = JobApplication.objects.filter(staff_job__created_by=user).count()
        
        # Recent Jobs
        ctx["recent_jobs"] = StaffJob.objects.filter(created_by=user).order_by("-created_at")[:5]
        
        # Recent Applications
        ctx["recent_applications"] = JobApplication.objects.filter(staff_job__created_by=user).select_related("applicant", "staff_job").order_by("-applied_at")[:5]
        
        return ctx


class StaffMyJobsView(StaffRequiredMixin, TemplateView):
    template_name = "dashboard/staff/manage_jobs.html"
    sidebar_section = "jobs"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        qs = StaffJob.objects.filter(created_by=user)

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
        ctx["page_obj"] = paginator.get_page(page_number)
        ctx["jobs"] = ctx["page_obj"]
        
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
        job = get_object_or_404(StaffJob, id=pk, created_by=request.user)
        form = StaffJobForm(instance=job, request=request)
        return render(request, self.template_name, {"form": form, "is_edit": True, "job": job})

    def post(self, request, pk):
        job = get_object_or_404(StaffJob, id=pk, created_by=request.user)
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
        job = get_object_or_404(StaffJob, id=pk, created_by=request.user)
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
        
        # Get all applications for jobs posted by this staff user
        qs = JobApplication.objects.filter(staff_job__created_by=user).select_related("applicant", "staff_job", "resume")
        
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
        
        if not first_name or not last_name:
            messages.error(request, "First name and last name are required.")
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
            profile.save(update_fields=["full_name", "phone_number"])

        messages.success(request, "Profile updated successfully.")
        return redirect("staff:profile")
