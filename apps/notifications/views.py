"""Candidate / recruiter in-app notification feed."""

from __future__ import annotations

from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from .models import Notification
from .serializers import NotificationSerializer


@extend_schema(tags=["notifications"])
class NotificationListView(generics.ListAPIView):
    """GET /api/v1/notifications/ — the current user's notifications."""

    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer
    filterset_fields = ["is_read", "notification_type"]

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user)


@extend_schema(tags=["notifications"])
class UnreadCountView(APIView):
    """GET /api/v1/notifications/unread-count/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        count = Notification.objects.filter(recipient=request.user, is_read=False).count()
        return Response({"unread": count})


@extend_schema(tags=["notifications"])
class MarkReadView(APIView):
    """POST /api/v1/notifications/<pk>/read/"""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        notification = Notification.objects.filter(pk=pk, recipient=request.user).first()
        if not notification:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        notification.mark_read()
        return Response(NotificationSerializer(notification).data)


@extend_schema(tags=["notifications"])
class MarkAllReadView(APIView):
    """POST /api/v1/notifications/read-all/"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        updated = Notification.objects.filter(recipient=request.user, is_read=False).update(
            is_read=True, read_at=timezone.now()
        )
        return Response({"marked_read": updated})


import base64
import hashlib
import json
import logging
import re
import urllib.request
from urllib.parse import urlparse

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from django.core.cache import cache
from rest_framework.permissions import AllowAny

from .models import EmailSuppression

logger = logging.getLogger("apps.notifications")

AWS_SNS_HOST_PATTERN = re.compile(r"^sns\.[a-z0-9-]+\.amazonaws\.com$", re.IGNORECASE)


def is_valid_aws_sns_url(url: str, check_pem_extension: bool = False) -> bool:
    """
    Strict URL validation to prevent SSRF and webhook spoofing.

    Checks:
    - Scheme must be HTTPS
    - Host must match exact AWS SNS pattern: sns.<region>.amazonaws.com
    - No username or password (userinfo) in URL
    - Standard HTTPS port only (None or 443)
    - Path must end in .pem if check_pem_extension is True
    """
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme != "https":
            return False
        if parsed.username or parsed.password:
            return False
        if parsed.port not in (None, 443):
            return False
        hostname = parsed.hostname or ""
        if not AWS_SNS_HOST_PATTERN.match(hostname):
            return False
        if check_pem_extension and not parsed.path.lower().endswith(".pem"):
            return False
        return True
    except Exception:
        return False


def get_sns_x509_certificate(cert_url: str) -> x509.Certificate:
    """Download and cache X.509 certificate for SNS signature verification."""
    url_hash = hashlib.md5(cert_url.encode("utf-8")).hexdigest()
    cache_key = f"sns_cert:{url_hash}"
    cached_pem = cache.get(cache_key)

    if cached_pem:
        try:
            pem_bytes = cached_pem.encode("utf-8") if isinstance(cached_pem, str) else cached_pem
            return x509.load_pem_x509_certificate(pem_bytes)
        except Exception:
            pass

    req = urllib.request.Request(cert_url, headers={"User-Agent": "SevaJobs-SNS-Verifier"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status != 200:
            raise ValueError(f"HTTP {resp.status} fetching certificate")
        pem_data = resp.read(65536)  # 64 KB safety limit

    pem_bytes = pem_data.encode("utf-8") if isinstance(pem_data, str) else pem_data
    cert = x509.load_pem_x509_certificate(pem_bytes)
    cache.set(cache_key, pem_bytes, timeout=86400)  # Cache for 24 hours
    return cert


def build_sns_canonical_string(payload: dict) -> bytes:
    """Construct official AWS SNS canonical string for signature verification."""
    msg_type = payload.get("Type")

    if msg_type == "Notification":
        keys = ["Message", "MessageId", "Subject", "Timestamp", "TopicArn", "Type"]
    elif msg_type in ("SubscriptionConfirmation", "UnsubscribeConfirmation"):
        keys = ["Message", "MessageId", "SubscribeURL", "Timestamp", "Token", "TopicArn", "Type"]
    else:
        raise ValueError(f"Unsupported SNS message type: {msg_type}")

    lines = []
    for key in keys:
        if key in payload and payload[key] is not None:
            lines.append(f"{key}\n{payload[key]}\n")

    return "".join(lines).encode("utf-8")


def verify_sns_signature(payload: dict) -> bool:
    """Cryptographically verify AWS SNS payload RSA signature."""
    try:
        cert_url = payload.get("SigningCertURL", "")
        if not is_valid_aws_sns_url(cert_url, check_pem_extension=True):
            logger.warning("Invalid or suspicious SigningCertURL: %s", cert_url)
            return False

        signature_b64 = payload.get("Signature", "")
        if not signature_b64:
            logger.warning("Missing Signature in SNS payload")
            return False

        signature_bytes = base64.b64decode(signature_b64)
        canonical_bytes = build_sns_canonical_string(payload)
        cert = get_sns_x509_certificate(cert_url)

        sig_version = str(payload.get("SignatureVersion", "1"))
        if sig_version == "1":
            hash_algo = hashes.SHA1()
        elif sig_version == "2":
            hash_algo = hashes.SHA256()
        else:
            logger.warning("Unsupported SignatureVersion: %s", sig_version)
            return False

        cert.public_key().verify(
            signature_bytes,
            canonical_bytes,
            padding.PKCS1v15(),
            hash_algo,
        )
        return True
    except InvalidSignature:
        logger.warning("AWS SNS signature verification failed (InvalidSignature)")
        return False
    except Exception as exc:
        logger.warning("AWS SNS signature verification error: %s", str(exc))
        return False


@extend_schema(tags=["notifications"])
class SESNotificationWebhookView(APIView):
    """
    POST /api/v1/notifications/ses/webhook/
    Webhook endpoint for Amazon SES event publishing via AWS SNS.
    Handles SubscriptionConfirmation, Bounce, and Complaint events after cryptographic verification.
    """

    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        try:
            if isinstance(request.data, dict) and request.data:
                payload = request.data
            else:
                payload = json.loads(request.body.decode("utf-8"))
        except Exception:
            return Response({"detail": "Invalid JSON body"}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Mandatory Cryptographic Signature Verification
        if not verify_sns_signature(payload):
            return Response({"detail": "Invalid or unverified SNS signature"}, status=status.HTTP_400_BAD_REQUEST)

        message_type = payload.get("Type")

        # 2. Handle AWS SNS Subscription Confirmation
        if message_type == "SubscriptionConfirmation":
            subscribe_url = payload.get("SubscribeURL")
            if subscribe_url and is_valid_aws_sns_url(subscribe_url):
                logger.info("Confirming verified AWS SNS subscription at %s", subscribe_url)
                try:
                    req = urllib.request.Request(subscribe_url, headers={"User-Agent": "SevaJobs-SNS-Confirmer"})
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        logger.info("SNS Subscription confirmed with status %s", resp.status)
                except Exception:
                    logger.exception("Failed to confirm SNS subscription URL")
                return Response({"status": "subscription_confirmation_received"})
            else:
                logger.warning("Rejected SubscriptionConfirmation due to invalid SubscribeURL")
                return Response({"detail": "Invalid SubscribeURL"}, status=status.HTTP_400_BAD_REQUEST)

        # 3. Handle AWS SNS Notification (Bounce / Complaint)
        if message_type == "Notification":
            msg_str = payload.get("Message", "")
            try:
                message_data = json.loads(msg_str) if isinstance(msg_str, str) else msg_str
            except Exception:
                return Response({"detail": "Invalid JSON in Message payload"}, status=status.HTTP_400_BAD_REQUEST)

            if not isinstance(message_data, dict):
                return Response({"detail": "Invalid JSON in Message payload"}, status=status.HTTP_400_BAD_REQUEST)

            notification_type = message_data.get("notificationType") or message_data.get("eventType")

            if notification_type == "Bounce":
                bounce = message_data.get("bounce", {})
                bounce_type = bounce.get("bounceType", "")
                bounce_sub_type = bounce.get("bounceSubType", "")
                bounced_recipients = bounce.get("bouncedRecipients", [])

                # Process permanent bounces only
                if bounce_type == "Permanent":
                    for recipient in bounced_recipients:
                        email = recipient.get("emailAddress", "")
                        if email:
                            sanitized_details = {
                                "bounce_type": bounce_type,
                                "bounce_sub_type": bounce_sub_type,
                                "diagnostic_code": str(recipient.get("diagnosticCode", ""))[:255],
                                "status_code": str(recipient.get("status", ""))[:20],
                                "action": str(recipient.get("action", ""))[:20],
                                "ses_message_id": str(message_data.get("mail", {}).get("messageId", "")),
                                "event_timestamp": str(message_data.get("mail", {}).get("timestamp", "")),
                            }
                            EmailSuppression.suppress(
                                email=email,
                                reason=EmailSuppression.Reason.BOUNCE,
                                bounce_type=bounce_type,
                                bounce_sub_type=bounce_sub_type,
                                details=sanitized_details,
                            )
                            logger.warning("Permanent SES Bounce recorded for %s", email)

            elif notification_type == "Complaint":
                complaint = message_data.get("complaint", {})
                complained_recipients = complaint.get("complainedRecipients", [])
                for recipient in complained_recipients:
                    email = recipient.get("emailAddress", "")
                    if email:
                        sanitized_details = {
                            "feedback_type": str(complaint.get("complaintFeedbackType", "")),
                            "user_agent": str(complaint.get("userAgent", ""))[:255],
                            "ses_message_id": str(message_data.get("mail", {}).get("messageId", "")),
                            "event_timestamp": str(message_data.get("mail", {}).get("timestamp", "")),
                        }
                        EmailSuppression.suppress(
                            email=email,
                            reason=EmailSuppression.Reason.COMPLAINT,
                            details=sanitized_details,
                        )
                        logger.warning("SES Spam Complaint recorded for %s", email)

            else:
                return Response({"status": "ignored_notification_type"})

            return Response({"status": "processed"})

        return Response({"status": "ignored"})
