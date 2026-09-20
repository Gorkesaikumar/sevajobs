"""Centralized transactional email service for SevaJobs."""

from __future__ import annotations

import logging
import hashlib
from typing import Any, Dict, Optional

from django.conf import settings
from django.db import transaction
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from .models import EmailSuppression

logger = logging.getLogger("apps.notifications")


class EmailService:
    """Centralized service for rendering HTML/Text email templates and queuing async email delivery."""

    @classmethod
    def send_template_email(
        cls,
        *,
        template_name: str,
        to_email: str,
        subject: str,
        context: Optional[Dict[str, Any]] = None,
        from_email: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> bool:
        """
        Render an HTML/text template pair and queue transactional email via Celery.
        
        :param template_name: Base name of template without extension (e.g. 'verification', 'welcome')
        :param to_email: Recipient email address
        :param subject: Email subject line
        :param context: Dict of variables passed to Django template renderer
        :param from_email: Optional custom sender (defaults to settings.DEFAULT_FROM_EMAIL)
        :param idempotency_key: Optional unique identifier to prevent duplicate emails
        :return: True if queued, False if skipped due to suppression or rendering failure.
        """
        to_email = to_email.strip()
        if not to_email:
            logger.warning("Empty recipient email passed to send_template_email.")
            return False

        # 1. Suppression Check
        if EmailSuppression.is_suppressed(to_email):
            logger.info("Email delivery to %s skipped because recipient is suppressed.", to_email)
            return False

        # 2. Build Context
        ctx = {
            "frontend_url": getattr(settings, "FRONTEND_URL", "http://localhost:3000"),
            "platform_name": "SevaJobs",
            "support_email": "support@sevajobs.in",
            "subject": subject,
            **(context or {}),
        }

        # 3. Render Templates
        html_template = f"emails/{template_name}.html"
        text_template = f"emails/{template_name}.txt"

        try:
            html_message = render_to_string(html_template, ctx)
        except Exception:
            logger.exception("Failed to render HTML email template %s", html_template)
            return False

        try:
            plain_message = render_to_string(text_template, ctx)
        except Exception:
            # Fallback to html-stripped text if .txt template is absent
            plain_message = strip_tags(html_message)

        # 4. Generate Idempotency Key if not explicitly supplied
        if not idempotency_key:
            # Generate deterministic key based on template + recipient + key context items if available
            ctx_digest = hashlib.md5(f"{template_name}:{to_email}:{ctx.get('token', '')}{ctx.get('application_id', '')}{ctx.get('job_id', '')}".encode()).hexdigest()
            idempotency_key = f"{template_name}:{ctx_digest}"

        # 5. Queue Task via transaction.on_commit to avoid race conditions with uncommitted DB transactions
        from .tasks import send_transactional_email_task

        def enqueue():
            send_transactional_email_task.delay(
                subject=subject,
                to_email=to_email,
                html_message=html_message,
                plain_message=plain_message,
                from_email=from_email or settings.DEFAULT_FROM_EMAIL,
                idempotency_key=idempotency_key,
            )

        if transaction.get_connection().in_atomic_block:
            transaction.on_commit(enqueue)
        else:
            enqueue()

        logger.info("Queued transactional email '%s' (%s) for recipient %s", subject, template_name, to_email)
        return True
