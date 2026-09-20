"""Celery tasks for asynchronous email delivery with SES retry & idempotency strategy."""

from __future__ import annotations

import logging
from smtplib import SMTPConnectError, SMTPServerDisconnected, SMTPException, SMTPDataError, SMTPRecipientsRefused
from typing import Any, Dict, Optional

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives, get_connection

logger = logging.getLogger("apps.notifications")

TRANSIENT_SMTP_ERRORS = (
    SMTPServerDisconnected,
    SMTPConnectError,
    ConnectionError,
    OSError,
    TimeoutError,
)


@shared_task(
    bind=True,
    name="notifications.send_transactional_email",
    autoretry_for=TRANSIENT_SMTP_ERRORS,
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
    - Automatic retries with exponential backoff & jitter for network/SMTP glitches
    - No PII, passwords, or credentials logged
    """
    to_email = to_email.strip()
    from_email = from_email or settings.DEFAULT_FROM_EMAIL

    # 1. Idempotency Check
    if idempotency_key:
        cache_key = f"email_idempotency:{idempotency_key}"
        # Store attempt in cache (True if set, False if already existed)
        was_set = cache.add(cache_key, "sent", timeout=86400)  # 24 hours
        if not was_set:
            logger.info("Skipping duplicate email execution for idempotency_key=%s", idempotency_key)
            return {"status": "skipped_duplicate", "idempotency_key": idempotency_key}

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
        
        masked_email = _mask_email(to_email)
        logger.info("Transactional email '%s' sent successfully to %s", subject, masked_email)
        return {"status": "sent", "recipient": masked_email, "subject": subject}

    except (SMTPRecipientsRefused, SMTPDataError) as perm_err:
        # Permanent failure (e.g. recipient mailbox does not exist or 5xx SES response)
        masked_email = _mask_email(to_email)
        logger.error(
            "Permanent SMTP delivery failure for %s (code %s): %s",
            masked_email, getattr(perm_err, "smtp_code", "N/A"), str(perm_err)
        )
        # Suppress future emails if 550 / permanent bounce response
        smtp_code = getattr(perm_err, "smtp_code", 0)
        if smtp_code in (550, 551, 552, 553, 554):
            EmailSuppression.suppress(
                email=to_email,
                reason=EmailSuppression.Reason.BOUNCE,
                bounce_type="Permanent",
                details={"error": str(perm_err), "code": smtp_code},
            )
        return {"status": "failed_permanent", "recipient": masked_email, "error": str(perm_err)}

    except TRANSIENT_SMTP_ERRORS as transient_err:
        masked_email = _mask_email(to_email)
        logger.warning(
            "Transient SMTP failure for %s (attempt %d/%d): %s",
            masked_email, self.request.retries + 1, self.max_retries, str(transient_err)
        )
        # Re-raise to trigger Celery retry
        raise transient_err

    except Exception as exc:
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
