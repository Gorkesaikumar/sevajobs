"""
Service layer for orchestrating SevaJobs Admin Bulk Job Alerts Based on Candidate Professional Profiles.
Handles candidate-to-job matching snapshots, personalized vacancy card rendering, daily quota reservation,
deduplication checking, Celery asynchronous dispatch, and lifecycle state management.
"""

from __future__ import annotations

import logging
import re
from typing import Sequence, Dict, Any, List, Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.html import strip_tags
from django.core.mail import EmailMultiAlternatives

from apps.accounts.models import User
from apps.jobs.models import Job, InstitutionRequirement
from apps.jobs.job_alert_matching_service import CandidateJobAlertMatchingService
from django.core.cache import cache
from .models import (
    JobAlertCampaign,
    JobAlertRecipient,
    CandidateJobAlertDelivery,
    EmailSuppression,
)
from .unsubscribe_service import UnsubscribeService, JobAlertPreferenceService
from .quota_service import DailyEmailQuotaService
from .default_templates import DEFAULT_JOB_ALERT_TEMPLATE, FIVE_ALERT_TEMPLATES

logger = logging.getLogger("apps.notifications")


class JobAlertCampaignService:
    """Service layer managing bulk job alert campaign operations across all 5 alert types."""

    SCHEDULE_ENABLED_CACHE_KEY = "daily_job_alerts_schedule_active"

    @classmethod
    def is_daily_schedule_enabled(cls) -> bool:
        """Check if 10:00 AM IST daily job alerts schedule is active."""
        val = cache.get(cls.SCHEDULE_ENABLED_CACHE_KEY)
        if val is None:
            return True
        return bool(val)

    @classmethod
    def set_daily_schedule_enabled(cls, enabled: bool) -> None:
        """Allow administrators to pause, resume, or disable daily 10:00 AM schedule."""
        cache.set(cls.SCHEDULE_ENABLED_CACHE_KEY, bool(enabled), timeout=None)

    @classmethod
    def sanitize_subject(cls, subject: str) -> str:
        """Strip newlines and carriage returns to prevent email header injection."""
        if not subject:
            return ""
        return re.sub(r"[\r\n]+", " ", subject).strip()

    @classmethod
    def sanitize_html(cls, html_content: str) -> str:
        """Sanitize administrator-authored HTML to prevent script execution while preserving styling."""
        if not html_content:
            return ""
        cleaned = re.sub(r"<script.*?</script>", "", html_content, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"javascript:", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"on\w+\s*=", "", cleaned, flags=re.IGNORECASE)
        return cleaned

    @classmethod
    def render_vacancy_cards_html(cls, matched_jobs: List[Dict[str, Any]]) -> str:
        """
        Renders a responsive list of matching job cards for email inclusion.
        Contains job title, organization, location, salary, and direct application link.
        """
        if not matched_jobs:
            return "<p><em>No active matching vacancies at this time.</em></p>"

        cards_html = []
        for job in matched_jobs:
            title = job.get("title", "Teaching Position")
            org = job.get("organization", "Educational Institution")
            loc = job.get("location", "India")
            salary = job.get("salary_display", "Competitive")
            url = job.get("url", "https://sevajobs.in/jobs/")
            job_type = job.get("job_type", "Full Time")

            card = f"""
            <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px 20px; margin-bottom: 14px; text-align: left;">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
                    <div>
                        <h3 style="margin: 0 0 4px 0; font-size: 16px; font-weight: 700; color: #0f172a;">{title}</h3>
                        <p style="margin: 0; font-size: 14px; color: #475569; font-weight: 500;">{org}</p>
                    </div>
                </div>
                <div style="margin: 8px 0 12px 0; font-size: 13px; color: #64748b; line-height: 1.5;">
                    <span style="display: inline-block; margin-right: 12px;">📍 <strong>{loc}</strong></span>
                    <span style="display: inline-block; margin-right: 12px;">💼 {job_type}</span>
                    <span style="display: inline-block;">💰 <strong>{salary}</strong></span>
                </div>
                <div style="margin-top: 10px;">
                    <a href="{url}" style="display: inline-block; background-color: #4f46e5; color: #ffffff; text-decoration: none; padding: 8px 16px; border-radius: 6px; font-size: 13px; font-weight: 600;">
                        View Job &amp; Apply &rarr;
                    </a>
                </div>
            </div>
            """
            cards_html.append(card)

        return "\n".join(cards_html)

    @classmethod
    def render_vacancy_cards_plain(cls, matched_jobs: List[Dict[str, Any]]) -> str:
        """Plain-text alternative listing of matching vacancies."""
        if not matched_jobs:
            return "No active matching vacancies at this time."

        lines = []
        for i, job in enumerate(matched_jobs, 1):
            title = job.get("title", "")
            org = job.get("organization", "")
            loc = job.get("location", "")
            salary = job.get("salary_display", "")
            url = job.get("url", "")
            lines.append(f"{i}. {title} at {org}")
            lines.append(f"   Location: {loc} | Salary: {salary}")
            lines.append(f"   Apply here: {url}\n")

        return "\n".join(lines)

    @classmethod
    def render_content(
        cls,
        *,
        body_template: str,
        context: Dict[str, Any],
    ) -> str:
        """Safely substitute merge tags and strip any stray block tags."""
        result = body_template
        for key, val in context.items():
            pattern = re.compile(r"\{\{\s*" + re.escape(key) + r"\s*\}\}", re.IGNORECASE)
            result = pattern.sub(str(val if val is not None else ""), result)
        # Clean any accidental residual template tags like {% ... %}
        result = re.sub(r"\{%[^%]*%\}", "", result)
        return result

    @classmethod
    def build_context_for_recipient(
        cls,
        campaign: JobAlertCampaign,
        recipient: JobAlertRecipient,
        valid_jobs: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Builds the template substitution dictionary for any of the 5 alert types.
        Safely provides all required variables with sensible defaults.
        """
        email_addr = recipient.email
        unsubscribe_url = UnsubscribeService.build_unsubscribe_url(email_addr)
        preferences_url = JobAlertPreferenceService.build_preference_url(email_addr)
        frontend_url = getattr(settings, "FRONTEND_URL", "https://sevajobs.in").rstrip("/")
        meta = recipient.metadata or {}

        # Determine standard fallback values for cross-template compatibility
        default_inst = (
            meta.get("institution_name")
            or meta.get("organization_name")
            or meta.get("school_name")
            or meta.get("company_name")
            or "Educational Institution"
        )
        default_role = (
            meta.get("role_title")
            or meta.get("requirement_title")
            or (recipient.profession if recipient.profession else "Teaching Professional")
        )
        jobs = valid_jobs if valid_jobs is not None else (recipient.matched_jobs_data or [])
        matching_jobs_html = cls.render_vacancy_cards_html(jobs)
        matching_jobs_plain = cls.render_vacancy_cards_plain(jobs)

        # Default common tags
        context: Dict[str, Any] = {
            "candidate_name": recipient.recipient_name or email_addr.split("@")[0],
            "candidate_profession": recipient.profession or "Teaching Professional",
            "candidate_subject": recipient.subject or "General",
            "role_title": default_role,
            "requirement_title": default_role,
            "institution_name": default_inst,
            "organization_name": default_inst,
            "company_name": default_inst,
            "school_name": default_inst,
            "candidate_status": meta.get("status") or meta.get("candidate_status") or "Shortlisted",
            "location": meta.get("location") or recipient.location or "Chennai",
            "matching_jobs": matching_jobs_html,
            "matching_jobs_plain": matching_jobs_plain,
            "walkin_dates_and_time": meta.get("walkin_date") or meta.get("walkin_dates_and_time") or "Today",
            "walkin_venue": meta.get("walkin_venue") or "Institution Campus",
            "walkin_attendance_note": "You may attend this walk-in interview directly without prior application. Please bring your updated resume and qualification certificates.",
            "walkin_instructions": "Carry 2 hard copies of your CV, passport photos, and original degree certificates.",
            "walkin_job_url": f"{frontend_url}/jobs/",
            "job_alert_preferences_url": preferences_url,
            "preferences_url": preferences_url,
            "unsubscribe_url": unsubscribe_url,
            "support_email": getattr(settings, "RESEND_FROM_EMAIL", "noreply@sevajobs.in"),
            "site_url": frontend_url,
            "login_url": f"{frontend_url}/accounts/login/",
        }

        # ── TYPE 4: EMPLOYER ALERT ───────────────────────────────────────────
        if campaign.alert_type in (JobAlertCampaign.AlertType.EMPLOYER_ALERT, "employer", "employer_alert"):
            company_name = meta.get("company_name") or default_inst
            context.update({
                "employer_contact_name": recipient.recipient_name or "Hiring Partner",
                "company_name": company_name,
                "institution_name": company_name,
                "organization_name": company_name,
                "school_name": company_name,
                "post_job_url": f"{frontend_url}/jobs/post/",
                "submit_requirement_url": f"{frontend_url}/requirements/create/",
                "pricing_url": f"{frontend_url}/pricing/",
            })

        # ── TYPE 2: INTERVIEW ALERT ──────────────────────────────────────────
        elif campaign.alert_type in (JobAlertCampaign.AlertType.INTERVIEW_ALERT, "interview", "interview_alert"):
            candidate_status = meta.get("status") or meta.get("candidate_status") or "Shortlisted"
            interview_date = meta.get("interview_date", "")
            interview_time = meta.get("interview_time", "")
            venue_or_link = meta.get("venue_or_link", "")
            interview_type = meta.get("interview_type", "In-Person")

            interview_details_html = ""
            interview_details_plain = ""
            if interview_date or venue_or_link:
                interview_details_html = f"""
                <div style="background-color: #f0fdf4; border: 1px solid #bbf7d0; padding: 14px 18px; margin: 16px 0; border-radius: 8px;">
                    <p style="margin: 0 0 6px 0;"><strong>Date:</strong> {interview_date} {interview_time}</p>
                    <p style="margin: 0 0 6px 0;"><strong>Format:</strong> {interview_type}</p>
                    <p style="margin: 0;"><strong>Venue / Meeting Link:</strong> {venue_or_link}</p>
                </div>
                """
                interview_details_plain = f"Date: {interview_date} {interview_time}\nFormat: {interview_type}\nVenue/Link: {venue_or_link}\n"

            inst = meta.get("employer_name") or meta.get("institution_name") or default_inst
            context.update({
                "role_title": meta.get("role_title") or default_role,
                "requirement_title": meta.get("role_title") or default_role,
                "institution_name": inst,
                "organization_name": inst,
                "school_name": inst,
                "company_name": inst,
                "candidate_status": candidate_status.title(),
                "interview_details_block": interview_details_html,
                "interview_details_html": interview_details_html,
                "interview_details_plain": interview_details_plain,
                "next_steps": "Please check your SevaJobs candidate dashboard or reply to this email for interview confirmation.",
            })

        # ── TYPE 3: WALKIN ALERT ─────────────────────────────────────────────
        elif campaign.alert_type in (JobAlertCampaign.AlertType.WALKIN_ALERT, "walkin", "walkin_alert"):
            walkin_job = campaign.walkin_job
            dates_time = ""
            venue = ""
            instructions = ""
            attendance_note = "You may attend this walk-in interview directly without prior application. Please bring your updated resume and qualification certificates."
            role_title = meta.get("role_title", "")
            org_name = meta.get("organization_name") or meta.get("institution_name") or ""

            if walkin_job:
                role_title = role_title or walkin_job.title
                comp_name = walkin_job.company.name if (walkin_job.company and hasattr(walkin_job.company, "name")) else ""
                org_name = org_name or comp_name or "Academic Institution"
                start_d = walkin_job.walkin_start_date.strftime("%b %d, %Y") if walkin_job.walkin_start_date else ""
                end_d = walkin_job.walkin_end_date.strftime("%b %d, %Y") if walkin_job.walkin_end_date else ""
                dates_time = f"{start_d} to {end_d}" if (start_d and end_d and start_d != end_d) else (start_d or "Today")
                if walkin_job.walkin_time:
                    dates_time += f" at {walkin_job.walkin_time}"
                venue = walkin_job.walkin_venue or (walkin_job.location or "Institution Campus")
                instructions = walkin_job.walkin_contact_instructions or "Carry 2 hard copies of your CV, passport photos, and original degree certificates."
                job_url = f"{frontend_url}/jobs/{walkin_job.slug}/" if hasattr(walkin_job, 'slug') and walkin_job.slug else f"{frontend_url}/jobs/{walkin_job.id}/"
            else:
                job_url = f"{frontend_url}/jobs/"

            final_role = role_title or default_role or "Urgent Teaching Vacancy"
            final_org = org_name or default_inst or "Academic Institution"

            context.update({
                "role_title": final_role,
                "requirement_title": final_role,
                "institution_name": final_org,
                "organization_name": final_org,
                "school_name": final_org,
                "company_name": final_org,
                "walkin_dates_and_time": dates_time or meta.get("walkin_date", "Today"),
                "walkin_venue": venue or meta.get("walkin_venue", "School Campus"),
                "walkin_attendance_note": attendance_note,
                "walkin_instructions": instructions,
                "walkin_job_url": job_url,
            })

        # ── TYPE 5: REQUIREMENT ALERT ────────────────────────────────────────
        elif campaign.alert_type in (JobAlertCampaign.AlertType.REQUIREMENT_ALERT, "requirement", "requirement_alert"):
            req = campaign.requirement
            if req:
                req_subject = req.subject or meta.get("subject", "Educator")
                req_grade = getattr(req, "teaching_grade", "") or meta.get("grade_level", "All Levels")
                if hasattr(req, "get_teaching_grade_display"):
                    req_grade = req.get_teaching_grade_display()
                inst_name = req.institution_name or "Academic Institution"
                req_loc = req.location or "India"
                req_exp = f"{getattr(req, 'min_experience_years', 0)}+ Years"
                req_salary = f"₹{req.salary_min:,} - ₹{req.salary_max:,}" if getattr(req, 'salary_min', None) and getattr(req, 'salary_max', None) else "Competitive"
                pos_cnt = str(req.positions_count or 1)
                req_url = f"{frontend_url}/requirements/{req.id}/"
            else:
                req_subject = meta.get("subject", "Educator")
                req_grade = meta.get("grade_level", "Secondary")
                inst_name = meta.get("institution_name", "Partner Institution")
                req_loc = meta.get("location", "India")
                req_exp = "2+ Years"
                req_salary = "Industry Standard"
                pos_cnt = "1"
                req_url = f"{frontend_url}/requirements/"

            context.update({
                "subject": req_subject,
                "requirement_subject": req_subject,
                "requirement_grade": req_grade,
                "institution_name": inst_name,
                "requirement_location": req_loc,
                "requirement_experience": req_exp,
                "requirement_salary": req_salary,
                "positions_count": pos_cnt,
                "requirement_url": req_url,
            })

        # ── TYPE 1: DAILY JOB ALERT (DIGEST) ─────────────────────────────────
        else:
            jobs = valid_jobs if valid_jobs is not None else (recipient.matched_jobs_data or [])
            matching_jobs_html = cls.render_vacancy_cards_html(jobs)
            matching_jobs_plain = cls.render_vacancy_cards_plain(jobs)
            context.update({
                "matching_jobs": matching_jobs_html,
                "matching_jobs_plain": matching_jobs_plain,
            })

        return context

    @classmethod
    def wrap_in_base_email(
        cls,
        *,
        rendered_body_html: str,
        subject: str,
        unsubscribe_url: str,
        preferences_url: str,
        frontend_url: str | None = None,
    ) -> str:
        """Wrap body in standard SevaJobs responsive email container."""
        site_url = frontend_url or getattr(settings, "FRONTEND_URL", "https://sevajobs.in")
        logo_url = f"{site_url.rstrip('/')}/static/images/logo.jpg"
        support_email = getattr(settings, "RESEND_FROM_EMAIL", "noreply@sevajobs.in")
        year = timezone.now().year

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{subject}</title>
    <style>
        body {{ margin: 0; padding: 0; background-color: #f1f5f9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #334155; }}
        .wrapper {{ width: 100%; background-color: #f1f5f9; padding: 24px 0 40px 0; }}
        .main {{ background-color: #ffffff; margin: 0 auto; width: 100%; max-width: 600px; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }}
        .header {{ background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); padding: 20px 32px; text-align: left; }}
        .content {{ padding: 32px; font-size: 15px; line-height: 1.6; color: #334155; }}
        .footer {{ background-color: #f8fafc; padding: 24px 32px; text-align: center; font-size: 12px; color: #64748b; border-top: 1px solid #e2e8f0; }}
        .footer a {{ color: #4f46e5; text-decoration: none; }}
        @media screen and (max-width: 600px) {{
            .content {{ padding: 20px !important; }}
            .header {{ padding: 16px 20px !important; }}
        }}
    </style>
</head>
<body>
    <div class="wrapper">
        <table role="presentation" class="main" align="center" width="100%">
            <tr>
                <td class="header">
                    <a href="{site_url}" style="text-decoration:none; display:inline-block;">
                        <img src="{logo_url}" alt="SevaJobs" width="140" style="display:block; max-width:140px; height:auto; border:0; border-radius:6px; box-shadow:0 2px 4px rgba(0,0,0,0.1);">
                    </a>
                </td>
            </tr>
            <tr>
                <td class="content">
                    {rendered_body_html}
                </td>
            </tr>
            <tr>
                <td class="footer">
                    <p style="margin: 0 0 8px 0;">&copy; {year} SevaJobs Career Platform. All rights reserved.</p>
                    <p style="margin: 0 0 12px 0;">Need help? Contact <a href="mailto:{support_email}">{support_email}</a></p>
                    <p style="margin: 0 0 6px 0; font-size: 11px; color: #94a3b8;">
                        You received this job alert based on your professional profile on SevaJobs.<br>
                        <a href="{preferences_url}">Manage Job Alert Preferences</a> &bull; <a href="{unsubscribe_url}">Unsubscribe from all emails</a>
                    </p>
                </td>
            </tr>
        </table>
    </div>
</body>
</html>"""

    @classmethod
    def create_campaign(
        cls,
        *,
        created_by: User,
        name: str,
        subject: str,
        body_html: str,
        body_plain: str = "",
        alert_type: str = JobAlertCampaign.AlertType.DAILY_DIGEST,
        priority: Optional[int] = None,
        walkin_job_id: Optional[str] = None,
        requirement_id: Optional[str] = None,
        is_recurring: bool = False,
        recurring_enabled: bool = False,
        recurring_time: Optional[Any] = None,
        targeting_criteria: Dict[str, Any] | None = None,
        matching_strategy: str = "auto",
        selected_job_ids: Sequence[str] | None = None,
        candidate_ids: Sequence[str] | None = None,
        dedup_window_days: int = 14,
    ) -> JobAlertCampaign:
        """
        Atomically create a JobAlertCampaign for any of the 5 alert types, evaluate
        and snapshot eligible matching recipients (candidates or employers),
        and attach their specific matched vacancies or context bundle.
        """
        clean_name = cls.sanitize_subject(name) or f"Job Alert ({timezone.now().strftime('%Y-%m-%d')})"
        clean_subj = cls.sanitize_subject(subject)
        if not clean_subj:
            raise ValueError("Email subject line cannot be empty.")

        clean_html = cls.sanitize_html(body_html)
        if not clean_html.strip():
            raise ValueError("Email body content cannot be empty.")

        clean_plain = body_plain.strip() or strip_tags(clean_html)
        criteria = targeting_criteria or {}

        # Resolve priority based on 5-type hierarchy if not specified
        default_priorities = {
            JobAlertCampaign.AlertType.INTERVIEW_ALERT: 1,
            "interview": 1,
            "interview_alert": 1,
            JobAlertCampaign.AlertType.WALKIN_ALERT: 2,
            "walkin": 2,
            "walkin_alert": 2,
            JobAlertCampaign.AlertType.REQUIREMENT_ALERT: 3,
            "requirement": 3,
            "requirement_alert": 3,
            JobAlertCampaign.AlertType.DAILY_DIGEST: 4,
            "daily_digest": 4,
            JobAlertCampaign.AlertType.EMPLOYER_ALERT: 5,
            "employer": 5,
            "employer_alert": 5,
        }
        resolved_priority = priority or default_priorities.get(alert_type, 4)

        walkin_job = None
        if walkin_job_id:
            walkin_job = Job.objects.filter(pk=walkin_job_id).first()

        requirement = None
        if requirement_id:
            requirement = InstitutionRequirement.objects.filter(pk=requirement_id).first()

        with transaction.atomic():
            campaign = JobAlertCampaign.objects.create(
                name=clean_name,
                created_by=created_by,
                status=JobAlertCampaign.Status.DRAFT,
                alert_type=alert_type,
                priority=resolved_priority,
                walkin_job=walkin_job,
                requirement=requirement,
                is_recurring=is_recurring,
                recurring_enabled=recurring_enabled,
                recurring_time=recurring_time or "10:00:00",
                matching_strategy=matching_strategy,
                selected_job_ids=list(selected_job_ids or []),
                targeting_criteria=criteria,
                subject=clean_subj,
                body_html=clean_html,
                body_plain=clean_plain,
            )

            # Evaluate audience based on alert_type
            if alert_type in (JobAlertCampaign.AlertType.EMPLOYER_ALERT, "employer", "employer_alert"):
                eval_result = CandidateJobAlertMatchingService.evaluate_employer_audience(filters=criteria)
                recipients_to_create = []
                selected_ids_set = set(candidate_ids) if candidate_ids else None
                for review in eval_result["candidates_review"]:
                    emp_id = review["candidate_id"]
                    if selected_ids_set and emp_id not in selected_ids_set:
                        continue
                    if not review.get("is_eligible", True):
                        continue

                    recipients_to_create.append(
                        JobAlertRecipient(
                            campaign=campaign,
                            recipient_type=JobAlertRecipient.RecipientType.EMPLOYER,
                            employer=getattr(review["user"], "recruiter_profile", None),
                            candidate=None,
                            recipient_name=review["name"],
                            email=review["email"],
                            profession="",
                            subject="",
                            location=review.get("location", ""),
                            metadata=review.get("metadata", {}),
                            matched_job_count=0,
                            matched_jobs_data=[],
                            status=JobAlertRecipient.RecipientStatus.PENDING,
                        )
                    )

            elif alert_type in (JobAlertCampaign.AlertType.INTERVIEW_ALERT, "interview", "interview_alert"):
                eval_result = CandidateJobAlertMatchingService.evaluate_interview_audience(filters=criteria)
                recipients_to_create = []
                selected_ids_set = set(candidate_ids) if candidate_ids else None
                for review in eval_result["candidates_review"]:
                    cand_id = review["candidate_id"]
                    if selected_ids_set and cand_id not in selected_ids_set:
                        continue
                    if not review["is_eligible"]:
                        continue

                    recipients_to_create.append(
                        JobAlertRecipient(
                            campaign=campaign,
                            recipient_type=JobAlertRecipient.RecipientType.CANDIDATE,
                            candidate=review["user"],
                            recipient_name=review["name"],
                            email=review["email"],
                            profession=review.get("profession", ""),
                            subject=review.get("subject", ""),
                            location=review.get("location", ""),
                            metadata=review.get("metadata", {}),
                            matched_job_count=len(review.get("matched_jobs", [])),
                            matched_jobs_data=review.get("matched_jobs", []),
                            status=JobAlertRecipient.RecipientStatus.PENDING,
                        )
                    )

            elif alert_type in (JobAlertCampaign.AlertType.WALKIN_ALERT, "walkin", "walkin_alert"):
                eval_result = CandidateJobAlertMatchingService.evaluate_walkin_audience(
                    walkin_job_id=walkin_job_id,
                    filters=criteria,
                )
                recipients_to_create = []
                selected_ids_set = set(candidate_ids) if candidate_ids else None
                for review in eval_result["candidates_review"]:
                    cand_id = review["candidate_id"]
                    if selected_ids_set and cand_id not in selected_ids_set:
                        continue
                    if not review["is_eligible"]:
                        continue

                    meta = dict(review.get("metadata", {}))
                    if walkin_job:
                        start_d = walkin_job.walkin_start_date.strftime("%b %d, %Y") if walkin_job.walkin_start_date else ""
                        end_d = walkin_job.walkin_end_date.strftime("%b %d, %Y") if walkin_job.walkin_end_date else ""
                        dates_time = f"{start_d} to {end_d}" if (start_d and end_d and start_d != end_d) else (start_d or "Today")
                        if walkin_job.walkin_time:
                            dates_time += f" at {walkin_job.walkin_time}"
                        meta.setdefault("role_title", walkin_job.title)
                        meta.setdefault("organization_name", (walkin_job.company.name if getattr(walkin_job, 'company', None) else "Academic Institution"))
                        meta.setdefault("walkin_date", dates_time)
                        meta.setdefault("walkin_venue", walkin_job.walkin_venue or walkin_job.location)

                    recipients_to_create.append(
                        JobAlertRecipient(
                            campaign=campaign,
                            recipient_type=JobAlertRecipient.RecipientType.CANDIDATE,
                            candidate=review["user"],
                            recipient_name=review["name"],
                            email=review["email"],
                            profession=review.get("profession", ""),
                            subject=review.get("subject", ""),
                            location=review.get("location", ""),
                            metadata=meta,
                            matched_job_count=len(review.get("matched_jobs", [])),
                            matched_jobs_data=review.get("matched_jobs", []),
                            status=JobAlertRecipient.RecipientStatus.PENDING,
                        )
                    )

            elif alert_type in (JobAlertCampaign.AlertType.REQUIREMENT_ALERT, "requirement", "requirement_alert"):
                eval_result = CandidateJobAlertMatchingService.evaluate_requirement_audience(
                    requirement_id=requirement_id,
                    filters=criteria,
                )
                recipients_to_create = []
                selected_ids_set = set(candidate_ids) if candidate_ids else None
                for review in eval_result["candidates_review"]:
                    cand_id = review["candidate_id"]
                    if selected_ids_set and cand_id not in selected_ids_set:
                        continue
                    if not review["is_eligible"]:
                        continue

                    meta = dict(review.get("metadata", {}))
                    if requirement:
                        grade_str = requirement.get_teaching_grade_display() if hasattr(requirement, "get_teaching_grade_display") else getattr(requirement, "teaching_grade", "")
                        meta.setdefault("requirement_id", str(requirement.id))
                        meta.setdefault("role_title", f"{requirement.subject} ({grade_str})" if grade_str else requirement.subject)
                        meta.setdefault("subject", requirement.subject)
                        meta.setdefault("grade_level", grade_str)
                        meta.setdefault("institution_name", requirement.institution_name)
                        meta.setdefault("location", requirement.location)

                    recipients_to_create.append(
                        JobAlertRecipient(
                            campaign=campaign,
                            recipient_type=JobAlertRecipient.RecipientType.CANDIDATE,
                            candidate=review["user"],
                            recipient_name=review["name"],
                            email=review["email"],
                            profession=review.get("profession", ""),
                            subject=review.get("subject", ""),
                            location=review.get("location", ""),
                            metadata=meta,
                            matched_job_count=len(review.get("matched_jobs", [])),
                            matched_jobs_data=review.get("matched_jobs", []),
                            status=JobAlertRecipient.RecipientStatus.PENDING,
                        )
                    )

            else:  # DAILY_DIGEST (or general job alert)
                eval_result = CandidateJobAlertMatchingService.evaluate_audience(
                    filters=criteria,
                    specific_job_ids=selected_job_ids if matching_strategy == "specific_jobs" else None,
                    dedup_window_days=dedup_window_days,
                )
                recipients_to_create = []
                selected_ids_set = set(candidate_ids) if candidate_ids else None
                for review in eval_result["candidates_review"]:
                    cand_id = review["candidate_id"]
                    if selected_ids_set and cand_id not in selected_ids_set:
                        continue
                    if not review["is_eligible"]:
                        continue

                    recipients_to_create.append(
                        JobAlertRecipient(
                            campaign=campaign,
                            recipient_type=JobAlertRecipient.RecipientType.CANDIDATE,
                            candidate=review["user"],
                            recipient_name=review["name"],
                            email=review["email"],
                            profession=review["profession"],
                            subject=review["subject"],
                            location=review["location"],
                            matched_job_count=len(review["matched_jobs"]),
                            matched_jobs_data=review["matched_jobs"],
                            status=JobAlertRecipient.RecipientStatus.PENDING,
                        )
                    )

            if recipients_to_create:
                JobAlertRecipient.objects.bulk_create(recipients_to_create, ignore_conflicts=True)

            total = campaign.recipients.count()
            campaign.total_recipients = total
            campaign.pending_count = total
            campaign.save(update_fields=["total_recipients", "pending_count"])

        logger.info("Created JobAlertCampaign id=%s (type=%s) with %d snapshot recipients", campaign.id, alert_type, total)
        return campaign

    @classmethod
    def send_test_email(
        cls,
        *,
        admin_user: User,
        test_email: str,
        subject: str,
        body_html: str,
        alert_type: str = JobAlertCampaign.AlertType.DAILY_DIGEST,
        specific_job_ids: Sequence[str] | None = None,
        walkin_job_id: Optional[str] = None,
        requirement_id: Optional[str] = None,
    ) -> bool:
        """Send a single live preview email to an authorized administrator address for any of the 5 alert types."""
        clean_to = test_email.strip().lower()
        if not clean_to or "@" not in clean_to:
            raise ValueError("Please provide a valid test email address.")

        clean_subj = f"[TEST] {cls.sanitize_subject(subject)}"
        unsubscribe_url = UnsubscribeService.build_unsubscribe_url(clean_to)
        preferences_url = JobAlertPreferenceService.build_preference_url(clean_to)

        # Build mock in-memory campaign and recipient
        walkin_job = Job.objects.filter(pk=walkin_job_id).first() if walkin_job_id else None
        requirement = InstitutionRequirement.objects.filter(pk=requirement_id).first() if requirement_id else None

        if not walkin_job and alert_type in ("walkin", "walkin_alert"):
            walkin_job = Job.objects.filter(is_walkin=True, is_active=True).first() or Job.objects.filter(is_walkin=True).first()

        mock_campaign = JobAlertCampaign(
            alert_type=alert_type,
            walkin_job=walkin_job,
            requirement=requirement,
            subject=clean_subj,
            body_html=body_html,
        )

        if alert_type in ("walkin", "walkin_alert") and walkin_job:
            sample_vacancies = [CandidateJobAlertMatchingService._format_walkin_dict(walkin_job)]
        else:
            sample_vacancies = CandidateJobAlertMatchingService.get_public_vacancies(specific_job_ids=specific_job_ids)[:3]

        comp_name = (
            walkin_job.company.name if (walkin_job and getattr(walkin_job, "company", None))
            else (requirement.institution_name if requirement else "SevaJobs Model Academy")
        )

        mock_recipient = JobAlertRecipient(
            email=clean_to,
            recipient_name=admin_user.get_full_name() or "Administrator Preview",
            profession="Senior Educator",
            subject="English",
            location="Chennai",
            matched_jobs_data=sample_vacancies,
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
                "venue_or_link": "Campus Administrative Block, Chennai",
                "interview_type": "In-Person Demo",
                "subject": requirement.subject if requirement else "English",
                "grade_level": requirement.grade_level if requirement else "High School",
                "location": "Chennai",
                "walkin_date": "Today",
                "walkin_venue": (walkin_job.walkin_venue if walkin_job and walkin_job.walkin_venue else "Campus Grounds"),
            },
        )

        sample_context = cls.build_context_for_recipient(
            campaign=mock_campaign,
            recipient=mock_recipient,
            valid_jobs=sample_vacancies,
        )

        rendered_body = cls.render_content(body_template=body_html, context=sample_context)
        wrapped_html = cls.wrap_in_base_email(
            rendered_body_html=rendered_body,
            subject=clean_subj,
            unsubscribe_url=unsubscribe_url,
            preferences_url=preferences_url,
        )

        plain_text = strip_tags(rendered_body)
        plain_text += f"\n\n---\nPreferences: {preferences_url}\nUnsubscribe: {unsubscribe_url}"

        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "SevaJobs <noreply@sevajobs.in>")
        msg = EmailMultiAlternatives(
            subject=clean_subj,
            body=plain_text,
            from_email=from_email,
            to=[clean_to],
        )
        msg.attach_alternative(wrapped_html, "text/html")
        msg.send(fail_silently=False)
        logger.info("Sent job alert test email to %s for alert_type=%s", clean_to, alert_type)
        return True

    @classmethod
    def launch_campaign(cls, campaign_id: str) -> bool:
        """
        Transition JobAlertCampaign to QUEUED state and dispatch the background task.
        Enforces atomic quota reservation against DailyEmailQuotaService.
        """
        with transaction.atomic():
            campaign = JobAlertCampaign.objects.select_for_update().get(pk=campaign_id)
            if not campaign.can_transition_to(JobAlertCampaign.Status.QUEUED):
                raise ValueError(f"Campaign cannot be launched from current state '{campaign.status}'.")

            pending_count = campaign.recipients.filter(status=JobAlertRecipient.RecipientStatus.PENDING).count()
            if pending_count > 0:
                if not DailyEmailQuotaService.reserve_quota(pending_count):
                    quota_status = DailyEmailQuotaService.get_quota_status()
                    raise ValueError(
                        f"Daily email quota exceeded. Cannot queue {pending_count} emails; "
                        f"only {quota_status['remaining']} remaining of {quota_status['daily_limit']} daily limit."
                    )

            campaign.transition_to(JobAlertCampaign.Status.QUEUED)
            campaign.recipients.filter(status=JobAlertRecipient.RecipientStatus.PENDING).update(
                status=JobAlertRecipient.RecipientStatus.QUEUED,
                queued_at=timezone.now(),
            )

            from .tasks import send_bulk_job_alerts_task

            def enqueue():
                send_bulk_job_alerts_task.delay(str(campaign.id))

            transaction.on_commit(enqueue)

        logger.info("Enqueued job alert campaign %s with %d reserved recipients", campaign_id, pending_count)
        return True

    @classmethod
    def cancel_campaign(cls, campaign_id: str, actor: User | None = None) -> bool:
        """Safely cancel a queued or processing job alert campaign and release reserved quota."""
        with transaction.atomic():
            campaign = JobAlertCampaign.objects.select_for_update().get(pk=campaign_id)
            if campaign.status in [JobAlertCampaign.Status.COMPLETED, JobAlertCampaign.Status.FAILED, JobAlertCampaign.Status.CANCELLED]:
                return False

            cancelled_count = campaign.recipients.filter(
                status__in=[JobAlertRecipient.RecipientStatus.PENDING, JobAlertRecipient.RecipientStatus.QUEUED]
            ).count()

            campaign.transition_to(JobAlertCampaign.Status.CANCELLED)
            campaign.recipients.filter(
                status__in=[JobAlertRecipient.RecipientStatus.PENDING, JobAlertRecipient.RecipientStatus.QUEUED]
            ).update(status=JobAlertRecipient.RecipientStatus.CANCELLED)

            if cancelled_count > 0:
                DailyEmailQuotaService.release_reserved_quota(cancelled_count)

        logger.info("Cancelled JobAlertCampaign %s. Released %d quota units.", campaign_id, cancelled_count)
        return True

    @classmethod
    def retry_failed_recipients(cls, campaign_id: str, actor: User | None = None) -> int:
        """Retry eligible failed recipients (attempt < 3) respecting daily quota."""
        with transaction.atomic():
            campaign = JobAlertCampaign.objects.select_for_update().get(pk=campaign_id)
            failed_qs = campaign.recipients.select_for_update().filter(
                status=JobAlertRecipient.RecipientStatus.FAILED,
                attempt_count__lt=3,
            )
            count = failed_qs.count()
            if count == 0:
                return 0

            if not DailyEmailQuotaService.reserve_quota(count):
                quota_status = DailyEmailQuotaService.get_quota_status()
                raise ValueError(
                    f"Insufficient daily quota to retry {count} recipients. "
                    f"Only {quota_status['remaining']} remaining today."
                )

            failed_qs.update(
                status=JobAlertRecipient.RecipientStatus.QUEUED,
                queued_at=timezone.now(),
                last_error="",
            )

            if campaign.status in [JobAlertCampaign.Status.COMPLETED, JobAlertCampaign.Status.PARTIALLY_FAILED, JobAlertCampaign.Status.FAILED]:
                campaign.status = JobAlertCampaign.Status.QUEUED
                campaign.save(update_fields=["status", "updated_at"])

            from .tasks import send_bulk_job_alerts_task

            def enqueue():
                send_bulk_job_alerts_task.delay(str(campaign.id))

            transaction.on_commit(enqueue)

        logger.info("Queued retry of %d failed recipients for JobAlertCampaign %s", count, campaign_id)
        return count
