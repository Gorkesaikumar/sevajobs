"""Celery tasks for asynchronous email delivery with Resend retry & idempotency strategy."""

from __future__ import annotations

import logging
from smtplib import SMTPConnectError, SMTPServerDisconnected, SMTPException, SMTPDataError, SMTPRecipientsRefused
from typing import Any, Dict, Optional

import requests
try:
    from resend.exceptions import RateLimitError
except ImportError:
    RateLimitError = Exception

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives, get_connection
from django.db.models import Count, Q

logger = logging.getLogger("apps.notifications")

TRANSIENT_EMAIL_ERRORS = (
    SMTPServerDisconnected,
    SMTPConnectError,
    ConnectionError,
    OSError,
    TimeoutError,
    RateLimitError,
    requests.exceptions.RequestException,
)


@shared_task(
    bind=True,
    name="notifications.send_transactional_email",
    autoretry_for=TRANSIENT_EMAIL_ERRORS,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
)
def send_transactional_email_task(
    self,
    subject: str,
    to_email: str,
    html_message: str,
    plain_message: str,
    from_email: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Asynchronous Celery task for sending transactional email over Django's email backend.
    
    Features:
    - Idempotency guard via Redis cache (24h expiry)
    - Bounce/complaint suppression check
    - Automatic retries with exponential backoff & jitter for network errors
    - Safe logging with PII email masking
    """
    to_email = to_email.strip()
    from_email = from_email or settings.DEFAULT_FROM_EMAIL

    # 1. Idempotency Check
    sent_key = f"email_sent:{idempotency_key}" if idempotency_key else None
    lock_key = f"email_lock:{idempotency_key}" if idempotency_key else None

    if idempotency_key:
        # Check if email was already successfully delivered
        if cache.get(sent_key) == "sent" or cache.get(f"email_idempotency:{idempotency_key}") == "sent":
            logger.info("Skipping duplicate email execution for idempotency_key=%s", idempotency_key)
            return {"status": "skipped_duplicate", "idempotency_key": idempotency_key}

        # Concurrency guard: temporary processing lock (only on attempt 0)
        retries = getattr(self.request, "retries", 0)
        if lock_key and retries == 0:
            acquired = cache.add(lock_key, "processing", timeout=300)
            if not acquired:
                logger.info("Email task with idempotency_key=%s already processing by another worker.", idempotency_key)
                return {"status": "skipped_concurrent", "idempotency_key": idempotency_key}


    # 2. Suppression Check
    from .models import EmailSuppression
    if EmailSuppression.is_suppressed(to_email):
        masked_email = _mask_email(to_email)
        logger.warning("Recipient %s is in EmailSuppression list. Delivery aborted.", masked_email)
        return {"status": "skipped_suppressed", "recipient": masked_email}

    # 3. Construct and Dispatch Email
    try:
        connection = get_connection(fail_silently=False)
        msg = EmailMultiAlternatives(
            subject=subject,
            body=plain_message,
            from_email=from_email,
            to=[to_email],
            headers=headers or {},
            connection=connection,
        )
        if html_message:
            msg.attach_alternative(html_message, "text/html")
        
        msg.send(fail_silently=False)
        provider_msg_id = getattr(msg, "provider_message_id", "") or (
            msg.extra_headers.get("provider_message_id", "")
            if hasattr(msg, "extra_headers") and msg.extra_headers
            else ""
        )
        
        # Mark as successfully sent for idempotency (24h) and release processing lock
        if sent_key:
            cache.set(sent_key, "sent", timeout=86400)
            cache.set(f"email_idempotency:{idempotency_key}", "sent", timeout=86400)
        if lock_key:
            cache.delete(lock_key)

        masked_email = _mask_email(to_email)
        logger.info(
            "Transactional email '%s' sent successfully to %s. provider_message_id=%s",
            subject, masked_email, provider_msg_id or "unknown"
        )
        return {"status": "sent", "recipient": masked_email, "subject": subject, "provider_message_id": provider_msg_id}

    except (SMTPRecipientsRefused, SMTPDataError) as perm_err:
        if lock_key:
            cache.delete(lock_key)
        # Permanent failure (e.g. recipient mailbox does not exist or permanent bounce response)
        masked_email = _mask_email(to_email)
        logger.error(
            "Permanent delivery failure for %s: %s",
            masked_email, str(perm_err)
        )
        EmailSuppression.suppress(
            email=to_email,
            reason=EmailSuppression.Reason.BOUNCE,
            bounce_type="Permanent",
            details={"error": str(perm_err)},
        )
        return {"status": "failed_permanent", "recipient": masked_email, "error": str(perm_err)}

    except TRANSIENT_EMAIL_ERRORS as transient_err:
        if lock_key:
            cache.delete(lock_key)
        masked_email = _mask_email(to_email)
        logger.warning(
            "Transient delivery failure for %s (attempt %d/%d): %s",
            masked_email, self.request.retries + 1, self.max_retries, str(transient_err)
        )
        raise transient_err

    except Exception as exc:
        if lock_key:
            cache.delete(lock_key)
        masked_email = _mask_email(to_email)
        logger.exception("Unexpected error delivering email to %s: %s", masked_email, str(exc))
        raise exc



def _mask_email(email: str) -> str:
    """Mask email for privacy in logs (e.g., j***n@example.com)."""
    if not email or "@" not in email:
        return "***"
    name, domain = email.split("@", 1)
    if len(name) <= 2:
        masked_name = name[0] + "*"
    else:
        masked_name = name[0] + "*" * (len(name) - 2) + name[-1]
    return f"{masked_name}@{domain}"


@shared_task(
    bind=True,
    name="notifications.send_bulk_campaign",
    max_retries=3,
    time_limit=3600,
)
def send_bulk_campaign_task(self, campaign_id: str) -> Dict[str, Any]:
    """
    Celery task for executing a queued bulk email campaign.
    Iterates through CampaignRecipient records, enforces per-recipient suppression,
    renders personalized content, and executes strictly 1-to-1 dispatches.
    """
    from django.utils import timezone
    from django.utils.html import strip_tags
    from django.core.mail import EmailMultiAlternatives, get_connection
    from .models import EmailCampaign, CampaignRecipient, EmailSuppression
    from .campaign_service import CampaignService
    from .unsubscribe_service import UnsubscribeService
    from .quota_service import DailyEmailQuotaService

    try:
        campaign = EmailCampaign.objects.get(pk=campaign_id)
    except EmailCampaign.DoesNotExist:
        logger.error("send_bulk_campaign_task aborted: EmailCampaign %s does not exist.", campaign_id)
        return {"status": "error", "message": "Campaign does not exist."}

    # If already cancelled or completed, abort
    if campaign.status in [EmailCampaign.Status.CANCELLED, EmailCampaign.Status.COMPLETED]:
        logger.info("Campaign %s is in state '%s'; execution halted.", campaign_id, campaign.status)
        return {"status": "halted", "campaign_status": campaign.status}

    # Transition to PROCESSING
    if campaign.status in [EmailCampaign.Status.QUEUED, EmailCampaign.Status.DRAFT]:
        campaign.transition_to(EmailCampaign.Status.PROCESSING)
    elif campaign.can_transition_to(EmailCampaign.Status.PROCESSING):
        campaign.transition_to(EmailCampaign.Status.PROCESSING)

    recipients_qs = campaign.recipients.filter(
        status__in=[CampaignRecipient.RecipientStatus.QUEUED, CampaignRecipient.RecipientStatus.PENDING]
    ).select_related("candidate", "match").order_by("created_at")

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "SevaJobs <noreply@sevajobs.in>")
    connection = get_connection(fail_silently=False)

    batch_processed = 0

    for recipient in recipients_qs.iterator(chunk_size=100):
        # Check if campaign was cancelled during processing
        campaign.refresh_from_db(fields=["status"])
        if campaign.status == EmailCampaign.Status.CANCELLED:
            logger.info("Campaign %s was cancelled during execution. Halting recipient loop.", campaign_id)
            break

        email_addr = recipient.email.strip().lower()

        # Real-time suppression check
        if EmailSuppression.is_suppressed(email_addr):
            recipient.status = CampaignRecipient.RecipientStatus.SUPPRESSED
            recipient.last_error = "Recipient suppressed (bounce, complaint, or unsubscribed)"
            recipient.save(update_fields=["status", "last_error", "updated_at"])
            campaign.suppressed_count += 1
            DailyEmailQuotaService.release_reserved_quota(1)
            continue

        # Build personalized context
        unsubscribe_url = UnsubscribeService.build_unsubscribe_url(email_addr)
        cand_name = recipient.recipient_name
        if not cand_name and recipient.candidate:
            cand_name = recipient.candidate.get_full_name() or recipient.candidate.first_name
        if not cand_name:
            cand_name = email_addr.split("@")[0]

        req_title = campaign.requirement.subject if campaign.requirement else ""
        school_name = campaign.requirement.institution_name if campaign.requirement else ""
        location = campaign.requirement.location if campaign.requirement else ""
        cand_status = recipient.match.get_status_display() if recipient.match else ""

        ctx = {
            "candidate_name": cand_name,
            "requirement_title": req_title,
            "school_name": school_name,
            "location": location,
            "candidate_status": cand_status,
            "support_email": getattr(settings, "RESEND_FROM_EMAIL", "noreply@sevajobs.in"),
            "unsubscribe_url": unsubscribe_url,
        }

        rendered_subject = CampaignService.render_content(body_template=campaign.subject, context=ctx)
        clean_subject = CampaignService.sanitize_subject(rendered_subject) or campaign.subject

        rendered_body = CampaignService.render_content(body_template=campaign.body_html, context=ctx)
        wrapped_html = CampaignService.wrap_in_base_email(
            rendered_body_html=rendered_body,
            subject=clean_subject,
            unsubscribe_url=unsubscribe_url,
        )
        plain_body = campaign.body_plain
        if not plain_body:
            plain_body = strip_tags(rendered_body)
        else:
            plain_body = CampaignService.render_content(body_template=plain_body, context=ctx)
        if plain_body and unsubscribe_url not in plain_body:
            plain_body += f"\n\n---\nTo unsubscribe: {unsubscribe_url}"

        # Dispatch 1-to-1
        headers = {
            "List-Unsubscribe": f"<{unsubscribe_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            "X-Campaign-ID": str(campaign.id),
            "X-Recipient-ID": str(recipient.id),
        }

        recipient.status = CampaignRecipient.RecipientStatus.SENDING
        recipient.attempt_count += 1
        recipient.save(update_fields=["status", "attempt_count", "updated_at"])

        try:
            msg = EmailMultiAlternatives(
                subject=clean_subject,
                body=plain_body,
                from_email=from_email,
                to=[email_addr],
                headers=headers,
                connection=connection,
            )
            msg.attach_alternative(wrapped_html, "text/html")
            msg.send(fail_silently=False)

            provider_msg_id = getattr(msg, "provider_message_id", "") or (
                msg.extra_headers.get("provider_message_id", "")
                if hasattr(msg, "extra_headers") and msg.extra_headers
                else ""
            )
            recipient.status = CampaignRecipient.RecipientStatus.SENT
            recipient.sent_at = timezone.now()
            recipient.provider_message_id = provider_msg_id
            recipient.save(update_fields=["status", "sent_at", "provider_message_id", "updated_at"])
            DailyEmailQuotaService.record_send_success(1)

        except Exception as exc:
            logger.warning("Failed to send campaign email to %s: %s", _mask_email(email_addr), exc)
            recipient.status = CampaignRecipient.RecipientStatus.FAILED
            recipient.last_error = str(exc)[:500]
            recipient.failed_at = timezone.now()
            recipient.save(update_fields=["status", "last_error", "failed_at", "updated_at"])
            DailyEmailQuotaService.record_send_failure(1, error=str(exc))

    # Finalize Campaign State
    latest_status = EmailCampaign.objects.filter(pk=campaign.id).values_list("status", flat=True).first()
    if latest_status == EmailCampaign.Status.CANCELLED:
        campaign.status = EmailCampaign.Status.CANCELLED
    else:
        from django.db.models import Count, Q
        recipient_counts = campaign.recipients.aggregate(
            sent=Count("id", filter=Q(status__in=[CampaignRecipient.RecipientStatus.SENT, CampaignRecipient.RecipientStatus.DELIVERED])),
            failed=Count("id", filter=Q(status=CampaignRecipient.RecipientStatus.FAILED)),
            suppressed=Count("id", filter=Q(status=CampaignRecipient.RecipientStatus.SUPPRESSED)),
            pending=Count("id", filter=Q(status__in=[CampaignRecipient.RecipientStatus.QUEUED, CampaignRecipient.RecipientStatus.PENDING])),
        )
        campaign.sent_count = recipient_counts["sent"] or 0
        campaign.failed_count = recipient_counts["failed"] or 0
        campaign.suppressed_count = recipient_counts["suppressed"] or 0
        campaign.pending_count = recipient_counts["pending"] or 0

        if campaign.pending_count == 0:
            if campaign.failed_count == 0:
                campaign.transition_to(EmailCampaign.Status.COMPLETED, save=False)
            elif campaign.sent_count > 0:
                campaign.transition_to(EmailCampaign.Status.PARTIALLY_FAILED, save=False)
            else:
                campaign.transition_to(EmailCampaign.Status.FAILED, save=False)
        campaign.save(update_fields=["status", "pending_count", "sent_count", "failed_count", "suppressed_count", "completed_at", "updated_at"])

    logger.info(
        "Finished bulk campaign %s. Sent=%d, Failed=%d, Suppressed=%d, Final Status=%s",
        campaign.id, campaign.sent_count, campaign.failed_count, campaign.suppressed_count, campaign.status
    )
    return {
        "status": "finished",
        "campaign_id": str(campaign.id),
        "campaign_status": campaign.status,
        "sent": campaign.sent_count,
        "failed": campaign.failed_count,
        "suppressed": campaign.suppressed_count,
    }


@shared_task(
    bind=True,
    name="notifications.send_bulk_job_alerts",
    max_retries=3,
    time_limit=3600,
)
def send_bulk_job_alerts_task(self, campaign_id: str) -> Dict[str, Any]:
    """
    Celery task for executing a queued bulk job alert campaign.
    Revalidates vacancies in real time, applies deduplication, respects daily email quota,
    and records persistent candidate-job delivery records.
    """
    from django.utils import timezone
    from django.utils.html import strip_tags
    from django.core.mail import EmailMultiAlternatives, get_connection
    from apps.jobs.models import Job, StaffJob
    from .models import (
        JobAlertCampaign,
        JobAlertRecipient,
        CandidateJobAlertDelivery,
        EmailSuppression,
    )
    from .job_alert_service import JobAlertCampaignService
    from .unsubscribe_service import UnsubscribeService, JobAlertPreferenceService
    from .quota_service import DailyEmailQuotaService

    try:
        campaign = JobAlertCampaign.objects.get(pk=campaign_id)
    except JobAlertCampaign.DoesNotExist:
        logger.error("send_bulk_job_alerts_task aborted: JobAlertCampaign %s does not exist.", campaign_id)
        return {"status": "error", "message": "Campaign does not exist."}

    if campaign.status in [JobAlertCampaign.Status.CANCELLED, JobAlertCampaign.Status.COMPLETED]:
        logger.info("JobAlertCampaign %s is in state '%s'; execution halted.", campaign_id, campaign.status)
        return {"status": "halted", "campaign_status": campaign.status}

    if campaign.status in [JobAlertCampaign.Status.QUEUED, JobAlertCampaign.Status.DRAFT]:
        campaign.transition_to(JobAlertCampaign.Status.PROCESSING)
    elif campaign.can_transition_to(JobAlertCampaign.Status.PROCESSING):
        campaign.transition_to(JobAlertCampaign.Status.PROCESSING)

    recipients_qs = campaign.recipients.filter(
        status__in=[JobAlertRecipient.RecipientStatus.QUEUED, JobAlertRecipient.RecipientStatus.PENDING]
    ).select_related("candidate", "candidate__job_seeker_profile", "employer").order_by("created_at")

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "SevaJobs <noreply@sevajobs.in>")
    connection = get_connection(fail_silently=False)
    today = timezone.now().date()

    for recipient in recipients_qs.iterator(chunk_size=100):
        # Check if campaign was cancelled during processing
        campaign.refresh_from_db(fields=["status"])
        if campaign.status == JobAlertCampaign.Status.CANCELLED:
            logger.info("JobAlertCampaign %s was cancelled during execution. Halting recipient loop.", campaign_id)
            break

        email_addr = recipient.email.strip().lower()

        # 1. Real-time suppression & opt-out check
        if EmailSuppression.is_suppressed(email_addr):
            recipient.status = JobAlertRecipient.RecipientStatus.SUPPRESSED
            recipient.last_error = "Recipient suppressed (bounce, complaint, or unsubscribed)"
            recipient.save(update_fields=["status", "last_error", "updated_at"])
            campaign.suppressed_count += 1
            DailyEmailQuotaService.release_reserved_quota(1)
            continue

        cand = recipient.candidate
        if cand and hasattr(cand, "job_seeker_profile") and not cand.job_seeker_profile.job_alerts_enabled:
            recipient.status = JobAlertRecipient.RecipientStatus.SUPPRESSED
            recipient.last_error = "Candidate has opted out of Job Alerts"
            recipient.save(update_fields=["status", "last_error", "updated_at"])
            campaign.suppressed_count += 1
            DailyEmailQuotaService.release_reserved_quota(1)
            continue

        # 2. Revalidate vacancies / event status in real-time immediately before dispatch
        if campaign.alert_type in (JobAlertCampaign.AlertType.EMPLOYER_ALERT, "employer", "employer_alert"):
            valid_jobs = []

        elif campaign.alert_type in (JobAlertCampaign.AlertType.WALKIN_ALERT, "walkin", "walkin_alert"):
            walkin_job = campaign.walkin_job
            if walkin_job:
                if not walkin_job.is_active or walkin_job.status != Job.Status.ACTIVE:
                    recipient.status = JobAlertRecipient.RecipientStatus.SKIPPED
                    recipient.last_error = "Walk-in vacancy is no longer active or approved."
                    recipient.save(update_fields=["status", "last_error", "updated_at"])
                    campaign.skipped_count += 1
                    DailyEmailQuotaService.release_reserved_quota(1)
                    continue

                if walkin_job.walkin_end_date and walkin_job.walkin_end_date < today:
                    recipient.status = JobAlertRecipient.RecipientStatus.SKIPPED
                    recipient.last_error = "Walk-in event date has already passed."
                    recipient.save(update_fields=["status", "last_error", "updated_at"])
                    campaign.skipped_count += 1
                    DailyEmailQuotaService.release_reserved_quota(1)
                    continue

            valid_jobs = recipient.matched_jobs_data or []

        elif campaign.alert_type in (JobAlertCampaign.AlertType.REQUIREMENT_ALERT, "requirement", "requirement_alert"):
            req = campaign.requirement
            if req and req.status.lower() in ["closed", "rejected", "draft", "on_hold"]:
                recipient.status = JobAlertRecipient.RecipientStatus.SKIPPED
                recipient.last_error = f"Institutional requirement is inactive (status: {req.status})."
                recipient.save(update_fields=["status", "last_error", "updated_at"])
                campaign.skipped_count += 1
                DailyEmailQuotaService.release_reserved_quota(1)
                continue

            valid_jobs = recipient.matched_jobs_data or []

        elif campaign.alert_type in (JobAlertCampaign.AlertType.INTERVIEW_ALERT, "interview", "interview_alert"):
            valid_jobs = recipient.matched_jobs_data or []

        else:
            # Type 1: DAILY_DIGEST (or general job alert)
            raw_jobs = recipient.matched_jobs_data or []
            valid_jobs = []

            for j_data in raw_jobs:
                j_id = j_data.get("id")
                j_type = j_data.get("type", "recruiter")

                # Check deduplication window
                if cand and CandidateJobAlertDelivery.is_duplicate(
                    candidate_id=cand.id,
                    job_id=j_id,
                    dedup_window_days=14,
                ):
                    continue

                # Verify vacancy still active and not expired
                if j_type == "recruiter":
                    job_exists = Job.objects.filter(
                        id=j_id,
                        is_active=True,
                        status=Job.Status.ACTIVE,
                        approval_status=Job.ApprovalStatus.APPROVED,
                    ).filter(Q(deadline__isnull=True) | Q(deadline__gte=today)).exists()
                else:
                    job_exists = StaffJob.objects.filter(
                        id=j_id,
                        is_active=True,
                        status=StaffJob.Status.ACTIVE,
                    ).exists()

                if job_exists:
                    valid_jobs.append(j_data)

            if not valid_jobs:
                recipient.status = JobAlertRecipient.RecipientStatus.SKIPPED
                recipient.last_error = "All matched vacancies have expired, closed, or were already delivered prior to dispatch"
                recipient.save(update_fields=["status", "last_error", "updated_at"])
                campaign.skipped_count += 1
                DailyEmailQuotaService.release_reserved_quota(1)
                continue

            # Update recipient's job snapshot with validated jobs
            recipient.matched_job_count = len(valid_jobs)
            recipient.matched_jobs_data = valid_jobs

        # 3. Build personalized content via centralized context helper
        ctx = JobAlertCampaignService.build_context_for_recipient(
            campaign=campaign,
            recipient=recipient,
            valid_jobs=valid_jobs,
        )

        rendered_subject = JobAlertCampaignService.render_content(body_template=campaign.subject, context=ctx)
        clean_subject = JobAlertCampaignService.sanitize_subject(rendered_subject) or campaign.subject

        rendered_body = JobAlertCampaignService.render_content(body_template=campaign.body_html, context=ctx)
        wrapped_html = JobAlertCampaignService.wrap_in_base_email(
            rendered_body_html=rendered_body,
            subject=clean_subject,
            unsubscribe_url=ctx["unsubscribe_url"],
            preferences_url=ctx["preferences_url"],
        )

        plain_body = campaign.body_plain
        if not plain_body:
            plain_body = strip_tags(rendered_body)
        else:
            plain_body = JobAlertCampaignService.render_content(body_template=plain_body, context=ctx)

        if campaign.alert_type == JobAlertCampaign.AlertType.DAILY_DIGEST:
            matching_jobs_plain = ctx.get("matching_jobs_plain", "")
            if matching_jobs_plain and matching_jobs_plain not in plain_body:
                plain_body += f"\n\nMatching Vacancies:\n{matching_jobs_plain}"

        if ctx["unsubscribe_url"] not in plain_body:
            plain_body += f"\n\n---\nPreferences: {ctx['preferences_url']}\nUnsubscribe: {ctx['unsubscribe_url']}"

        headers = {
            "List-Unsubscribe": f"<{ctx['unsubscribe_url']}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            "X-Campaign-ID": str(campaign.id),
            "X-JobAlert-Recipient-ID": str(recipient.id),
            "X-Alert-Type": campaign.alert_type,
            "X-Priority": str(campaign.priority),
        }

        recipient.status = JobAlertRecipient.RecipientStatus.SENDING
        recipient.attempt_count += 1
        recipient.save(update_fields=["status", "attempt_count", "matched_job_count", "matched_jobs_data", "updated_at"])

        try:
            msg = EmailMultiAlternatives(
                subject=clean_subject,
                body=plain_body,
                from_email=from_email,
                to=[email_addr],
                headers=headers,
                connection=connection,
            )
            msg.attach_alternative(wrapped_html, "text/html")
            msg.send(fail_silently=False)

            provider_msg_id = getattr(msg, "provider_message_id", "") or (
                msg.extra_headers.get("provider_message_id", "")
                if hasattr(msg, "extra_headers") and msg.extra_headers
                else ""
            )
            recipient.status = JobAlertRecipient.RecipientStatus.SENT
            recipient.sent_at = timezone.now()
            recipient.provider_message_id = provider_msg_id
            recipient.save(update_fields=["status", "sent_at", "provider_message_id", "updated_at"])
            DailyEmailQuotaService.record_send_success(1)

            # Record persistent deduplication history for each delivered job/event
            if cand:
                if campaign.alert_type in (JobAlertCampaign.AlertType.WALKIN_ALERT, "walkin", "walkin_alert"):
                    walkin_id = campaign.walkin_job.id if campaign.walkin_job else campaign.id
                    CandidateJobAlertDelivery.record_delivery(
                        candidate=cand,
                        job_id=walkin_id,
                        job_type=CandidateJobAlertDelivery.JobType.WALKIN,
                        campaign=campaign,
                        recipient=recipient,
                        status="sent",
                        provider_message_id=recipient.provider_message_id,
                        sent_at=recipient.sent_at,
                    )
                elif campaign.alert_type in (JobAlertCampaign.AlertType.REQUIREMENT_ALERT, "requirement", "requirement_alert") and campaign.requirement:
                    CandidateJobAlertDelivery.record_delivery(
                        candidate=cand,
                        job_id=campaign.requirement.id,
                        job_type=CandidateJobAlertDelivery.JobType.REQUIREMENT,
                        campaign=campaign,
                        recipient=recipient,
                        status="sent",
                        provider_message_id=recipient.provider_message_id,
                        sent_at=recipient.sent_at,
                    )
                elif campaign.alert_type in (JobAlertCampaign.AlertType.INTERVIEW_ALERT, "interview", "interview_alert"):
                    match_id = (recipient.metadata or {}).get("match_id") or recipient.id
                    CandidateJobAlertDelivery.record_delivery(
                        candidate=cand,
                        job_id=match_id,
                        job_type=CandidateJobAlertDelivery.JobType.INTERVIEW,
                        campaign=campaign,
                        recipient=recipient,
                        status="sent",
                        provider_message_id=recipient.provider_message_id,
                        sent_at=recipient.sent_at,
                    )
                elif valid_jobs:
                    for j_item in valid_jobs:
                        CandidateJobAlertDelivery.record_delivery(
                            candidate=cand,
                            job_id=j_item["id"],
                            job_type=j_item.get("type", "recruiter"),
                            campaign=campaign,
                            recipient=recipient,
                            status="sent",
                            provider_message_id=recipient.provider_message_id,
                            sent_at=recipient.sent_at,
                        )

        except Exception as exc:
            logger.warning("Failed to send job alert email to %s: %s", _mask_email(email_addr), exc)
            recipient.status = JobAlertRecipient.RecipientStatus.FAILED
            recipient.last_error = str(exc)[:500]
            recipient.failed_at = timezone.now()
            recipient.save(update_fields=["status", "last_error", "failed_at", "updated_at"])
            DailyEmailQuotaService.record_send_failure(1, error=str(exc))

    # Finalize Campaign State
    latest_status = JobAlertCampaign.objects.filter(pk=campaign.id).values_list("status", flat=True).first()
    if latest_status == JobAlertCampaign.Status.CANCELLED:
        campaign.status = JobAlertCampaign.Status.CANCELLED
    else:
        counts = campaign.recipients.aggregate(
            sent=Count("id", filter=Q(status__in=[JobAlertRecipient.RecipientStatus.SENT, JobAlertRecipient.RecipientStatus.DELIVERED])),
            failed=Count("id", filter=Q(status=JobAlertRecipient.RecipientStatus.FAILED)),
            suppressed=Count("id", filter=Q(status=JobAlertRecipient.RecipientStatus.SUPPRESSED)),
            skipped=Count("id", filter=Q(status=JobAlertRecipient.RecipientStatus.SKIPPED)),
            pending=Count("id", filter=Q(status__in=[JobAlertRecipient.RecipientStatus.QUEUED, JobAlertRecipient.RecipientStatus.PENDING])),
        )
        campaign.sent_count = counts["sent"] or 0
        campaign.failed_count = counts["failed"] or 0
        campaign.suppressed_count = counts["suppressed"] or 0
        campaign.skipped_count = counts["skipped"] or 0
        campaign.pending_count = counts["pending"] or 0

        if campaign.pending_count == 0:
            if campaign.failed_count == 0:
                campaign.transition_to(JobAlertCampaign.Status.COMPLETED, save=False)
            elif campaign.sent_count > 0:
                campaign.transition_to(JobAlertCampaign.Status.PARTIALLY_FAILED, save=False)
            else:
                campaign.transition_to(JobAlertCampaign.Status.FAILED, save=False)
        campaign.save(update_fields=["status", "pending_count", "sent_count", "failed_count", "suppressed_count", "skipped_count", "completed_at", "updated_at"])

    logger.info(
        "Finished JobAlertCampaign %s. Sent=%d, Failed=%d, Suppressed=%d, Skipped=%d, Status=%s",
        campaign.id, campaign.sent_count, campaign.failed_count, campaign.suppressed_count, campaign.skipped_count, campaign.status
    )
    return {
        "status": "finished",
        "campaign_id": str(campaign.id),
        "campaign_status": campaign.status,
        "sent": campaign.sent_count,
        "failed": campaign.failed_count,
        "suppressed": campaign.suppressed_count,
        "skipped": campaign.skipped_count,
    }


@shared_task(
    name="notifications.send_daily_job_alerts_digest",
    bind=True,
    max_retries=3,
)
def send_daily_job_alerts_digest(self) -> Dict[str, Any]:
    """
    Persistent Celery Beat task executed daily at 10:00 AM IST.
    Gathers active job seekers with matching vacancies, checks 14-day deduplication,
    groups up to 5 matching jobs into one personalized digest per candidate,
    verifies quota availability, and dispatches the daily job alert campaign.
    """
    from .job_alert_service import JobAlertCampaignService
    from .models import JobAlertCampaign
    from .default_templates import FIVE_ALERT_TEMPLATES, DEFAULT_JOB_ALERT_TEMPLATE
    from apps.jobs.job_alert_matching_service import CandidateJobAlertMatchingService
    from .quota_service import DailyEmailQuotaService
    from apps.accounts.models import User

    logger.info("Starting Daily Job Alert Digest (10:00 AM IST scheduled run)...")

    # 1. Check if schedule is paused / disabled by administrator
    if not JobAlertCampaignService.is_daily_schedule_enabled():
        logger.info("Daily job alert schedule is currently paused/disabled by administrator. Skipping run.")
        return {"status": "paused_by_admin"}

    # 2. Check quota availability
    quota_status = DailyEmailQuotaService.get_quota_status()
    if quota_status.get("remaining", 0) <= 0:
        quota_used = quota_status.get("used", quota_status.get("total_consumed", 0))
        quota_limit = quota_status.get("daily_limit", 100)
        logger.warning(
            "Daily email quota exhausted (%d/%d used). Cannot dispatch daily job alerts.",
            quota_used,
            quota_limit,
        )
        return {"status": "quota_exhausted"}

    # 3. Evaluate audience for eligible candidates who have matching vacancies
    # and haven't received them within 14 days
    eval_result = CandidateJobAlertMatchingService.evaluate_audience(
        filters={"alerts_enabled_only": True, "active_only": True},
        dedup_window_days=14,
    )

    eligible_reviews = [c for c in eval_result["candidates_review"] if c["is_eligible"] and c["matched_jobs"]]
    if not eligible_reviews:
        logger.info("No candidates have new matching vacancies today. Skipping empty digest dispatch.")
        return {"status": "no_eligible_vacancies"}

    # Cap at remaining quota to avoid exceeding hard limit
    capped_reviews = eligible_reviews[: quota_status["remaining"]]
    candidate_ids = [c["candidate_id"] for c in capped_reviews]

    # Find system/admin user for campaign ownership
    admin_user = (
        User.objects.filter(role="admin", is_active=True).first()
        or User.objects.filter(is_superuser=True).first()
        or User.objects.filter(is_staff=True).first()
    )

    today_str = timezone.now().strftime("%b %d, %Y")
    template_def = FIVE_ALERT_TEMPLATES.get("daily_digest", DEFAULT_JOB_ALERT_TEMPLATE)

    campaign = JobAlertCampaignService.create_campaign(
        created_by=admin_user,
        name=f"Daily Job Alerts Digest — {today_str}",
        subject=template_def["subject"],
        body_html=template_def["body_html"],
        body_plain=template_def.get("body_plain", ""),
        alert_type=JobAlertCampaign.AlertType.DAILY_DIGEST,
        priority=4,
        is_recurring=True,
        recurring_enabled=True,
        candidate_ids=candidate_ids,
        dedup_window_days=14,
    )

    # Launch campaign
    JobAlertCampaignService.launch_campaign(str(campaign.id))
    logger.info("Launched Daily Job Alert Digest Campaign id=%s for %d candidates", campaign.id, campaign.total_recipients)
    return {
        "status": "launched",
        "campaign_id": str(campaign.id),
        "recipient_count": campaign.total_recipients,
    }


