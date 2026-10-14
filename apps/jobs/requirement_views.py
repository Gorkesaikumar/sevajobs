"""
SevaJobs — Institution Requirement Submission & End-to-End Workflow Views.
"""

import json
from datetime import timedelta
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views import View
from django.http import JsonResponse, HttpResponseForbidden
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from django.core.paginator import Paginator
from django.db import transaction, models

from apps.jobs.models import (
    InstitutionRequirement,
    RequirementCandidateMatch,
    RequirementActivityLog,
    RequirementInternalNote,
    Job,
)
from apps.jobs.requirement_services import (
    RequirementWorkflowService,
    RequirementAssignmentService,
    RequirementConversionService,
    RequirementPipelineIntegrationService,
)
from apps.jobs.matching_service import CandidateMatchingService
from apps.jobs.tasks import process_requirement_matching_task
from apps.accounts.models import User
from apps.core.validators import SafeFileValidator

logo_validator = SafeFileValidator(max_size_mb=2, allowed_extensions=['.jpg', '.jpeg', '.png', '.webp'])


class SubmitRequirementView(View):
    """
    Public / Recruiter quick requirement submission endpoint (<30 seconds).
    Validates input server-side, checks duplicate submissions, queues async matching, and returns status.
    """

    @method_decorator(csrf_protect)
    def post(self, request, *args, **kwargs):
        if request.content_type == "application/json":
            try:
                data = json.loads(request.body.decode("utf-8"))
            except Exception:
                data = {}
        else:
            data = request.POST
        files = request.FILES

        institution_name = str(data.get("institution_name", "")).strip()
        phone_number = str(data.get("contact_phone") or data.get("phone_number") or "").strip()
        subject = str(data.get("subject", "")).strip()
        qualification = str(data.get("qualification", "")).strip()
        teaching_grade = str(data.get("teaching_grade", "PRT")).strip()
        location = str(data.get("location", "")).strip()
        positions_count = str(data.get("positions_count") or data.get("positions") or "1").strip()
        experience_range = str(data.get("experience_range") or data.get("experience") or "1-3").strip()
        salary_min = str(data.get("salary_min") or data.get("min_salary") or "").strip()
        salary_max = str(data.get("salary_max") or data.get("max_salary") or "").strip()
        salary_period = str(data.get("salary_period", "monthly")).strip()

        # 1. Validation
        if not institution_name or len(institution_name) < 2:
            return JsonResponse({"status": "error", "message": "Valid Institution name is required."}, status=400)
        
        clean_phone = "".join(filter(str.isdigit, phone_number))
        if not clean_phone or len(clean_phone) < 10 or len(clean_phone) > 15:
            return JsonResponse({"status": "error", "message": "Please enter a valid 10-15 digit mobile number."}, status=400)

        if not subject:
            return JsonResponse({"status": "error", "message": "Subject is required."}, status=400)

        if not qualification:
            return JsonResponse({"status": "error", "message": "Qualification is required."}, status=400)

        if not location:
            return JsonResponse({"status": "error", "message": "Location is required."}, status=400)

        try:
            positions = int(positions_count)
            if positions < 1:
                positions = 1
        except ValueError:
            positions = 1

        sal_min = int(salary_min) if salary_min.isdigit() else None
        sal_max = int(salary_max) if salary_max.isdigit() else None

        if sal_min and sal_max and sal_max < sal_min:
            return JsonResponse({"status": "error", "message": "Maximum salary cannot be less than minimum salary."}, status=400)

        logo_file = files.get("logo")
        if logo_file:
            try:
                logo_validator(logo_file)
            except Exception as e:
                return JsonResponse({"status": "error", "message": f"Invalid logo image: {e}"}, status=400)

        # 2. Duplicate Check (within 10 mins)
        ten_minutes_ago = timezone.now() - timedelta(minutes=10)
        duplicate = InstitutionRequirement.objects.filter(
            phone_number=clean_phone,
            institution_name__iexact=institution_name,
            subject__iexact=subject,
            location__iexact=location,
            created_at__gte=ten_minutes_ago,
        ).first()

        if duplicate:
            return JsonResponse({
                "status": "success",
                "success": True,
                "duplicate": True,
                "message": "Requirement already submitted recently! We are currently matching candidates.",
                "requirement_id": str(duplicate.id),
                "req_code": duplicate.req_code,
                "redirect_url": f"/dashboard/recruiter/requirements/{duplicate.id}/" if (request.user.is_authenticated and request.user.is_recruiter) else None
            }, status=200)

        # 3. Create Requirement Instance
        recruiter_profile = getattr(request.user, "recruiter_profile", None) if request.user.is_authenticated else None
        company = recruiter_profile.company if recruiter_profile else None

        min_exp = 0
        max_exp = None
        if "-" in experience_range:
            parts = experience_range.split("-")
            if parts[0].isdigit(): min_exp = int(parts[0])
            if parts[1].isdigit(): max_exp = int(parts[1])
        elif experience_range.startswith("10"):
            min_exp = 10
        elif experience_range.lower() == "fresher":
            min_exp = 0
            max_exp = 1

        with transaction.atomic():
            requirement = InstitutionRequirement.objects.create(
                recruiter=recruiter_profile,
                company=company,
                posted_by_user=request.user if request.user.is_authenticated else None,
                institution_name=institution_name,
                phone_number=clean_phone,
                subject=subject,
                qualification=qualification,
                teaching_grade=teaching_grade,
                positions_count=positions,
                location=location,
                experience_range=experience_range,
                min_experience_years=min_exp,
                max_experience_years=max_exp,
                salary_min=sal_min,
                salary_max=sal_max,
                salary_period=salary_period,
                logo=logo_file,
                status=InstitutionRequirement.RequirementStatus.SUBMITTED
            )
            RequirementWorkflowService.submit(requirement, actor=request.user if request.user.is_authenticated else None)

            # Trigger Candidate Matching (Immediate synchronous call + async Celery dispatch)
            matches = CandidateMatchingService.find_and_store_matches(requirement)
            match_count = len(matches)
            RequirementWorkflowService.update_matching_status(requirement, match_count=match_count)

            try:
                transaction.on_commit(lambda: process_requirement_matching_task.delay(str(requirement.id)))
            except Exception:
                pass

        redirect_url = None
        if request.user.is_authenticated and (request.user.is_recruiter or request.user.is_staff):
            redirect_url = f"/dashboard/recruiter/requirements/{requirement.id}/"

        return JsonResponse({
            "status": "success",
            "message": f"Requirement submitted successfully! Reference Code: {requirement.req_code}.",
            "requirement_id": str(requirement.id),
            "req_code": requirement.req_code,
            "match_count": match_count,
            "redirect_url": redirect_url
        }, status=201)


class RequirementAdminQueueView(LoginRequiredMixin, View):
    """
    Internal Admin & Recruiter Queue view for managing submitted teaching requirements.
    Supports pagination, multi-field search, and status filters.
    """

    def get(self, request, *args, **kwargs):
        is_staff = request.user.is_staff or request.user.is_superuser or (getattr(request.user, "role", "") in ["staff", "admin", "super_admin"])
        if not (is_staff or request.user.is_recruiter):
            return HttpResponseForbidden("You do not have permission to view requirements.")

        qs = InstitutionRequirement.objects.all().select_related("assigned_staff", "posted_by_user", "company", "converted_job")

        if not is_staff:
            # Recruiter sees own requirements
            qs = qs.filter(
                models.Q(posted_by_user=request.user) |
                models.Q(recruiter__user=request.user)
            )

        # Filters
        status_filter = request.GET.get("status")
        subject_filter = request.GET.get("subject")
        grade_filter = request.GET.get("grade")
        assigned_filter = request.GET.get("assigned_to")
        priority_filter = request.GET.get("priority")
        q = request.GET.get("q", "").strip()

        if status_filter:
            qs = qs.filter(status=status_filter)
        if subject_filter:
            qs = qs.filter(subject__icontains=subject_filter)
        if grade_filter:
            qs = qs.filter(teaching_grade=grade_filter)
        if assigned_filter == "unassigned":
            qs = qs.filter(assigned_staff__isnull=True)
        elif assigned_filter == "me":
            qs = qs.filter(assigned_staff=request.user)
        elif assigned_filter and assigned_filter.isdigit():
            qs = qs.filter(assigned_staff_id=assigned_filter)
        if priority_filter:
            qs = qs.filter(priority=priority_filter)

        if q:
            qs = qs.filter(
                models.Q(institution_name__icontains=q) |
                models.Q(subject__icontains=q) |
                models.Q(location__icontains=q) |
                models.Q(phone_number__icontains=q) |
                models.Q(id__icontains=q)
            )

        # Metrics overview counters
        total_count = qs.count()
        new_count = InstitutionRequirement.objects.filter(status=InstitutionRequirement.RequirementStatus.SUBMITTED).count()
        assigned_count = InstitutionRequirement.objects.filter(status=InstitutionRequirement.RequirementStatus.ASSIGNED).count()
        in_progress_count = InstitutionRequirement.objects.filter(status=InstitutionRequirement.RequirementStatus.IN_PROGRESS).count()
        fulfilled_count = InstitutionRequirement.objects.filter(status=InstitutionRequirement.RequirementStatus.FULFILLED).count()

        paginator = Paginator(qs, 15)
        page_number = request.GET.get("page")
        page_obj = paginator.get_page(page_number)

        staff_list = User.objects.filter(role__in=["staff", "admin", "super_admin"]).order_by("first_name", "email")

        layout_template = getattr(request, "layout_template", "dashboard/recruiter/_layout.html")
        context = {
            "layout_template": layout_template,
            "page_obj": page_obj,
            "requirements": page_obj.object_list,
            "total_count": total_count,
            "new_count": new_count,
            "assigned_count": assigned_count,
            "in_progress_count": in_progress_count,
            "fulfilled_count": fulfilled_count,
            "staff_list": staff_list,
            "selected_status": status_filter,
            "selected_subject": subject_filter,
            "selected_grade": grade_filter,
            "selected_assigned": assigned_filter,
            "selected_priority": priority_filter,
            "search_query": q,
            "status_choices": InstitutionRequirement.RequirementStatus.choices,
            "grade_choices": InstitutionRequirement.TeachingGrade.choices,
            "sidebar_section": getattr(request, "sidebar_section", "requirement-queue"),
        }
        return render(request, "dashboard/recruiter/requirement_queue.html", context)


def get_requirement_detail_redirect_url(request, pk):
    """
    Role-aware URL generator for requirement detail redirect after actions.
    Ensures Admin stays in Admin UI, Recruiter in Recruiter UI, and Staff in Staff UI.
    """
    from django.urls import reverse
    scope = request.session.get("current_role_scope")
    if scope == "admin" or (request.user.is_authenticated and (request.user.is_superuser or getattr(request.user, "role", "") in ["admin", "super_admin"])):
        return reverse("admin-panel:requirement-detail", kwargs={"pk": pk})
    elif scope == "recruiter" or (request.user.is_authenticated and getattr(request.user, "role", "") == "recruiter"):
        return reverse("recruiter:requirement-detail", kwargs={"pk": pk})
    return reverse("jobs:requirement-detail", kwargs={"pk": pk})


class RequirementDetailView(LoginRequiredMixin, View):
    """
    Detailed Requirement view displaying status, candidate funnel, matched candidates,
    activity timeline, and internal notes. Role-aware shell architecture.
    """

    def get(self, request, pk, *args, **kwargs):
        from django.urls import reverse
        requirement = get_object_or_404(
            InstitutionRequirement.objects.select_related("assigned_staff", "assigned_by", "converted_job"),
            pk=pk
        )

        scope = request.session.get("current_role_scope")
        is_admin_user = (scope == "admin" and (request.user.is_admin_role or request.user.is_superuser)) or request.user.is_superuser or getattr(request.user, "role", "") in ["admin", "super_admin"]
        is_staff_user = (scope == "staff" or getattr(request.user, "role", "") == "staff" or request.user.is_staff) and not is_admin_user
        
        # Object-level permission check: Admin, Staff, or Requirement Owner / Company
        recruiter_profile = getattr(request.user, "recruiter_profile", None)
        user_company = recruiter_profile.company if recruiter_profile else None
        is_owner = (
            (requirement.posted_by_user == request.user) or
            (requirement.recruiter and requirement.recruiter.user == request.user) or
            (user_company and requirement.company == user_company)
        )

        if not (is_admin_user or is_staff_user or is_owner):
            return HttpResponseForbidden("You do not have permission to view this requirement.")

        def _safe_reverse(name, fallback_name):
            try:
                return reverse(name)
            except Exception:
                return reverse(fallback_name)

        # Determine Role-aware Navigation Layout & Sidebar Context
        if is_admin_user:
            layout_template = getattr(request, "layout_template", "dashboard/admin/_layout.html")
            sidebar_section = getattr(request, "sidebar_section", "admin_requirements")
            back_to_queue_url = getattr(request, "back_to_queue_url", _safe_reverse("admin-panel:requirements", "jobs:requirement-queue"))
        elif is_staff_user:
            layout_template = getattr(request, "layout_template", "dashboard/staff/_layout.html")
            sidebar_section = getattr(request, "sidebar_section", "requirements")
            back_to_queue_url = getattr(request, "back_to_queue_url", _safe_reverse("admin-panel:requirements", "jobs:requirement-queue"))
        else:
            layout_template = getattr(request, "layout_template", "dashboard/recruiter/_layout.html")
            sidebar_section = getattr(request, "sidebar_section", "requirements-list")
            back_to_queue_url = getattr(request, "back_to_queue_url", _safe_reverse("recruiter:requirements-list", "jobs:requirement-queue"))

        matches = requirement.candidate_matches.select_related("candidate", "candidate__job_seeker_profile").order_by("-match_score")
        activity_logs = requirement.activity_logs.select_related("actor").order_by("-created_at")[:50]
        internal_notes = requirement.internal_notes.select_related("author").order_by("-created_at") if (is_admin_user or is_staff_user) else []

        # Funnel counts
        matched_count = matches.count()
        shortlisted_count = matches.filter(status=RequirementCandidateMatch.MatchStatus.SHORTLISTED).count()
        interview_count = matches.filter(status=RequirementCandidateMatch.MatchStatus.INTERVIEW_SCHEDULED).count()
        selected_count = matches.filter(status=RequirementCandidateMatch.MatchStatus.SELECTED).count()
        joined_count = matches.filter(status=RequirementCandidateMatch.MatchStatus.JOINED).count()

        staff_list = User.objects.filter(role__in=["staff", "admin", "super_admin"], is_active=True).order_by("first_name", "email") if (is_admin_user or is_staff_user) else []

        context = {
            "requirement": requirement,
            "matches": matches,
            "activity_logs": activity_logs,
            "internal_notes": internal_notes,
            "matched_count": matched_count,
            "shortlisted_count": shortlisted_count,
            "interview_count": interview_count,
            "selected_count": selected_count,
            "joined_count": joined_count,
            "staff_list": staff_list,
            "is_staff": is_admin_user or is_staff_user,
            "layout_template": layout_template,
            "sidebar_section": sidebar_section,
            "back_to_queue_url": back_to_queue_url,
        }
        return render(request, "dashboard/recruiter/requirement_detail_workflow.html", context)


class RequirementAssignView(LoginRequiredMixin, View):
    """
    Assign requirement to staff member.
    """

    def post(self, request, pk, *args, **kwargs):
        is_staff = request.user.is_staff or request.user.is_superuser or (getattr(request.user, "role", "") in ["staff", "admin", "super_admin"])
        if not is_staff:
            return HttpResponseForbidden("Only staff or admin can assign requirements.")

        requirement = get_object_or_404(InstitutionRequirement, pk=pk)
        staff_id = request.POST.get("staff_id")
        priority = request.POST.get("priority", "normal")
        notes = request.POST.get("notes", "")

        staff_user = get_object_or_404(User, pk=staff_id)
        if not staff_user.is_active or getattr(staff_user, "role", "") not in ["staff", "admin", "super_admin"]:
            messages.error(request, "Selected employee is inactive or unauthorized for assignment.")
            return redirect(get_requirement_detail_redirect_url(request, pk))

        RequirementAssignmentService.assign_employee(
            requirement_id=requirement.pk,
            staff_user=staff_user,
            assigned_by_user=request.user,
            priority=priority,
            notes=notes,
        )

        messages.success(request, f"Requirement assigned to {staff_user.get_full_name() or staff_user.email} successfully.")
        return redirect(get_requirement_detail_redirect_url(request, pk))


class RequirementStartWorkView(LoginRequiredMixin, View):
    """
    Assigned staff starts working on requirement.
    """

    def post(self, request, pk, *args, **kwargs):
        requirement = get_object_or_404(InstitutionRequirement, pk=pk)
        is_staff = request.user.is_staff or request.user.is_superuser or (getattr(request.user, "role", "") in ["staff", "admin", "super_admin"])
        if not (is_staff or requirement.assigned_staff == request.user):
            return HttpResponseForbidden("Permission denied.")

        RequirementWorkflowService.start_work(requirement, actor=request.user)
        messages.success(request, "Work started on this requirement.")
        return redirect(get_requirement_detail_redirect_url(request, pk))


class RequirementConvertJobView(LoginRequiredMixin, View):
    """
    Converts requirement to a formal Job draft.
    """

    def post(self, request, pk, *args, **kwargs):
        requirement = get_object_or_404(InstitutionRequirement, pk=pk)
        is_staff = request.user.is_staff or request.user.is_superuser or (getattr(request.user, "role", "") in ["staff", "admin", "super_admin"])
        is_owner = (requirement.posted_by_user == request.user) or (requirement.recruiter and requirement.recruiter.user == request.user)
        if not (is_staff or is_owner):
            return HttpResponseForbidden("Permission denied.")

        job = RequirementConversionService.convert_to_job_draft(requirement.pk, actor=request.user)
        messages.success(request, f"Requirement converted to Job Draft '{job.title}'.")
        return redirect(get_requirement_detail_redirect_url(request, pk))


class RequirementCandidateActionView(LoginRequiredMixin, View):
    """
    Handles shortlist, schedule interview, select, join, and reject actions on candidate matches.
    """

    def post(self, request, pk, match_id, *args, **kwargs):
        requirement = get_object_or_404(InstitutionRequirement, pk=pk)
        match = get_object_or_404(RequirementCandidateMatch, pk=match_id, requirement=requirement)

        is_staff = request.user.is_staff or request.user.is_superuser or (getattr(request.user, "role", "") in ["staff", "admin", "super_admin"])
        is_owner = (requirement.posted_by_user == request.user) or (requirement.recruiter and requirement.recruiter.user == request.user)
        if not (is_staff or is_owner):
            return HttpResponseForbidden("Permission denied.")

        action = request.POST.get("action")
        reason = request.POST.get("reason", "")

        try:
            if action == "shortlist":
                RequirementPipelineIntegrationService.shortlist_candidate(match.pk, actor=request.user)
                messages.success(request, f"{match.candidate.get_full_name() or match.candidate.email} shortlisted successfully.")
            elif action == "schedule_interview":
                interview_date = request.POST.get("interview_date", "")
                interview_time = request.POST.get("interview_time", "")
                interview_mode = request.POST.get("interview_mode", "Online")
                interview_details = {
                    "date": interview_date,
                    "time": interview_time,
                    "mode": interview_mode,
                    "notes": request.POST.get("interview_notes", "")
                }
                RequirementPipelineIntegrationService.schedule_interview(match.pk, actor=request.user, interview_details=interview_details)
                messages.success(request, f"Interview scheduled for {match.candidate.get_full_name() or match.candidate.email}.")
            elif action == "select":
                RequirementPipelineIntegrationService.mark_selected(match.pk, actor=request.user)
                messages.success(request, f"{match.candidate.get_full_name() or match.candidate.email} marked as Selected.")
            elif action == "join":
                RequirementPipelineIntegrationService.mark_joined(match.pk, actor=request.user)
                messages.success(request, f"{match.candidate.get_full_name() or match.candidate.email} marked as Joined.")
            elif action == "reject":
                RequirementPipelineIntegrationService.reject_candidate(match.pk, actor=request.user, reason=reason)
                messages.info(request, f"{match.candidate.get_full_name() or match.candidate.email} rejected.")
        except Exception as e:
            messages.error(request, str(e))

        return redirect(get_requirement_detail_redirect_url(request, pk))


class RequirementInternalNoteView(LoginRequiredMixin, View):
    """
    Adds an internal note to a requirement.
    """

    def post(self, request, pk, *args, **kwargs):
        is_staff = request.user.is_staff or request.user.is_superuser or (getattr(request.user, "role", "") in ["staff", "admin", "super_admin"])
        if not is_staff:
            return HttpResponseForbidden("Only staff or admin can add internal notes.")

        requirement = get_object_or_404(InstitutionRequirement, pk=pk)
        body = request.POST.get("body", "").strip()

        if body:
            RequirementInternalNote.objects.create(
                requirement=requirement,
                author=request.user,
                body=body
            )
            RequirementWorkflowService.log_activity(
                requirement=requirement,
                event_type=RequirementActivityLog.EventType.NOTE_ADDED,
                description=f"Internal note added by {request.user.get_full_name() or request.user.email}.",
                actor=request.user,
            )
            messages.success(request, "Internal note added.")

        return redirect(get_requirement_detail_redirect_url(request, pk))


class RequirementCandidateInterviewView(LoginRequiredMixin, View):
    """
    Dedicated view for scheduling/viewing an interview for a shortlisted requirement candidate.
    """

    def get(self, request, pk, match_id, *args, **kwargs):
        requirement = get_object_or_404(InstitutionRequirement, pk=pk)
        match = get_object_or_404(
            RequirementCandidateMatch.objects.select_related("candidate", "requirement"),
            pk=match_id,
            requirement=requirement,
        )

        is_staff = request.user.is_staff or request.user.is_superuser or (getattr(request.user, "role", "") in ["staff", "admin", "super_admin"])
        is_owner = (requirement.posted_by_user == request.user) or (requirement.recruiter and requirement.recruiter.user == request.user)
        if not (is_staff or is_owner):
            return HttpResponseForbidden("Permission denied.")

        if match.status not in [
            RequirementCandidateMatch.MatchStatus.SHORTLISTED,
            RequirementCandidateMatch.MatchStatus.INTERVIEW_SCHEDULED,
            RequirementCandidateMatch.MatchStatus.SELECTED,
            RequirementCandidateMatch.MatchStatus.JOINED,
        ]:
            messages.error(request, "Candidate must be shortlisted before scheduling an interview.")
            return redirect(get_requirement_detail_redirect_url(request, pk))

        is_admin_user = (request.user.is_superuser or getattr(request.user, "role", "") in ["admin", "super_admin"])
        is_staff_user = (request.user.is_staff or getattr(request.user, "role", "") == "staff")

        if is_admin_user:
            layout_template = getattr(request, "layout_template", "dashboard/admin/_layout.html")
            sidebar_section = getattr(request, "sidebar_section", "admin_requirements")
            back_to_requirement_url = getattr(request, "back_to_requirement_url", reverse("admin-panel:requirement-detail", kwargs={"pk": requirement.pk}))
        elif is_staff_user:
            layout_template = getattr(request, "layout_template", "dashboard/staff/_layout.html")
            sidebar_section = getattr(request, "sidebar_section", "requirements")
            back_to_requirement_url = getattr(request, "back_to_requirement_url", reverse("admin-panel:requirement-detail", kwargs={"pk": requirement.pk}))
        else:
            layout_template = getattr(request, "layout_template", "dashboard/recruiter/_layout.html")
            sidebar_section = getattr(request, "sidebar_section", "requirements-list")
            back_to_requirement_url = getattr(request, "back_to_requirement_url", reverse("recruiter:requirement-detail", kwargs={"pk": requirement.pk}))

        return render(
            request,
            "dashboard/recruiter/requirement_schedule_interview.html",
            {
                "requirement": requirement,
                "match": match,
                "candidate": match.candidate,
                "allowed_actions": match.allowed_actions,
                "layout_template": layout_template,
                "sidebar_section": sidebar_section,
                "back_to_requirement_url": back_to_requirement_url,
                "is_admin_user": is_admin_user,
            },
        )

    def post(self, request, pk, match_id, *args, **kwargs):
        requirement = get_object_or_404(InstitutionRequirement, pk=pk)
        match = get_object_or_404(RequirementCandidateMatch, pk=match_id, requirement=requirement)

        is_staff = request.user.is_staff or request.user.is_superuser or (getattr(request.user, "role", "") in ["staff", "admin", "super_admin"])
        is_owner = (requirement.posted_by_user == request.user) or (requirement.recruiter and requirement.recruiter.user == request.user)
        if not (is_staff or is_owner):
            return HttpResponseForbidden("Permission denied.")

        interview_date = request.POST.get("interview_date", "").strip()
        interview_time = request.POST.get("interview_time", "").strip()
        interview_mode = request.POST.get("interview_mode", "Online").strip()
        location_or_link = request.POST.get("location_or_link", "").strip()
        interviewer_name = request.POST.get("interviewer_name", "").strip()
        notes = request.POST.get("interview_notes", "").strip()

        interview_details = {
            "date": interview_date,
            "time": interview_time,
            "mode": interview_mode,
            "location_or_link": location_or_link,
            "interviewer_name": interviewer_name,
            "notes": notes,
        }

        try:
            RequirementPipelineIntegrationService.schedule_interview(
                match.pk, actor=request.user, interview_details=interview_details
            )
            messages.success(request, f"Interview scheduled successfully for {match.candidate.get_full_name() or match.candidate.email}.")
        except Exception as e:
            messages.error(request, str(e))

        redirect_url = getattr(request, "back_to_requirement_url", get_requirement_detail_redirect_url(request, pk))
        return redirect(f"{redirect_url}#candidate-matches")



