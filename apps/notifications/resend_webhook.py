"""Production-grade Webhook Endpoint for Resend Transactional Email Events."""

from __future__ import annotations

import json
import logging
from typing import Dict, Any

from django.conf import settings
from django.core.cache import cache
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from .models import EmailSuppression

logger = logging.getLogger("apps.notifications")


@extend_schema(tags=["notifications"])
class ResendWebhookView(APIView):
    """
    POST /api/v1/notifications/webhooks/resend/
    
    Receives Resend webhook events (e.g. email.bounced, email.complained, email.delivered).
    Verifies cryptographic Svix signatures using RESEND_WEBHOOK_SECRET.
    Records permanent bounces & spam complaints in EmailSuppression table idempotently.
    """

    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs) -> Response:
        raw_body = request.body
        headers = {k.lower(): v for k, v in request.headers.items()}

        # 1. Cryptographic Signature Verification via Svix
        webhook_secret = getattr(settings, "RESEND_WEBHOOK_SECRET", "")
        if webhook_secret:
            verified_payload = self._verify_signature(raw_body, headers, webhook_secret)
            if verified_payload is None:
                logger.warning("Resend webhook signature verification failed.")
                return Response(
                    {"detail": "Invalid or missing webhook signature."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            payload = verified_payload
        else:
            # Fallback for environments where RESEND_WEBHOOK_SECRET is not configured yet
            if getattr(settings, "DEBUG", False):
                logger.warning("RESEND_WEBHOOK_SECRET not set. Processing unverified webhook in DEBUG mode.")
                try:
                    payload = json.loads(raw_body.decode("utf-8"))
                except Exception:
                    return Response({"detail": "Invalid JSON payload."}, status=status.HTTP_400_BAD_REQUEST)
            else:
                logger.error("RESEND_WEBHOOK_SECRET is required in production.")
                return Response(
                    {"detail": "Webhook secret not configured."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        # 2. Extract Event Data
        event_type = payload.get("type", "")
        data = payload.get("data", {})
        if not isinstance(data, dict):
            data = {}

        event_id = headers.get("svix-id") or data.get("email_id") or data.get("id") or payload.get("created_at", "")

        # 3. Idempotency Guard (Redis cache for 24 hours)
        if event_id:
            cache_key = f"resend_webhook_event:{event_id}"
            was_set = cache.add(cache_key, "processed", timeout=86400)
            if not was_set:
                logger.info("Duplicate Resend webhook event received: event_id=%s", event_id)
                return Response({"status": "duplicate_ignored", "event_id": event_id})

        # 4. Handle Specific Event Types
        from django.utils import timezone
        from django.db import models as dj_models
        from .models import CampaignRecipient, EmailCampaign, JobAlertRecipient, JobAlertCampaign

        resend_email_id = data.get("email_id") or data.get("id") or ""

        if event_type == "email.bounced":
            recipients = self._extract_recipients(data)
            bounce_type = str(data.get("bounce_type", "Permanent"))
            
            for email in recipients:
                details = {
                    "resend_event_id": event_id,
                    "resend_email_id": resend_email_id,
                    "event_type": event_type,
                    "bounce_type": bounce_type,
                    "timestamp": payload.get("created_at", ""),
                }
                EmailSuppression.suppress(
                    email=email,
                    reason=EmailSuppression.Reason.BOUNCE,
                    bounce_type=bounce_type[:50],
                    details=details,
                )
                logger.warning("Recorded Resend bounce suppression for recipient=%s", email)

                matched = False
                # Update matching campaign recipient
                cr_qs = CampaignRecipient.objects.filter(email=email)
                if resend_email_id:
                    cr = cr_qs.filter(provider_message_id=resend_email_id).first()
                else:
                    cr = cr_qs.filter(status=CampaignRecipient.RecipientStatus.SENT).order_by("-sent_at").first()
                if cr:
                    cr.status = CampaignRecipient.RecipientStatus.FAILED
                    cr.last_error = f"Resend Bounce ({bounce_type})"
                    cr.failed_at = timezone.now()
                    cr.save(update_fields=["status", "last_error", "failed_at", "updated_at"])
                    matched = True

                # Update matching job alert recipient only if not already matched to campaign recipient
                jar_qs = JobAlertRecipient.objects.filter(email=email)
                if resend_email_id:
                    jar = jar_qs.filter(provider_message_id=resend_email_id).first()
                elif not matched:
                    jar = jar_qs.filter(status=JobAlertRecipient.RecipientStatus.SENT).order_by("-sent_at").first()
                else:
                    jar = None

                if jar:
                    jar.status = JobAlertRecipient.RecipientStatus.FAILED
                    jar.last_error = f"Resend Bounce ({bounce_type})"
                    jar.failed_at = timezone.now()
                    jar.save(update_fields=["status", "last_error", "failed_at", "updated_at"])
                    JobAlertCampaign.objects.filter(pk=jar.campaign_id).update(failed_count=dj_models.F("failed_count") + 1)

            return Response({"status": "processed", "event_type": event_type})

        elif event_type == "email.complained":
            recipients = self._extract_recipients(data)
            
            for email in recipients:
                details = {
                    "resend_event_id": event_id,
                    "resend_email_id": resend_email_id,
                    "event_type": event_type,
                    "timestamp": payload.get("created_at", ""),
                }
                EmailSuppression.suppress(
                    email=email,
                    reason=EmailSuppression.Reason.COMPLAINT,
                    details=details,
                )
                logger.warning("Recorded Resend spam complaint suppression for recipient=%s", email)

                matched = False
                cr_qs = CampaignRecipient.objects.filter(email=email)
                if resend_email_id:
                    cr = cr_qs.filter(provider_message_id=resend_email_id).first()
                else:
                    cr = cr_qs.filter(status=CampaignRecipient.RecipientStatus.SENT).order_by("-sent_at").first()
                if cr:
                    cr.status = CampaignRecipient.RecipientStatus.FAILED
                    cr.last_error = "Resend Spam Complaint"
                    cr.failed_at = timezone.now()
                    cr.save(update_fields=["status", "last_error", "failed_at", "updated_at"])
                    matched = True

                jar_qs = JobAlertRecipient.objects.filter(email=email)
                if resend_email_id:
                    jar = jar_qs.filter(provider_message_id=resend_email_id).first()
                elif not matched:
                    jar = jar_qs.filter(status=JobAlertRecipient.RecipientStatus.SENT).order_by("-sent_at").first()
                else:
                    jar = None

                if jar:
                    jar.status = JobAlertRecipient.RecipientStatus.FAILED
                    jar.last_error = "Resend Spam Complaint"
                    jar.failed_at = timezone.now()
                    jar.save(update_fields=["status", "last_error", "failed_at", "updated_at"])
                    JobAlertCampaign.objects.filter(pk=jar.campaign_id).update(failed_count=dj_models.F("failed_count") + 1)

            return Response({"status": "processed", "event_type": event_type})

        elif event_type == "email.delivered":
            from .quota_service import DailyEmailQuotaService
            recipients = self._extract_recipients(data)
            for email in recipients:
                matched = False
                cr_qs = CampaignRecipient.objects.filter(email=email)
                if resend_email_id:
                    cr = cr_qs.filter(provider_message_id=resend_email_id).first()
                else:
                    cr = cr_qs.filter(status=CampaignRecipient.RecipientStatus.SENT).order_by("-sent_at").first()

                if cr and cr.status != CampaignRecipient.RecipientStatus.DELIVERED:
                    cr.status = CampaignRecipient.RecipientStatus.DELIVERED
                    cr.delivered_at = timezone.now()
                    cr.save(update_fields=["status", "delivered_at", "updated_at"])
                    EmailCampaign.objects.filter(pk=cr.campaign_id).update(delivered_count=dj_models.F("delivered_count") + 1)
                    DailyEmailQuotaService.record_delivery_success(1)
                    matched = True

                jar_qs = JobAlertRecipient.objects.filter(email=email)
                if resend_email_id:
                    jar = jar_qs.filter(provider_message_id=resend_email_id).first()
                elif not matched:
                    jar = jar_qs.filter(status=JobAlertRecipient.RecipientStatus.SENT).order_by("-sent_at").first()
                else:
                    jar = None

                if jar and jar.status != JobAlertRecipient.RecipientStatus.DELIVERED:
                    jar.status = JobAlertRecipient.RecipientStatus.DELIVERED
                    jar.delivered_at = timezone.now()
                    jar.save(update_fields=["status", "delivered_at", "updated_at"])
                    JobAlertCampaign.objects.filter(pk=jar.campaign_id).update(delivered_count=dj_models.F("delivered_count") + 1)
                    DailyEmailQuotaService.record_delivery_success(1)

            logger.info("Resend delivered event processed: email_id=%s", resend_email_id)
            return Response({"status": "acknowledged", "event_type": event_type})

        elif event_type in ("email.sent", "email.opened", "email.clicked"):
            logger.info("Resend event received: type=%s email_id=%s", event_type, data.get("email_id") or data.get("id"))
            return Response({"status": "acknowledged", "event_type": event_type})

        logger.info("Unhandled Resend webhook event type=%s", event_type)
        return Response({"status": "ignored", "event_type": event_type})

    @staticmethod
    def _verify_signature(raw_body: bytes, headers: Dict[str, str], secret: str) -> Dict[str, Any] | None:
        """Verify Svix webhook signature using official svix package or HMAC SHA256."""
        try:
            from svix.webhooks import Webhook, WebhookVerificationError
            wh = Webhook(secret)
            # Svix requires headers dict containing svix-id, svix-timestamp, svix-signature
            wh.verify(raw_body.decode("utf-8"), headers)
            return json.loads(raw_body.decode("utf-8"))
        except ImportError:
            # Manual HMAC SHA256 verification if svix package is not installed
            return ResendWebhookView._manual_svix_verify(raw_body, headers, secret)
        except Exception as exc:
            logger.warning("Svix signature verification failed: %s", str(exc))
            return None

    @staticmethod
    def _manual_svix_verify(raw_body: bytes, headers: Dict[str, str], secret: str) -> Dict[str, Any] | None:
        """Fallback manual HMAC SHA256 Svix signature verification."""
        import base64
        import hmac
        import hashlib

        msg_id = headers.get("svix-id")
        msg_timestamp = headers.get("svix-timestamp")
        msg_signature = headers.get("svix-signature")

        if not msg_id or not msg_timestamp or not msg_signature:
            return None

        clean_secret = secret.replace("whsec_", "")
        try:
            secret_bytes = base64.b64decode(clean_secret)
        except Exception:
            secret_bytes = clean_secret.encode("utf-8")

        to_sign = f"{msg_id}.{msg_timestamp}.{raw_body.decode('utf-8')}".encode("utf-8")
        computed_hmac = hmac.new(secret_bytes, to_sign, hashlib.sha256).digest()
        computed_sig = base64.b64encode(computed_hmac).decode("utf-8")

        for sig_item in msg_signature.split(" "):
            parts = sig_item.split(",")
            if len(parts) == 2 and parts[0] == "v1":
                if hmac.compare_digest(parts[1], computed_sig):
                    try:
                        return json.loads(raw_body.decode("utf-8"))
                    except Exception:
                        return None
        return None

    @staticmethod
    def _extract_recipients(data: dict) -> list[str]:
        """Extract recipient emails from Resend event data object."""
        to_field = data.get("to")
        if isinstance(to_field, list):
            return [str(addr).strip().lower() for addr in to_field if addr]
        elif isinstance(to_field, str) and to_field.strip():
            return [to_field.strip().lower()]
        return []
