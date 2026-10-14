"""Custom Django Email Backend for Resend Transactional Email API."""

from __future__ import annotations

import logging
from typing import Sequence

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail import EmailMessage

import resend

logger = logging.getLogger("apps.notifications")


class ResendEmailBackend(BaseEmailBackend):
    """
    Django EmailBackend implementation that sends transactional emails via the Resend API.
    
    Seamlessly supports standard Django email APIs:
    - send_mail()
    - EmailMessage.send()
    - EmailMultiAlternatives.send()
    """

    def __init__(
        self,
        api_key: str | None = None,
        fail_silently: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.api_key = api_key or getattr(settings, "RESEND_API_KEY", "")
        if self.api_key:
            resend.api_key = self.api_key

    def send_messages(self, email_messages: Sequence[EmailMessage]) -> int:
        """
        Send a list of EmailMessage objects via Resend.
        
        Returns the number of successfully delivered messages.
        """
        if not email_messages:
            return 0

        if not self.api_key:
            logger.warning("RESEND_API_KEY is not set. Email delivery skipped.")
            if not self.fail_silently:
                raise ValueError("RESEND_API_KEY is not configured.")
            return 0

        num_sent = 0
        for message in email_messages:
            sent = self._send_single_message(message)
            if sent:
                num_sent += 1

        return num_sent

    def _send_single_message(self, message: EmailMessage) -> bool:
        """Send a single EmailMessage object via Resend API."""
        try:
            to_addresses = list(message.to) if message.to else []
            if not to_addresses:
                logger.warning("EmailMessage has no recipient specified.")
                return False

            # Sender address resolution
            from_name = getattr(settings, "RESEND_FROM_NAME", "SevaJobs")
            from_addr = getattr(settings, "RESEND_FROM_EMAIL", "noreply@sevajobs.in")
            default_sender = f"{from_name} <{from_addr}>"
            sender = message.from_email or default_sender

            # Extract HTML alternative if present
            html_content = None
            if hasattr(message, "alternatives") and message.alternatives:
                for content, mimetype in message.alternatives:
                    if mimetype == "text/html":
                        html_content = content
                        break

            if not html_content and getattr(message, "content_subtype", "") == "html":
                html_content = message.body

            text_content = message.body or ""

            # Build Resend payload
            payload: dict = {
                "from": sender,
                "to": to_addresses,
                "subject": message.subject or "",
            }

            if html_content:
                payload["html"] = html_content
            if text_content:
                payload["text"] = text_content

            if message.reply_to:
                payload["reply_to"] = list(message.reply_to)
            if message.cc:
                payload["cc"] = list(message.cc)
            if message.bcc:
                payload["bcc"] = list(message.bcc)

            # Headers and metadata tags
            extra_headers = getattr(message, "extra_headers", None) or {}
            custom_headers = {k: v for k, v in extra_headers.items() if k.lower() != "provider_message_id"}
            if custom_headers:
                payload["headers"] = custom_headers

            tags = []
            c_val = custom_headers.get("X-Campaign-ID") or custom_headers.get("campaign_id")
            if c_val:
                tags.append({"name": "campaign_id", "value": str(c_val)[:256]})
            a_val = custom_headers.get("X-Alert-Type") or custom_headers.get("alert_type")
            if a_val:
                tags.append({"name": "alert_type", "value": str(a_val)[:256]})
            if tags:
                payload["tags"] = tags

            # Attachments support
            if getattr(message, "attachments", None):
                import base64
                attachments_payload = []
                for attachment in message.attachments:
                    if isinstance(attachment, tuple) and len(attachment) >= 2:
                        filename = attachment[0]
                        content = attachment[1]
                        if isinstance(content, str):
                            content = content.encode("utf-8")
                        b64_content = base64.b64encode(content).decode("utf-8")
                        attachments_payload.append({
                            "filename": filename,
                            "content": b64_content,
                        })
                if attachments_payload:
                    payload["attachments"] = attachments_payload

            # Invoke Resend SDK
            resend.api_key = self.api_key
            response = resend.Emails.send(payload)

            # Extract Resend Message ID
            msg_id = None
            if isinstance(response, dict):
                msg_id = response.get("id")
            elif hasattr(response, "id"):
                msg_id = getattr(response, "id")

            if msg_id:
                setattr(message, "provider_message_id", msg_id)
                if not hasattr(message, "extra_headers") or message.extra_headers is None:
                    message.extra_headers = {}
                message.extra_headers["provider_message_id"] = msg_id

            masked_recipients = [_mask_email(addr) for addr in to_addresses]
            logger.info(
                "Email sent via Resend. provider_message_id=%s recipients=%s subject='%s'",
                msg_id or "unknown",
                masked_recipients,
                message.subject,
            )
            return True

        except Exception as exc:
            masked_recipients = [_mask_email(addr) for addr in getattr(message, "to", [])]
            logger.error(
                "Resend email send failed for recipients=%s error=%s",
                masked_recipients,
                str(exc),
            )
            if not self.fail_silently:
                raise exc
            return False


def _mask_email(email: str) -> str:
    """Mask email for privacy in log files."""
    if not email or "@" not in email:
        return "***"
    name, domain = email.split("@", 1)
    if len(name) <= 2:
        masked_name = name[0] + "*"
    else:
        masked_name = name[0] + "*" * (len(name) - 2) + name[-1]
    return f"{masked_name}@{domain}"
