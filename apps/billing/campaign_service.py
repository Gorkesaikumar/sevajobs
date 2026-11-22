"""
Recruiter Campaign Dispatch & Tracking Service.
Integrates with Resend email backend or system email, embeds open tracking pixels,
wraps click tracking links, and enforces daily 200 emails/day quota.
"""

from __future__ import annotations

import logging
import re
import uuid
from decimal import Decimal
from typing import Any, List

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils import timezone
from django.utils.html import strip_tags

from apps.accounts.models import User
from .models import (
    EmailTemplate,
    RecruiterCampaign,
    RecruiterCampaignRecipient,
)
from .services import BillingEntitlementService

logger = logging.getLogger("apps.billing")


class RecruiterCampaignService:
    """
    Manages recruiter bulk email campaigns with mandatory admin approval.
    """

    @classmethod
    def create_campaign(
        cls,
        company,
        created_by: User,
        name: str,
        subject: str,
        body_html: str,
        candidate_ids: List[uuid.UUID],
        template: EmailTemplate | None = None,
    ) -> RecruiterCampaign:
        """
        Creates a draft/pending campaign for SevaJobs candidates.
        """
        can_send, reason = BillingEntitlementService.can_send_bulk_email(company, len(candidate_ids))
        if not can_send:
            raise ValueError(reason)

        with transaction.atomic():
            campaign = RecruiterCampaign.objects.create(
                company=company,
                created_by=created_by,
                template=template,
                name=name,
                subject=subject,
                body_html=body_html,
                approval_status=RecruiterCampaign.ApprovalStatus.PENDING_APPROVAL,
                status=RecruiterCampaign.Status.PENDING_APPROVAL,
                recipient_count=len(candidate_ids),
            )

            # Deduct credits atomically
            BillingEntitlementService.consume_email_credits(company, len(candidate_ids))

            candidates = User.objects.filter(id__in=candidate_ids, role=User.Role.JOB_SEEKER, is_active=True)
            recipients = []
            for candidate in candidates:
                recipients.append(
                    RecruiterCampaignRecipient(
                        campaign=campaign,
                        candidate_user=candidate,
                        email=candidate.email,
                        tracking_token=uuid.uuid4().hex,
                        status=RecruiterCampaignRecipient.Status.PENDING,
                    )
                )
            RecruiterCampaignRecipient.objects.bulk_create(recipients)
            logger.info("Created campaign '%s' with %d recipients for %s.", name, len(recipients), company.name)
            return campaign

    @classmethod
    def approve_campaign(cls, campaign: RecruiterCampaign, reviewed_by: User) -> bool:
        """
        Admin approves the campaign and queues it for dispatch.
        """
        campaign.approval_status = RecruiterCampaign.ApprovalStatus.APPROVED
        campaign.status = RecruiterCampaign.Status.APPROVED
        campaign.reviewed_by = reviewed_by
        campaign.reviewed_at = timezone.now()
        campaign.save(update_fields=["approval_status", "status", "reviewed_by", "reviewed_at"])
        logger.info("Campaign '%s' approved by %s.", campaign.name, reviewed_by.email)

        # Dispatch emails asynchronously via Celery worker, with eager fallback
        try:
            from .tasks import dispatch_campaign_task
            dispatch_campaign_task.delay(str(campaign.pk))
        except Exception as exc:
            logger.info("Celery delay failed (%s), dispatching synchronously.", exc)
            cls.dispatch_campaign(campaign)
        return True

    @classmethod
    def reject_campaign(cls, campaign: RecruiterCampaign, reviewed_by: User, reason: str = "") -> bool:
        """
        Admin rejects the campaign and refunds email credits.
        """
        with transaction.atomic():
            campaign.approval_status = RecruiterCampaign.ApprovalStatus.REJECTED
            campaign.status = RecruiterCampaign.Status.FAILED
            campaign.rejection_reason = reason
            campaign.reviewed_by = reviewed_by
            campaign.reviewed_at = timezone.now()
            campaign.save(update_fields=["approval_status", "status", "rejection_reason", "reviewed_by", "reviewed_at"])

            # Refund credits
            sub = BillingEntitlementService.get_company_subscription(campaign.company)
            sub.remaining_email_credits += campaign.recipient_count
            sub.save(update_fields=["remaining_email_credits"])
            logger.info("Campaign '%s' rejected. Refunded %d credits.", campaign.name, campaign.recipient_count)
            return True

    @classmethod
    def dispatch_campaign(cls, campaign: RecruiterCampaign) -> int:
        """
        Dispatches emails to recipients, embedding open tracking pixel and click tracking links.
        """
        campaign.status = RecruiterCampaign.Status.SENDING
        campaign.save(update_fields=["status"])

        frontend_url = getattr(settings, "FRONTEND_URL", "https://sevajobs.in").rstrip("/")
        sent_count = 0

        for recipient in campaign.recipients.filter(status=RecruiterCampaignRecipient.Status.PENDING).select_related("candidate_user"):
            token = recipient.tracking_token
            candidate = recipient.candidate_user

            # Personalize placeholders
            personalized_html = campaign.body_html.replace("{{candidate_name}}", candidate.full_name or "Candidate")
            personalized_html = personalized_html.replace("{{company_name}}", campaign.company.name)
            personalized_subject = campaign.subject.replace("{{candidate_name}}", candidate.full_name or "Candidate")
            personalized_subject = personalized_subject.replace("{{company_name}}", campaign.company.name)

            # Wrap hyperlinks with click tracker: href="URL" -> href="frontend_url/billing/track/click/<token>/?url=URL"
            def wrap_link(match):
                url = match.group(1)
                if "/billing/track/" in url:
                    return f'href="{url}"'
                tracked_url = f"{frontend_url}/billing/track/click/{token}/?url={url}"
                return f'href="{tracked_url}"'

            personalized_html = re.sub(r'href=["\'](https?://[^"\']+)["\']', wrap_link, personalized_html)

            # Embed open tracking pixel at the end of HTML
            pixel_url = f"{frontend_url}/billing/track/open/{token}/"
            tracking_pixel = f'<img src="{pixel_url}" width="1" height="1" alt="" style="display:none;" />'
            if "</body>" in personalized_html:
                personalized_html = personalized_html.replace("</body>", f"{tracking_pixel}</body>")
            else:
                personalized_html += tracking_pixel

            body_plain = strip_tags(personalized_html)

            try:
                msg = EmailMultiAlternatives(
                    subject=personalized_subject,
                    body=body_plain,
                    from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "SevaJobs <noreply@sevajobs.in>"),
                    to=[recipient.email],
                )
                msg.attach_alternative(personalized_html, "text/html")
                msg.send(fail_silently=False)

                recipient.status = RecruiterCampaignRecipient.Status.SENT
                recipient.sent_at = timezone.now()
                recipient.save(update_fields=["status", "sent_at"])
                sent_count += 1
            except Exception as e:
                logger.exception("Failed to send campaign email to %s: %s", recipient.email, e)
                recipient.status = RecruiterCampaignRecipient.Status.FAILED
                recipient.save(update_fields=["status"])

        campaign.sent_count = sent_count
        campaign.status = RecruiterCampaign.Status.COMPLETED
        campaign.save(update_fields=["sent_count", "status"])
        return sent_count
