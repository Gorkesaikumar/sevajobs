"""
Admin Views for Walk-in Management Module.
Provides list, filtering, creation, editing, detail inspection, and lifecycle status transitions
for walk-in vacancies on the authoritative Job model.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.middleware import get_client_ip
from apps.accounts.models import AuditLog, User
from apps.jobs.models import Job
from apps.jobs.job_alert_matching_service import CandidateJobAlertMatchingService
from apps.recruiters.models import Company
from .admin_views import AdminMixin
from .admin_walkin_forms import AdminWalkInJobForm

logger = logging.getLogger("apps.dashboard")


class AdminWalkInListView(AdminMixin, TemplateView):
    """
    Database-backed list of walk-in vacancies with search, status filters,
    date filters, live candidate matching counts, and lifecycle controls.
    """
    template_name = "dashboard/admin/walkins/list.html"
    sidebar_section = "admin_walkins"

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        today = timezone.now().date()

        # Base QuerySet: Real Walk-in jobs only
        qs = Job.objects.filter(is_walkin=True).select_related("company", "recruiter__user")

        # ── 1. Search Query ──
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(title__icontains=q) |
                Q(company__name__icontains=q) |
                Q(location__icontains=q) |
                Q(city__icontains=q) |
                Q(walkin_venue__icontains=q) |
                Q(metadata__subject__icontains=q)
            )

        # ── 2. Status Filter ──
        status_filter = (self.request.GET.get("status") or "all").strip().lower()
        if status_filter == "published":
            qs = qs.filter(
                status=Job.Status.ACTIVE,
                approval_status=Job.ApprovalStatus.APPROVED,
                is_active=True,
            )
        elif status_filter == "draft":
            qs = qs.filter(
                Q(status=Job.Status.DRAFT) | Q(approval_status=Job.ApprovalStatus.PENDING)
            ).filter(is_active=True)
        elif status_filter == "cancelled":
            qs = qs.filter(
                Q(status=Job.Status.CLOSED) | Q(is_active=False) | Q(metadata__walkin_status="cancelled")
            )
        elif status_filter == "completed":
            qs = qs.filter(walkin_end_date__lt=today)

        # ── 3. Date Filter ──
        date_filter = (self.request.GET.get("date") or "all").strip().lower()
        if date_filter == "today":
            qs = qs.filter(
                Q(walkin_start_date=today) |
                (Q(walkin_start_date__lte=today) & Q(walkin_end_date__gte=today))
            )
        elif date_filter == "upcoming":
            qs = qs.filter(Q(walkin_start_date__gt=today) | Q(walkin_end_date__gte=today))
        elif date_filter == "past":
            qs = qs.filter(walkin_end_date__lt=today)

        # ── 4. Summary Metrics ──
        base_walkins = Job.objects.filter(is_walkin=True)
        total_count = base_walkins.count()
        published_count = base_walkins.filter(
            status=Job.Status.ACTIVE,
            approval_status=Job.ApprovalStatus.APPROVED,
            is_active=True,
        ).count()
        upcoming_count = base_walkins.filter(
            status=Job.Status.ACTIVE,
            approval_status=Job.ApprovalStatus.APPROVED,
            is_active=True,
        ).filter(Q(walkin_end_date__gte=today) | Q(walkin_start_date__gte=today)).count()
        draft_count = base_walkins.filter(
            Q(status=Job.Status.DRAFT) | Q(approval_status=Job.ApprovalStatus.PENDING)
        ).filter(is_active=True).count()

        ctx["metrics"] = {
            "total": total_count,
            "published": published_count,
            "upcoming": upcoming_count,
            "drafts": draft_count,
        }

        # ── 5. Ordering & Pagination ──
        qs = qs.order_by("-walkin_start_date", "-created_at")
        paginator = Paginator(qs, 15)
        page_number = self.request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        # ── 6. Candidate Match Count Enrichment ──
        # Calculate real matching candidates for current page walk-ins
        for job in page_obj:
            job.match_count = CandidateJobAlertMatchingService.count_matching_candidates_for_walkin(job)
            
            # Formatted status helper
            meta = job.metadata or {}
            is_cancelled = (job.status == Job.Status.CLOSED and not job.is_active) or meta.get("walkin_status") == "cancelled"
            is_completed = bool(job.walkin_end_date and job.walkin_end_date < today)

            if is_cancelled:
                job.computed_badge = "cancelled"
                job.computed_badge_label = "Cancelled"
            elif is_completed:
                job.computed_badge = "completed"
                job.computed_badge_label = "Completed"
            elif job.is_published:
                job.computed_badge = "published"
                job.computed_badge_label = "Published"
            else:
                job.computed_badge = "draft"
                job.computed_badge_label = "Draft"

            # Formatted date badge
            if job.walkin_start_date:
                if job.walkin_start_date == today or (job.walkin_end_date and job.walkin_start_date <= today <= job.walkin_end_date):
                    job.date_timing_badge = "today"
                    job.date_timing_label = "Happening Today"
                elif job.walkin_start_date > today:
                    job.date_timing_badge = "upcoming"
                    job.date_timing_label = "Upcoming"
                else:
                    job.date_timing_badge = "past"
                    job.date_timing_label = "Past Event"
            else:
                job.date_timing_badge = "unscheduled"
                job.date_timing_label = "Unscheduled"

        ctx["page_obj"] = page_obj
        ctx["walkins"] = page_obj
        ctx["search_query"] = q
        ctx["status_filter"] = status_filter
        ctx["date_filter"] = date_filter
        return ctx


class AdminWalkInCreateView(AdminMixin, View):
    """
    Fast, minimal walk-in creation form view.
    Supports 'Save as Draft' and 'Save & Publish Walk-in'.
    """
    template_name = "dashboard/admin/walkins/form.html"
    sidebar_section = "admin_walkins"

    def get(self, request: HttpRequest) -> HttpResponse:
        form = AdminWalkInJobForm()
        companies = Company.objects.all().order_by("name")
        return render(request, self.template_name, {
            "form": form,
            "is_edit": False,
            "companies": companies,
        })

    def post(self, request: HttpRequest) -> HttpResponse:
        action = request.POST.get("action", "publish").strip().lower()
        if action not in ("publish", "draft"):
            action = "publish"

        form = AdminWalkInJobForm(request.POST, action=action)
        if form.is_valid():
            job = form.save(user=request.user, action=action)

            # Audit logging
            audit_action = "Walk-in Published" if action == "publish" else "Walk-in Created"
            AuditLog.objects.create(
                user=request.user,
                role=request.user.role,
                action=audit_action,
                module="Admin Walk-in Management",
                ip_address=get_client_ip(request),
                details={
                    "job_id": str(job.id),
                    "title": job.title,
                    "organization": job.company.name,
                    "action": action,
                    "walkin_start_date": str(job.walkin_start_date),
                }
            )

            if action == "publish":
                messages.success(
                    request,
                    f"Walk-in vacancy '{job.title}' for {job.company.name} published successfully! "
                    f"It is now live on the site and immediately selectable in Bulk Job Alerts."
                )
            else:
                messages.success(
                    request,
                    f"Walk-in vacancy '{job.title}' saved as draft. You can publish it whenever ready."
                )

            return redirect("admin-panel:walk-ins")

        companies = Company.objects.all().order_by("name")
        return render(request, self.template_name, {
            "form": form,
            "is_edit": False,
            "companies": companies,
        })


class AdminWalkInUpdateView(AdminMixin, View):
    """
    Edit view for existing walk-in vacancies.
    Allows updating dates, venue, instructions, and lifecycle state.
    """
    template_name = "dashboard/admin/walkins/form.html"
    sidebar_section = "admin_walkins"

    def get(self, request: HttpRequest, job_id: str) -> HttpResponse:
        job = get_object_or_404(Job, pk=job_id, is_walkin=True)
        form = AdminWalkInJobForm(instance=job)
        companies = Company.objects.all().order_by("name")
        return render(request, self.template_name, {
            "form": form,
            "is_edit": True,
            "job": job,
            "companies": companies,
        })

    def post(self, request: HttpRequest, job_id: str) -> HttpResponse:
        job = get_object_or_404(Job, pk=job_id, is_walkin=True)
        action = request.POST.get("action", "publish" if job.is_published else "draft").strip().lower()
        if action not in ("publish", "draft"):
            action = "publish"

        form = AdminWalkInJobForm(request.POST, instance=job, action=action)
        if form.is_valid():
            job = form.save(user=request.user, action=action)

            AuditLog.objects.create(
                user=request.user,
                role=request.user.role,
                action="Walk-in Updated",
                module="Admin Walk-in Management",
                ip_address=get_client_ip(request),
                details={
                    "job_id": str(job.id),
                    "title": job.title,
                    "action": action,
                }
            )

            messages.success(request, f"Walk-in vacancy '{job.title}' updated successfully.")
            return redirect("admin-panel:walk-ins")

        companies = Company.objects.all().order_by("name")
        return render(request, self.template_name, {
            "form": form,
            "is_edit": True,
            "job": job,
            "companies": companies,
        })


class AdminWalkInDetailView(AdminMixin, View):
    """
    Inspect detailed walk-in information, matching candidate count,
    and attendance instructions. Supports JSON output for quick preview modals.
    """
    def get(self, request: HttpRequest, job_id: str) -> HttpResponse:
        job = get_object_or_404(Job.objects.select_related("company", "recruiter__user"), pk=job_id, is_walkin=True)
        match_count = CandidateJobAlertMatchingService.count_matching_candidates_for_walkin(job)

        start_str = job.walkin_start_date.strftime("%b %d, %Y") if job.walkin_start_date else ""
        end_str = f" to {job.walkin_end_date.strftime('%b %d, %Y')}" if job.walkin_end_date and job.walkin_end_date != job.walkin_start_date else ""

        payload = {
            "id": str(job.id),
            "title": job.title,
            "organization": job.company.name if job.company else "Direct Institution",
            "subject": job.metadata.get("subject", "") if job.metadata else "",
            "dates": f"{start_str}{end_str}",
            "time": job.walkin_time,
            "venue": job.walkin_venue,
            "location": job.location,
            "instructions": job.walkin_contact_instructions,
            "status": job.status,
            "is_published": job.is_published,
            "match_count": match_count,
            "salary": f"₹{job.salary_min:,} - ₹{job.salary_max:,}" if job.salary_min and job.salary_max else "Competitive / Undisclosed",
            "experience": f"{job.min_experience_years} - {job.max_experience_years or 'Any'} Yrs",
            "vacancies": job.vacancies,
            "contact_person": job.metadata.get("contact_person", "") if job.metadata else "",
            "contact_phone": job.metadata.get("contact_phone", "") if job.metadata else "",
            "alert_url": f"{reverse('admin-panel:bulk-job-alerts')}?alert_type=walkin_alert&walkin_id={job.id}",
            "public_url": f"/jobs/{job.slug}/" if job.slug else "#",
        }
        return JsonResponse({"status": "success", "walkin": payload})


class AdminWalkInStatusActionView(AdminMixin, View):
    """
    Action dispatcher for walk-in lifecycle transitions:
    publish, unpublish, cancel.
    """
    def post(self, request: HttpRequest, job_id: str) -> HttpResponse:
        job = get_object_or_404(Job, pk=job_id, is_walkin=True)
        action = request.POST.get("action", "").strip().lower()
        today = timezone.now().date()
        meta = dict(job.metadata or {})

        is_ajax = (
            request.headers.get("x-requested-with") == "XMLHttpRequest" or
            request.content_type == "application/json"
        )

        if action == "publish":
            # Guard against publishing past events
            if job.walkin_end_date and job.walkin_end_date < today:
                msg = "Cannot publish a past walk-in event. Please edit the walk-in date first."
                if is_ajax:
                    return JsonResponse({"status": "error", "message": msg}, status=400)
                messages.error(request, msg)
                return redirect("admin-panel:walk-ins")

            job.status = Job.Status.ACTIVE
            job.approval_status = Job.ApprovalStatus.APPROVED
            job.is_active = True
            job.published_at = job.published_at or timezone.now()
            job.reviewed_by = request.user
            job.reviewed_at = timezone.now()
            meta["walkin_status"] = "published"
            job.metadata = meta
            job.save()

            AuditLog.objects.create(
                user=request.user,
                role=request.user.role,
                action="Walk-in Published",
                module="Admin Walk-in Management",
                ip_address=get_client_ip(request),
                details={"job_id": str(job.id), "title": job.title}
            )

            msg = f"Walk-in '{job.title}' published successfully! It is now live and selectable in Bulk Job Alerts."
            if is_ajax:
                return JsonResponse({"status": "success", "message": msg})
            messages.success(request, msg)

        elif action == "unpublish":
            job.status = Job.Status.DRAFT
            job.approval_status = Job.ApprovalStatus.PENDING
            meta["walkin_status"] = "draft"
            job.metadata = meta
            job.save(update_fields=["status", "approval_status", "metadata"])

            AuditLog.objects.create(
                user=request.user,
                role=request.user.role,
                action="Walk-in Unpublished",
                module="Admin Walk-in Management",
                ip_address=get_client_ip(request),
                details={"job_id": str(job.id), "title": job.title}
            )

            msg = f"Walk-in '{job.title}' unpublished and moved to Draft."
            if is_ajax:
                return JsonResponse({"status": "success", "message": msg})
            messages.success(request, msg)

        elif action == "cancel":
            job.status = Job.Status.CLOSED
            job.is_active = False
            meta["walkin_status"] = "cancelled"
            meta["cancelled_at"] = timezone.now().isoformat()
            meta["cancelled_by"] = request.user.email
            job.metadata = meta
            job.save(update_fields=["status", "is_active", "metadata"])

            AuditLog.objects.create(
                user=request.user,
                role=request.user.role,
                action="Walk-in Cancelled",
                module="Admin Walk-in Management",
                ip_address=get_client_ip(request),
                details={"job_id": str(job.id), "title": job.title}
            )

            msg = f"Walk-in '{job.title}' has been cancelled."
            if is_ajax:
                return JsonResponse({"status": "success", "message": msg})
            messages.success(request, msg)

        else:
            msg = f"Unknown action '{action}'."
            if is_ajax:
                return JsonResponse({"status": "error", "message": msg}, status=400)
            messages.error(request, msg)

        return redirect("admin-panel:walk-ins")
