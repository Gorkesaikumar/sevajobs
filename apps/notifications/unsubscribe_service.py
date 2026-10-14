"""
Cryptographically secure unsubscribe token service for SevaJobs bulk emails.
Uses Django's TimestampSigner to generate tamper-proof, time-limited opt-out links.
"""

from __future__ import annotations

import logging
from django.conf import settings
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from django.urls import reverse

from .models import EmailSuppression

logger = logging.getLogger("apps.notifications")

_signer = TimestampSigner(salt="sevajobs-email-unsubscribe-v1")


class UnsubscribeService:
    """Service to create, verify, and execute email unsubscriptions."""

    DEFAULT_MAX_AGE_DAYS = 90

    @classmethod
    def generate_token(cls, email: str) -> str:
        """Generate a cryptographically signed token for the recipient email."""
        normalized = email.strip().lower()
        return _signer.sign(normalized)

    @classmethod
    def verify_token(cls, token: str, max_age_days: int | None = None) -> str | None:
        """
        Verify a signed token and return the normalized email address.
        Returns None if invalid or expired.
        """
        if not token or not isinstance(token, str):
            return None
        max_age = (max_age_days or cls.DEFAULT_MAX_AGE_DAYS) * 86400
        try:
            email = _signer.unsign(token, max_age=max_age)
            return email.strip().lower()
        except SignatureExpired:
            logger.info("Unsubscribe token expired.")
            return None
        except BadSignature:
            logger.warning("Invalid unsubscribe token signature.")
            return None

    @classmethod
    def build_unsubscribe_url(cls, email: str, base_url: str | None = None) -> str:
        """Construct full absolute URL for one-click unsubscribe."""
        token = cls.generate_token(email)
        path = reverse("notifications:email-unsubscribe")
        root = base_url or getattr(settings, "FRONTEND_URL", "https://sevajobs.in")
        return f"{root.rstrip('/')}{path}?token={token}"

    @classmethod
    def unsubscribe_email(cls, email: str, details: dict | None = None) -> bool:
        """
        Record the email address in EmailSuppression with Reason.UNSUBSCRIBE.
        Guarantees that subsequent campaigns automatically suppress this recipient.
        """
        if not email or "@" not in email:
            return False
        normalized = email.strip().lower()
        EmailSuppression.unsubscribe(normalized, details=details or {})
        logger.info("Email %s has been unsubscribed and added to EmailSuppression.", normalized)
        return True


_job_alert_signer = TimestampSigner(salt="sevajobs-job-alert-preference-v1")


class JobAlertPreferenceService:
    """Service to generate and verify secure signed tokens for candidate Job Alert preferences and opt-out."""

    DEFAULT_MAX_AGE_DAYS = 180

    @classmethod
    def generate_token(cls, email: str) -> str:
        normalized = email.strip().lower()
        return _job_alert_signer.sign(normalized)

    @classmethod
    def verify_token(cls, token: str, max_age_days: int | None = None) -> str | None:
        if not token or not isinstance(token, str):
            return None
        max_age = (max_age_days or cls.DEFAULT_MAX_AGE_DAYS) * 86400
        try:
            email = _job_alert_signer.unsign(token, max_age=max_age)
            return email.strip().lower()
        except SignatureExpired:
            logger.info("Job alert preference token expired.")
            return None
        except BadSignature:
            logger.warning("Invalid job alert preference token signature.")
            return None

    @classmethod
    def build_preference_url(cls, email: str, base_url: str | None = None) -> str:
        token = cls.generate_token(email)
        path = reverse("notifications:job-alert-preferences")
        root = base_url or getattr(settings, "FRONTEND_URL", "https://sevajobs.in")
        return f"{root.rstrip('/')}{path}?token={token}"

    @classmethod
    def update_preference(cls, email: str, enabled: bool) -> bool:
        """Update candidate JobSeekerProfile.job_alerts_enabled without affecting core account."""
        from apps.accounts.models import User
        normalized = email.strip().lower()
        user = User.objects.filter(email__iexact=normalized).first()
        if user and hasattr(user, "job_seeker_profile"):
            user.job_seeker_profile.job_alerts_enabled = enabled
            user.job_seeker_profile.save(update_fields=["job_alerts_enabled", "updated_at"])
            logger.info("Updated job_alerts_enabled=%s for %s", enabled, normalized)
            return True
        return False

