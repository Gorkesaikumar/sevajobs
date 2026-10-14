"""
Centralized domain service for orchestrating Bulk Email campaigns.
Handles creation, recipient snapshotting, template rendering, test emails, and state transitions.
"""

from __future__ import annotations

import logging
import re
from typing import Sequence, Dict, Any, List, Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.html import strip_tags
from django.core.mail import EmailMultiAlternatives, get_connection

from apps.accounts.models import User
from apps.jobs.models import InstitutionRequirement
from .models import EmailCampaign, CampaignRecipient, EmailSuppression, RecruitmentEmailTemplate
from .requirement_recipient_service import RequirementRecipientService
from .unsubscribe_service import UnsubscribeService
from .quota_service import DailyEmailQuotaService

logger = logging.getLogger("apps.notifications")

# Whitelist allowed HTML tags for campaign emails
ALLOWED_TAGS = [
    "p", "br", "strong", "b", "em", "i", "u", "h1", "h2", "h3", "h4",
    "ul", "ol", "li", "span", "div", "a", "table", "tr", "td", "th", "tbody", "thead",
    "hr", "blockquote"
]


class CampaignService:
    """Service layer managing bulk email campaign operations."""

    @classmethod
    def sanitize_subject(cls, subject: str) -> str:
        """Strip newlines and carriage returns to prevent email header injection."""
        if not subject:
            return ""
        return re.sub(r"[\r\n]+", " ", subject).strip()

    @classmethod
    def sanitize_html(cls, html_content: str) -> str:
        """
        Sanitize user-authored campaign HTML to prevent script injection
        while allowing styling, links, tables, and typography.
        """
        if not html_content:
            return ""
        # Remove script and style tags completely
        cleaned = re.sub(r"<script.*?</script>", "", html_content, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"javascript:", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"on\w+\s*=", "", cleaned, flags=re.IGNORECASE)
        return cleaned

    @classmethod
    def render_content(
        cls,
        *,
        body_template: str,
        context: Dict[str, Any],
    ) -> str:
        """Safely substitute merge tags without executing arbitrary server-side code."""
        result = body_template
        for key, val in context.items():
            pattern = re.compile(r"\{\{\s*" + re.escape(key) + r"\s*\}\}", re.IGNORECASE)
            result = pattern.sub(str(val if val is not None else ""), result)
        return result

    @classmethod
    def wrap_in_base_email(
        cls,
        *,
        rendered_body_html: str,
        subject: str,
        unsubscribe_url: str,
        frontend_url: str | None = None,
    ) -> str:
        """
        Embed campaign body in the standard SevaJobs branded email wrapper
        including responsive container, logo, verified contact info, and unsubscribe link.
        """
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
                    <p style="margin: 0 0 8px 0;">&copy; {year} SevaJobs Recruitment Platform. All rights reserved.</p>
                    <p style="margin: 0 0 12px 0;">Need help? Contact <a href="mailto:{support_email}">{support_email}</a></p>
                    <p style="margin: 0; font-size: 11px; color: #94a3b8;">
                        You received this recruitment update regarding your application on SevaJobs.<br>
                        <a href="{unsubscribe_url}">Unsubscribe from recruitment emails</a>
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
        requirement: InstitutionRequirement,
        created_by: User,
        name: str,
        subject: str,
        body_html: str,
        body_plain: str = "",
        selected_statuses: Sequence[str] | None = None,
        candidate_ids: Sequence[str] | None = None,
    ) -> EmailCampaign:
        """
        Atomically create an EmailCampaign and snapshot its eligible recipients.
        Guarantees deduplication and prevents unsuppressed duplicate dispatch.
        """
        clean_name = cls.sanitize_subject(name) or f"Campaign for {requirement.subject}"
        clean_subject = cls.sanitize_subject(subject)
        if not clean_subject:
            raise ValueError("Email subject line cannot be empty.")

        clean_html = cls.sanitize_html(body_html)
        if not clean_html.strip():
            raise ValueError("Email body cannot be empty.")

        clean_plain = body_plain.strip() or strip_tags(clean_html)
        statuses = list(selected_statuses or ["all"])

        with transaction.atomic():
            campaign = EmailCampaign.objects.create(
                name=clean_name,
                requirement=requirement,
                created_by=created_by,
                subject=clean_subject,
                body_html=clean_html,
                body_plain=clean_plain,
                selected_statuses=statuses,
                status=EmailCampaign.Status.DRAFT,
            )

            # Retrieve eligible candidates
            eligible_list = RequirementRecipientService.get_eligible_candidates(
                requirement_id=str(requirement.id),
                selected_statuses=statuses,
                candidate_ids=candidate_ids,
            )

            recipients_to_create = []
            for item in eligible_list:
                recipients_to_create.append(
                    CampaignRecipient(
                        campaign=campaign,
                        candidate=item["candidate"],
                        match=item["match"],
                        recipient_name=item["full_name"],
                        email=item["email"],
                        status=CampaignRecipient.RecipientStatus.PENDING,
                    )
                )

            if recipients_to_create:
                CampaignRecipient.objects.bulk_create(
                    recipients_to_create,
                    ignore_conflicts=True,
                )

            total = CampaignRecipient.objects.filter(campaign=campaign).count()
            campaign.total_recipients = total
            campaign.pending_count = total
            campaign.save(update_fields=["total_recipients", "pending_count"])

        logger.info(
            "Created EmailCampaign '%s' (id=%s) with %d snapshot recipients for requirement %s.",
            campaign.name, campaign.id, total, requirement.id
        )
        return campaign

    @classmethod
    def send_test_email(
        cls,
        *,
        admin_user: User,
        test_email: str,
        subject: str,
        body_html: str,
        requirement: InstitutionRequirement,
    ) -> bool:
        """Dispatch a single preview test email to an authorized internal address."""
        clean_to = test_email.strip().lower()
        if not clean_to or "@" not in clean_to:
            raise ValueError("Please provide a valid test email address.")

        clean_subj = f"[TEST] {cls.sanitize_subject(subject)}"
        unsubscribe_url = UnsubscribeService.build_unsubscribe_url(clean_to)

        sample_context = {
            "candidate_name": admin_user.get_full_name() or "Sample Candidate",
            "requirement_title": requirement.subject,
            "school_name": requirement.institution_name,
            "location": requirement.location,
            "candidate_status": "Shortlisted (Preview)",
            "support_email": getattr(settings, "RESEND_FROM_EMAIL", "noreply@sevajobs.in"),
            "unsubscribe_url": unsubscribe_url,
        }

        rendered_body = cls.render_content(body_template=body_html, context=sample_context)
        wrapped_html = cls.wrap_in_base_email(
            rendered_body_html=rendered_body,
            subject=clean_subj,
            unsubscribe_url=unsubscribe_url,
        )
        plain_text = strip_tags(rendered_body)
        if unsubscribe_url:
            plain_text += f"\n\n---\nTo unsubscribe: {unsubscribe_url}"

        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "SevaJobs <noreply@sevajobs.in>")
        msg = EmailMultiAlternatives(
            subject=clean_subj,
            body=plain_text,
            from_email=from_email,
            to=[clean_to],
        )
        msg.attach_alternative(wrapped_html, "text/html")
        msg.send(fail_silently=False)
        logger.info("Dispatched campaign test email to %s for requirement %s", clean_to, requirement.id)
        return True

    @classmethod
    def launch_campaign(cls, campaign_id: str) -> bool:
        """
        Transition campaign to QUEUED state and dispatch the background Celery task.
        Enforces atomic daily email quota reservation.
        Uses transaction.on_commit to prevent race conditions.
        """
        with transaction.atomic():
            campaign = EmailCampaign.objects.select_for_update().get(pk=campaign_id)
            if not campaign.can_transition_to(EmailCampaign.Status.QUEUED):
                raise ValueError(f"Campaign cannot be launched from current state '{campaign.status}'.")

            # Check and reserve daily quota for pending recipients
            pending_count = campaign.recipients.filter(status=CampaignRecipient.RecipientStatus.PENDING).count()
            if pending_count > 0:
                if not DailyEmailQuotaService.reserve_quota(pending_count):
                    quota_status = DailyEmailQuotaService.get_quota_status()
                    raise ValueError(
                        f"Daily email quota exceeded. Cannot queue {pending_count} emails; "
                        f"only {quota_status['remaining']} remaining of {quota_status['daily_limit']} daily limit."
                    )

            campaign.transition_to(EmailCampaign.Status.QUEUED)
            # Mark recipients as QUEUED
            campaign.recipients.filter(status=CampaignRecipient.RecipientStatus.PENDING).update(
                status=CampaignRecipient.RecipientStatus.QUEUED,
                queued_at=timezone.now(),
            )

            from .tasks import send_bulk_campaign_task

            def enqueue():
                send_bulk_campaign_task.delay(str(campaign.id))

            transaction.on_commit(enqueue)

        logger.info("Enqueued bulk campaign task for campaign_id=%s with %d reserved recipients", campaign_id, pending_count)
        return True

    @classmethod
    def cancel_campaign(cls, campaign_id: str, actor: User | None = None) -> bool:
        """Safely cancel a queued or running campaign, mark remaining recipients as cancelled, and release quota."""
        with transaction.atomic():
            campaign = EmailCampaign.objects.select_for_update().get(pk=campaign_id)
            if campaign.status in [EmailCampaign.Status.COMPLETED, EmailCampaign.Status.FAILED, EmailCampaign.Status.CANCELLED]:
                return False

            cancelled_count = campaign.recipients.filter(
                status__in=[CampaignRecipient.RecipientStatus.PENDING, CampaignRecipient.RecipientStatus.QUEUED]
            ).count()

            campaign.transition_to(EmailCampaign.Status.CANCELLED)
            campaign.recipients.filter(
                status__in=[CampaignRecipient.RecipientStatus.PENDING, CampaignRecipient.RecipientStatus.QUEUED]
            ).update(
                status=CampaignRecipient.RecipientStatus.CANCELLED,
            )

            if cancelled_count > 0:
                DailyEmailQuotaService.release_reserved_quota(cancelled_count)

        logger.info(
            "Campaign %s cancelled by actor %s. Released %d reserved quota units.",
            campaign_id, getattr(actor, "email", "system"), cancelled_count
        )
        return True

    @classmethod
    def retry_failed_recipients(cls, campaign_id: str, actor: User | None = None) -> int:
        """
        Retries eligible failed recipients for a campaign, respecting the daily quota.
        Only recipients in FAILED status with attempt_count < 3 are eligible.
        """
        with transaction.atomic():
            campaign = EmailCampaign.objects.select_for_update().get(pk=campaign_id)
            failed_qs = campaign.recipients.select_for_update().filter(
                status=CampaignRecipient.RecipientStatus.FAILED,
                attempt_count__lt=3,
            )
            count = failed_qs.count()
            if count == 0:
                return 0

            # Check and reserve quota for retried recipients
            if not DailyEmailQuotaService.reserve_quota(count):
                quota_status = DailyEmailQuotaService.get_quota_status()
                raise ValueError(
                    f"Insufficient daily quota to retry {count} recipients. "
                    f"Only {quota_status['remaining']} remaining of {quota_status['daily_limit']} today."
                )

            failed_qs.update(
                status=CampaignRecipient.RecipientStatus.QUEUED,
                queued_at=timezone.now(),
                last_error="",
            )

            # Re-open campaign state if finished
            if campaign.status in [EmailCampaign.Status.COMPLETED, EmailCampaign.Status.PARTIALLY_FAILED, EmailCampaign.Status.FAILED]:
                campaign.status = EmailCampaign.Status.QUEUED
                campaign.save(update_fields=["status", "updated_at"])

            from .tasks import send_bulk_campaign_task

            def enqueue():
                send_bulk_campaign_task.delay(str(campaign.id))

            transaction.on_commit(enqueue)

        logger.info("Queued retry of %d failed recipients for campaign %s", count, campaign_id)
        return count

    @classmethod
    def get_template_for_status(cls, status_key: str) -> Dict[str, Any]:
        """Fetch template content for a specific recruitment status."""
        tmpl = RecruitmentEmailTemplate.get_default_template(status_key)
        return {
            "id": str(tmpl.id),
            "name": tmpl.name,
            "status_key": tmpl.status_key,
            "subject": tmpl.subject,
            "body_html": tmpl.body_html,
            "body_plain": tmpl.body_plain,
            "is_default": tmpl.is_default,
            "version": tmpl.version,
        }

    @classmethod
    def save_as_template(
        cls,
        *,
        status_key: str,
        name: str,
        subject: str,
        body_html: str,
        body_plain: str = "",
        user: User,
        set_as_default: bool = False,
    ) -> RecruitmentEmailTemplate:
        """Create or update a reusable template for a given status."""
        clean_key = str(status_key).strip().lower()
        if clean_key in ("interview_scheduled", "interview"):
            clean_key = RecruitmentEmailTemplate.StatusKey.INTERVIEWING
        elif clean_key in ("all", "eligible", "matched"):
            clean_key = RecruitmentEmailTemplate.StatusKey.GENERAL

        with transaction.atomic():
            if set_as_default:
                RecruitmentEmailTemplate.objects.filter(status_key=clean_key, is_default=True).update(is_default=False)

            tmpl = RecruitmentEmailTemplate.objects.create(
                name=name.strip() or f"Template for {clean_key.title()}",
                status_key=clean_key,
                subject=cls.sanitize_subject(subject),
                body_html=cls.sanitize_html(body_html),
                body_plain=body_plain.strip() or strip_tags(body_html),
                is_default=set_as_default,
                is_active=True,
                created_by=user,
                updated_by=user,
            )
        logger.info("Saved reusable RecruitmentEmailTemplate id=%s, name='%s', is_default=%s", tmpl.id, tmpl.name, tmpl.is_default)
        return tmpl

    @classmethod
    def reset_to_default_template(cls, status_key: str) -> Dict[str, Any]:
        """Restore canonical default template content for a status."""
        from .default_templates import CANONICAL_TEMPLATES
        from django.db.models import F
        clean_key = str(status_key).strip().lower()
        if clean_key in ("interview_scheduled", "interview"):
            clean_key = "interviewing"
        elif clean_key in ("all", "eligible", "matched"):
            clean_key = "general"

        defn = CANONICAL_TEMPLATES.get(clean_key, CANONICAL_TEMPLATES["general"])
        with transaction.atomic():
            updated = RecruitmentEmailTemplate.objects.filter(status_key=clean_key, is_default=True).update(
                name=defn["name"],
                subject=defn["subject"],
                body_html=defn["body_html"],
                body_plain=defn.get("body_plain", ""),
                version=F("version") + 1,
            )
            if updated == 0:
                RecruitmentEmailTemplate.objects.create(
                    name=defn["name"],
                    status_key=clean_key,
                    subject=defn["subject"],
                    body_html=defn["body_html"],
                    body_plain=defn.get("body_plain", ""),
                    is_default=True,
                    is_active=True,
                    version=1,
                )
        return cls.get_template_for_status(clean_key)

