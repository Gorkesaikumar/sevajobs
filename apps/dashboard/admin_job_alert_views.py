"""
Admin views for SevaJobs Bulk Job Alerts Based on Candidate Professional Profiles.
Provides a dedicated 4-step wizard workflow, real-time candidate evaluation, live vacancy matching,
email preview, test dispatch, campaign tracking, and failure retry management.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from apps.accounts.models import AuditLog, JobSeekerProfile, User
from apps.accounts.middleware import get_client_ip
from apps.jobs.models import Job, InstitutionRequirement
from apps.jobs.job_alert_matching_service import CandidateJobAlertMatchingService
from apps.notifications.default_templates import DEFAULT_JOB_ALERT_TEMPLATE, FIVE_ALERT_TEMPLATES
from apps.notifications.job_alert_service import JobAlertCampaignService
from apps.notifications.models import (
    CandidateJobAlertDelivery,
    JobAlertCampaign,
    JobAlertRecipient,
)
from apps.notifications.quota_service import DailyEmailQuotaService
from apps.notifications.unsubscribe_service import (
    JobAlertPreferenceService,
    UnsubscribeService,
)

from .admin_views import AdminMixin

logger = logging.getLogger("apps.notifications")


class AdminBulkJobAlertsView(AdminMixin, View):
    """
    Dedicated 4-Step Job Alert Campaign Creation Workflow supporting all 5 Alert Types:
    1. Daily Job Alert — General (Scheduled at 10:00 AM IST)
    2. Interview Alert — Personal (Priority 1)
    3. Walk-in Alert — Urgent (Priority 2)
    4. Employer Alert — For Earning (Priority 5)
    5. VIP Requirement Alert (Priority 3)
    """

    sidebar_section = "users"

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        quota_status = DailyEmailQuotaService.get_quota_status()

        # Gather distinct filter options from candidate profiles
        available_subjects = sorted(
            list(
                set(
                    JobSeekerProfile.objects.exclude(subject__isnull=True)
                    .exclude(subject="")
                    .values_list("subject", flat=True)
                )
            )
        )
        common_subjects = [
            "English", "Mathematics", "Physics", "Chemistry", "Biology",
            "Computer Science", "Social Studies", "Hindi", "Tamil", "Science",
            "Commerce", "Economics", "Physical Education", "Music", "Art",
        ]
        all_subjects = sorted(list(set(available_subjects + common_subjects)))

        available_professions = sorted(
            list(
                set(
                    JobSeekerProfile.objects.exclude(designation__isnull=True)
                    .exclude(designation="")
                    .values_list("designation", flat=True)
                )
            )
        )
        common_professions = [
            "Teacher", "PGT", "TGT", "PRT", "Primary Teacher", "High School Teacher",
            "Principal", "Vice Principal", "Academic Coordinator", "Lecturer",
            "Professor", "Physical Education Teacher (PET)", "Lab Assistant",
        ]
        all_professions = sorted(list(set(available_professions + common_professions)))

        common_locations = [
            "Chennai", "Coimbatore", "Madurai", "Tiruchirappalli", "Salem",
            "Erode", "Tirunelveli", "Vellore", "Bangalore", "Hyderabad", "Mumbai",
        ]

        # Retrieve available published vacancies for manual selection mode
        active_vacancies = CandidateJobAlertMatchingService.get_public_vacancies()[:50]
        # Retrieve walk-in vacancies
        walkin_vacancies = CandidateJobAlertMatchingService.get_walkin_vacancies()
        # Retrieve active institutional requirements
        active_requirements = CandidateJobAlertMatchingService.get_active_requirements()
        # Daily 10:00 AM IST schedule active status
        is_schedule_enabled = JobAlertCampaignService.is_daily_schedule_enabled()

        context = {
            "quota_status": quota_status,
            "all_subjects": all_subjects,
            "all_professions": all_professions,
            "common_locations": common_locations,
            "active_vacancies": active_vacancies,
            "walkin_vacancies": walkin_vacancies,
            "active_requirements": active_requirements,
            "is_schedule_enabled": is_schedule_enabled,
            "five_templates": FIVE_ALERT_TEMPLATES,
            "five_templates_json": json.dumps(FIVE_ALERT_TEMPLATES),
            "default_template": DEFAULT_JOB_ALERT_TEMPLATE,
            "sidebar_section": "users",
        }
        return render(request, "dashboard/admin/bulk_job_alerts.html", context)

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        try:
            if request.content_type == "application/json":
                data = json.loads(request.body.decode("utf-8"))
            else:
                data = request.POST.dict()
        except Exception:
            return JsonResponse({"status": "error", "message": "Invalid JSON or request body."}, status=400)

        action = data.get("action", "").strip()

        # ── ACTION 0: TOGGLE 10 AM DAILY SCHEDULE ────────────────────────────
        if action == "toggle_schedule":
            new_state = not JobAlertCampaignService.is_daily_schedule_enabled()
            JobAlertCampaignService.set_daily_schedule_enabled(new_state)
            AuditLog.objects.create(
                user=request.user,
                role=getattr(request.user, "role", "admin"),
                action=f"Daily Job Alert Schedule {'Resumed' if new_state else 'Paused'}",
                module="Bulk Job Alerts",
                ip_address=get_client_ip(request),
                details={"is_enabled": new_state},
            )
            return JsonResponse({
                "status": "success",
                "is_enabled": new_state,
                "message": f"Daily 10:00 AM job alert schedule is now {'ACTIVE' if new_state else 'PAUSED'}."
            })

        # ── ACTION 1: CALCULATE AUDIENCE ─────────────────────────────────────
        elif action == "calculate_audience":
            return self._handle_calculate_audience(data)

        # ── ACTION 2: PREVIEW PERSONALIZED EMAIL ─────────────────────────────
        elif action == "preview_email":
            return self._handle_preview_email(data)

        # ── ACTION 3: SEND TEST EMAIL ─────────────────────────────────────────
        elif action == "send_test":
            return self._handle_send_test(request, data)

        # ── ACTION 4: CREATE & LAUNCH CAMPAIGN ───────────────────────────────
        elif action in ("create_campaign", "launch_campaign", "save_draft"):
            return self._handle_create_or_launch(request, data, is_draft=(action == "save_draft"))

        return JsonResponse({"status": "error", "message": f"Unsupported action: '{action}'"}, status=400)

    def _handle_calculate_audience(self, data: Dict[str, Any]) -> JsonResponse:
        """Evaluate real candidate or employer profiles against criteria and matching jobs."""
        alert_type = data.get("alert_type", "daily_digest").strip()
        subject = data.get("subject", "").strip()
        profession = data.get("profession", "").strip()
        location = data.get("location", "").strip()

        exp_min = data.get("experience_min")
        exp_max = data.get("experience_max")
        salary_min = data.get("salary_min")
        salary_max = data.get("salary_max")
        alerts_only = data.get("alerts_enabled_only", True)
        active_only = data.get("active_only", True)
        matching_strategy = data.get("matching_strategy", "auto")
        selected_job_ids = data.get("selected_job_ids", [])
        dedup_window_days = int(data.get("dedup_window_days", 14))
        walkin_job_id = data.get("walkin_job_id")
        requirement_id = data.get("requirement_id")
        candidate_status = data.get("candidate_status")
        account_type = data.get("account_type")

        filters = {
            "subject": subject,
            "profession": profession,
            "location": location,
            "experience_min": float(exp_min) if exp_min not in ("", None) else None,
            "experience_max": float(exp_max) if exp_max not in ("", None) else None,
            "salary_min": float(salary_min) if salary_min not in ("", None) else None,
            "salary_max": float(salary_max) if salary_max not in ("", None) else None,
            "alerts_enabled_only": bool(alerts_only),
            "active_only": bool(active_only),
            "status": candidate_status,
            "role": account_type,
        }

        specific_job_ids = selected_job_ids if matching_strategy == "specific_jobs" else None

        if alert_type in ("employer", "employer_alert"):
            eval_result = CandidateJobAlertMatchingService.evaluate_employer_audience(filters=filters)
        elif alert_type in ("interview", "interview_alert"):
            eval_result = CandidateJobAlertMatchingService.evaluate_interview_audience(filters=filters)
        elif alert_type in ("walkin", "walkin_alert"):
            eval_result = CandidateJobAlertMatchingService.evaluate_walkin_audience(
                walkin_job_id=walkin_job_id,
                filters=filters,
                dedup_window_days=dedup_window_days,
            )
        elif alert_type in ("requirement", "requirement_alert"):
            eval_result = CandidateJobAlertMatchingService.evaluate_requirement_audience(requirement_id=requirement_id, filters=filters)
        else:
            eval_result = CandidateJobAlertMatchingService.evaluate_audience(
                filters=filters,
                specific_job_ids=specific_job_ids,
                dedup_window_days=dedup_window_days,
            )

        quota_status = DailyEmailQuotaService.get_quota_status()

        # Format candidates for JSON serialization (remove User objects)
        serialized_candidates = []
        for cand in eval_result["candidates_review"]:
            serialized_candidates.append({
                "candidate_id": cand["candidate_id"],
                "name": cand["name"],
                "email": cand["email"],
                "profession": cand.get("profession", ""),
                "subject": cand.get("subject", ""),
                "location": cand.get("location", ""),
                "experience_years": cand.get("experience_years", 0),
                "expected_salary": cand.get("expected_salary"),
                "matched_job_count": len(cand.get("matched_jobs", [])),
                "matched_jobs": cand.get("matched_jobs", []),
                "is_eligible": cand.get("is_eligible", True),
                "exclusion_reason": cand.get("exclusion_reason", ""),
                "metadata": cand.get("metadata", {}),
            })

        return JsonResponse({
            "status": "success",
            "alert_type": alert_type,
            "total_job_seekers_found": eval_result.get("total_job_seekers_found", len(serialized_candidates)),
            "active_job_seekers": eval_result.get("active_job_seekers", len(serialized_candidates)),
            "with_valid_email": eval_result.get("with_valid_email", len(serialized_candidates)),
            "eligible_candidates_count": eval_result.get("eligible_candidates_count", len(serialized_candidates)),
            "matching_profiles_count": eval_result.get("matching_profiles_count", eval_result.get("eligible_candidates_count", 0)),
            "no_matching_jobs_count": eval_result.get("no_matching_jobs_count", 0),
            "excluded_count": eval_result.get("excluded_count", 0),
            "candidates": serialized_candidates,
            "quota_status": quota_status,
        })

    def _handle_preview_email(self, data: Dict[str, Any]) -> JsonResponse:
        """Render realistic personalized preview with live merge tags and alert context."""
        try:
            alert_type = data.get("alert_type", "daily_digest").strip()
            candidate_id = data.get("candidate_id", "").strip()
            walkin_job_id = data.get("walkin_job_id")
            requirement_id = data.get("requirement_id")
            matching_strategy = data.get("matching_strategy", "auto")
            selected_job_ids = data.get("selected_job_ids", [])

            default_tpl = FIVE_ALERT_TEMPLATES.get(alert_type, DEFAULT_JOB_ALERT_TEMPLATE)
            subject_tpl = data.get("subject", "").strip() or default_tpl["subject"]
            body_tpl = data.get("body_html", "").strip() or default_tpl["body_html"]

            walkin_job = Job.objects.filter(pk=walkin_job_id).first() if walkin_job_id else None
            requirement = InstitutionRequirement.objects.filter(pk=requirement_id).first() if requirement_id else None

            # Fallback if specific vacancy was not selected yet
            if not walkin_job and alert_type in ("walkin", "walkin_alert"):
                walkin_job = Job.objects.filter(is_walkin=True, is_active=True).first() or Job.objects.filter(is_walkin=True).first()

            if not requirement and alert_type in ("requirement", "requirement_alert"):
                requirement = (
                    InstitutionRequirement.objects.exclude(
                        status__in=[InstitutionRequirement.RequirementStatus.REJECTED, InstitutionRequirement.RequirementStatus.CLOSED]
                    ).first()
                    or InstitutionRequirement.objects.first()
                )

            mock_campaign = JobAlertCampaign(
                alert_type=alert_type,
                walkin_job=walkin_job,
                requirement=requirement,
                subject=subject_tpl,
                body_html=body_tpl,
            )

            user = None
            if candidate_id:
                user = User.objects.filter(pk=candidate_id).first()

            if user and user.role == "job_seeker":
                profile = getattr(user, "job_seeker_profile", None)
                cand_name = user.get_full_name() or user.username
                cand_prof = (profile.designation or "Teaching Professional") if profile else "Teaching Professional"
                cand_subj = (profile.subject or "English") if profile else "English"
                cand_email = user.email
                specific_jobs = selected_job_ids if matching_strategy == "specific_jobs" else None
                if alert_type in ("walkin", "walkin_alert") and walkin_job:
                    matched_jobs = [CandidateJobAlertMatchingService._format_walkin_dict(walkin_job)]
                else:
                    matched_jobs = CandidateJobAlertMatchingService.get_matching_jobs_for_candidate(
                        user, specific_job_ids=specific_jobs, limit=3
                    )
            elif user and user.role in ("recruiter", "school", "college", "company"):
                cand_name = user.get_full_name() or "Hiring Partner"
                cand_prof = "Recruitment Manager"
                cand_subj = ""
                cand_email = user.email
                matched_jobs = []
            else:
                cand_name = "Smrithi"
                cand_prof = "English Teacher"
                cand_subj = "English"
                cand_email = "candidate@example.com"
                if alert_type in ("walkin", "walkin_alert") and walkin_job:
                    matched_jobs = [CandidateJobAlertMatchingService._format_walkin_dict(walkin_job)]
                else:
                    matched_jobs = CandidateJobAlertMatchingService.get_public_vacancies()[:3]

            comp_name = (
                walkin_job.company.name if (walkin_job and getattr(walkin_job, "company", None))
                else (requirement.institution_name if requirement else "SevaJobs Model Academy")
            )

            mock_recipient = JobAlertRecipient(
                email=cand_email,
                recipient_name=cand_name,
                profession=cand_prof,
                subject=cand_subj,
                location="Chennai",
                matched_jobs_data=matched_jobs,
                metadata={
                    "role_title": walkin_job.title if walkin_job else "PGT English Teacher",
                    "requirement_title": walkin_job.title if walkin_job else "PGT English Teacher",
                    "institution_name": comp_name,
                    "organization_name": comp_name,
                    "school_name": comp_name,
                    "company_name": comp_name,
                    "status": "Interview Scheduled",
                    "candidate_status": "Interview Scheduled",
                    "interview_date": (timezone.now() + timezone.timedelta(days=2)).strftime("%b %d, %Y"),
                    "interview_time": "10:30 AM IST",
                    "venue_or_link": "Administrative Block, Campus Chennai",
                    "interview_type": "In-Person Demo",
                    "subject": requirement.subject if requirement else (cand_subj or "English"),
                    "grade_level": requirement.grade_level if requirement else "High School",
                    "location": "Chennai",
                    "walkin_date": "Today",
                    "walkin_venue": (walkin_job.walkin_venue if walkin_job and walkin_job.walkin_venue else "Campus Grounds"),
                },
            )

            context = JobAlertCampaignService.build_context_for_recipient(
                campaign=mock_campaign,
                recipient=mock_recipient,
                valid_jobs=matched_jobs,
            )

            rendered_subject = JobAlertCampaignService.render_content(body_template=subject_tpl, context=context)
            rendered_body = JobAlertCampaignService.render_content(body_template=body_tpl, context=context)
            wrapped_html = JobAlertCampaignService.wrap_in_base_email(
                rendered_body_html=rendered_body,
                subject=rendered_subject,
                unsubscribe_url=context["unsubscribe_url"],
                preferences_url=context["preferences_url"],
            )

            return JsonResponse({
                "status": "success",
                "rendered_subject": rendered_subject,
                "rendered_html": wrapped_html,
                "matched_job_count": len(matched_jobs),
                "preview_candidate_name": cand_name,
                "preview_candidate_profession": cand_prof,
            })
        except Exception as exc:
            logger.exception("Failed to generate live preview email: %s", exc)
            return JsonResponse({
                "status": "error",
                "message": f"Preview error: {exc}",
            }, status=400)

    def _handle_send_test(self, request: HttpRequest, data: Dict[str, Any]) -> JsonResponse:
        """Send a single live preview email to test administrator address."""
        alert_type = data.get("alert_type", "daily_digest").strip()
        test_email = data.get("test_email", "").strip()
        default_tpl = FIVE_ALERT_TEMPLATES.get(alert_type, DEFAULT_JOB_ALERT_TEMPLATE)
        subject = data.get("subject", "").strip() or default_tpl["subject"]
        body_html = data.get("body_html", "").strip() or default_tpl["body_html"]
        matching_strategy = data.get("matching_strategy", "auto")
        selected_job_ids = data.get("selected_job_ids", [])
        walkin_job_id = data.get("walkin_job_id")
        requirement_id = data.get("requirement_id")

        if not test_email or "@" not in test_email:
            return JsonResponse({"status": "error", "message": "Please provide a valid test recipient email."}, status=400)

        specific_jobs = selected_job_ids if matching_strategy == "specific_jobs" else None

        try:
            JobAlertCampaignService.send_test_email(
                admin_user=request.user,
                test_email=test_email,
                subject=subject,
                body_html=body_html,
                alert_type=alert_type,
                specific_job_ids=specific_jobs,
                walkin_job_id=walkin_job_id,
                requirement_id=requirement_id,
            )
            AuditLog.objects.create(
                user=request.user,
                role=getattr(request.user, "role", "admin"),
                action="Job Alert Test Sent",
                module="Bulk Job Alerts",
                ip_address=get_client_ip(request),
                details={"test_email": test_email, "subject": subject, "alert_type": alert_type},
            )
            return JsonResponse({"status": "success", "message": f"Test email sent to {test_email}."})
        except Exception as exc:
            logger.exception("Failed to send test job alert: %s", exc)
            return JsonResponse({"status": "error", "message": f"Error delivering test email: {exc}"}, status=400)

    def _handle_create_or_launch(self, request: HttpRequest, data: Dict[str, Any], is_draft: bool = False) -> JsonResponse:
        """Create campaign, record recipients with matching vacancy snapshots, and optionally queue for sending."""
        alert_type = data.get("alert_type", "daily_digest").strip()
        name = data.get("name", "").strip() or f"{alert_type.replace('_', ' ').title()} ({timezone.now().strftime('%b %d, %Y')})"
        subject = data.get("subject", "").strip()
        body_html = data.get("body_html", "").strip()
        matching_strategy = data.get("matching_strategy", "auto")
        selected_job_ids = data.get("selected_job_ids", [])
        targeting_criteria = data.get("targeting_criteria", {})
        candidate_ids = data.get("candidate_ids", [])
        walkin_job_id = data.get("walkin_job_id")
        requirement_id = data.get("requirement_id")
        is_recurring = bool(data.get("is_recurring", False))
        recurring_enabled = bool(data.get("recurring_enabled", False))

        if not subject:
            return JsonResponse({"status": "error", "message": "Subject line is required."}, status=400)
        if not body_html:
            return JsonResponse({"status": "error", "message": "Email message body is required."}, status=400)

        try:
            campaign = JobAlertCampaignService.create_campaign(
                created_by=request.user,
                name=name,
                subject=subject,
                body_html=body_html,
                alert_type=alert_type,
                walkin_job_id=walkin_job_id,
                requirement_id=requirement_id,
                is_recurring=is_recurring,
                recurring_enabled=recurring_enabled,
                targeting_criteria=targeting_criteria,
                matching_strategy=matching_strategy,
                selected_job_ids=selected_job_ids,
                candidate_ids=candidate_ids,
            )

            AuditLog.objects.create(
                user=request.user,
                role=getattr(request.user, "role", "admin"),
                action="Job Alert Campaign Created",
                module="Bulk Job Alerts",
                ip_address=get_client_ip(request),
                details={
                    "campaign_id": str(campaign.id),
                    "name": campaign.name,
                    "alert_type": campaign.alert_type,
                    "total_recipients": campaign.total_recipients,
                    "is_draft": is_draft,
                },
            )

            if not is_draft and campaign.total_recipients > 0:
                JobAlertCampaignService.launch_campaign(str(campaign.id))
                messages.success(
                    request,
                    f"Job Alert Campaign '{campaign.name}' launched! {campaign.total_recipients} emails queued for delivery.",
                )
            elif is_draft:
                messages.info(request, f"Job Alert Campaign '{campaign.name}' saved as draft.")
            else:
                messages.warning(request, f"Campaign created, but no eligible recipients matched.")

            redirect_url = reverse("admin-panel:job-alert-campaign-detail", kwargs={"campaign_id": campaign.id})
            return JsonResponse({
                "status": "success",
                "campaign_id": str(campaign.id),
                "redirect_url": redirect_url,
            })

        except ValueError as exc:
            return JsonResponse({"status": "error", "message": str(exc)}, status=400)
        except Exception as exc:
            logger.exception("Failed to create/launch job alert campaign: %s", exc)
            return JsonResponse({"status": "error", "message": f"Server error: {exc}"}, status=500)


class AdminJobAlertCampaignDetailView(AdminMixin, View):
    """
    Detailed real-time monitoring of a specific Job Alert Campaign.
    Displays sent/delivered/failed/suppressed/skipped breakdown, delivery audit trail,
    and failure retry controls.
    """

    sidebar_section = "users"

    def get(self, request: HttpRequest, campaign_id: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        campaign = get_object_or_404(
            JobAlertCampaign.objects.select_related("created_by"),
            pk=campaign_id,
        )

        recipients_qs = campaign.recipients.select_related("candidate").order_by("-updated_at")

        status_filter = request.GET.get("status", "").strip()
        if status_filter:
            recipients_qs = recipients_qs.filter(status=status_filter)

        search_query = request.GET.get("q", "").strip()
        if search_query:
            recipients_qs = recipients_qs.filter(
                Q(recipient_name__icontains=search_query)
                | Q(email__icontains=search_query)
                | Q(profession__icontains=search_query)
                | Q(subject__icontains=search_query)
            )

        paginator = Paginator(recipients_qs, 25)
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        quota_status = DailyEmailQuotaService.get_quota_status()

        context = {
            "campaign": campaign,
            "page_obj": page_obj,
            "status_filter": status_filter,
            "search_query": search_query,
            "quota_status": quota_status,
            "sidebar_section": "users",
        }
        return render(request, "dashboard/admin/job_alert_campaign_detail.html", context)

    def post(self, request: HttpRequest, campaign_id: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        campaign = get_object_or_404(JobAlertCampaign, pk=campaign_id)
        action = request.POST.get("action", "").strip()

        if action == "retry_failed":
            try:
                retried = JobAlertCampaignService.retry_failed_recipients(str(campaign.id), actor=request.user)
                if retried > 0:
                    messages.success(request, f"Successfully re-queued {retried} failed recipient(s) for delivery.")
                else:
                    messages.info(request, "No eligible failed recipients found to retry (or maximum 3 retry attempts reached).")
            except ValueError as exc:
                messages.error(request, str(exc))
            except Exception as exc:
                logger.exception("Failed to retry job alert recipients: %s", exc)
                messages.error(request, f"Retry error: {exc}")

        elif action == "cancel":
            if JobAlertCampaignService.cancel_campaign(str(campaign.id), actor=request.user):
                messages.warning(request, "Campaign was cancelled. Any remaining queued deliveries have been halted.")
            else:
                messages.error(request, "Campaign could not be cancelled in its current state.")

        return redirect("admin-panel:job-alert-campaign-detail", campaign_id=campaign.id)


class AdminJobAlertCampaignListView(AdminMixin, View):
    """
    History log of all Job Alert campaigns with status pills, delivery counts, and analytics links.
    """

    sidebar_section = "users"

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        campaigns_qs = JobAlertCampaign.objects.select_related("created_by").order_by("-created_at")

        search_query = request.GET.get("q", "").strip()
        if search_query:
            campaigns_qs = campaigns_qs.filter(
                Q(name__icontains=search_query) | Q(subject__icontains=search_query)
            )

        status_filter = request.GET.get("status", "").strip()
        if status_filter:
            campaigns_qs = campaigns_qs.filter(status=status_filter)

        paginator = Paginator(campaigns_qs, 15)
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        quota_status = DailyEmailQuotaService.get_quota_status()

        context = {
            "page_obj": page_obj,
            "search_query": search_query,
            "status_filter": status_filter,
            "quota_status": quota_status,
            "sidebar_section": "users",
        }
        return render(request, "dashboard/admin/job_alert_campaigns.html", context)
