"""Business logic for authentication and account management."""

from __future__ import annotations

import logging
from typing import Optional

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, ValidationError

from .models import EmailVerificationToken, PasswordResetToken
from .repository import UserRepository

logger = logging.getLogger("apps.accounts")
security_logger = logging.getLogger("django.security")
User = get_user_model()

FRONTEND_URL = getattr(settings, "FRONTEND_URL", "http://localhost:3000")


class UserService:
    """Registration, profile, and password management."""

    def register(
        self,
        *,
        email: str,
        password: str,
        first_name: str,
        last_name: str,
        role: str = User.Role.JOB_SEEKER,
        phone: Optional[str] = None,
    ) -> User:
        if role in (User.Role.ADMIN, User.Role.SUPER_ADMIN, User.Role.STAFF):
            raise ValidationError({"role": "Admin, Super Admin, and Staff accounts cannot be self-registered."})
        if UserRepository.email_exists(email):
            raise ValidationError({"email": "A user with this email already exists."})
        if phone and UserRepository.phone_exists(phone):
            raise ValidationError({"phone": "A user with this phone number already exists."})

        user = UserRepository.create(
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            role=role,
            phone=phone,
        )
        logger.info("New user registered: %s (role=%s)", user.email, role)
        return user

    def update_profile(self, user: User, **fields) -> User:
        allowed = {"first_name", "last_name", "phone", "avatar"}
        filtered = {k: v for k, v in fields.items() if k in allowed}
        return UserRepository.update(user, **filtered)

    def change_password(self, user: User, old_password: str, new_password: str) -> None:
        if not user.check_password(old_password):
            raise AuthenticationFailed("Current password is incorrect.")
        user.set_password(new_password)
        user.save(update_fields=["password"])
        security_logger.info("Password changed for user %s", user.pk)

    def deactivate(self, user: User) -> None:
        UserRepository.update(user, is_active=False)
        security_logger.warning("User deactivated: %s", user.pk)

    def record_login_ip(self, user: User, ip: Optional[str]) -> None:
        if ip:
            UserRepository.update(user, last_login_ip=ip)


class AuthService:
    """Email verification and password-reset workflows."""

    # ----- Email verification ---------------------------------------------
    @transaction.atomic
    def send_verification_email(self, user: User) -> EmailVerificationToken:
        # Invalidate any outstanding tokens, then issue a fresh one.
        EmailVerificationToken.objects.filter(user=user, used_at__isnull=True).update(
            used_at=timezone.now()
        )
        token = EmailVerificationToken.issue(user)
        link = f"{FRONTEND_URL}/verify-email?token={token.token}"
        self._send(
            subject="Verify your SevaJobs email address",
            message=(
                f"Hi {user.first_name},\n\n"
                f"Please confirm your email by visiting:\n{link}\n\n"
                f"This link expires in {EmailVerificationToken.DEFAULT_TTL_HOURS} hours."
            ),
            recipient=user.email,
        )
        logger.info("Verification email dispatched to %s", user.email)
        return token

    def resend_verification(self, email: str) -> None:
        user = UserRepository.get_by_email(email)
        # Stay silent for unknown / already-verified accounts (no enumeration).
        if user and not user.is_email_verified:
            self.send_verification_email(user)

    @transaction.atomic
    def verify_email(self, token_str: str) -> User:
        token = EmailVerificationToken.objects.select_related("user").filter(token=token_str).first()
        if token is None or not token.is_valid():
            raise ValidationError({"token": "Invalid or expired verification token."})
        user = token.user
        if not user.is_email_verified:
            user.is_email_verified = True
            user.save(update_fields=["is_email_verified"])
        token.consume()
        logger.info("Email verified for %s", user.email)
        return user

    # ----- Password reset --------------------------------------------------
    @transaction.atomic
    def request_password_reset(self, email: str, ip: Optional[str] = None) -> None:
        user = UserRepository.get_by_email(email)
        if user is None:
            # Do not reveal whether the email exists.
            security_logger.info("Password reset requested for unknown email.")
            return
        PasswordResetToken.objects.filter(user=user, used_at__isnull=True).update(
            used_at=timezone.now()
        )
        token = PasswordResetToken.issue(user, requested_ip=ip)
        link = f"{FRONTEND_URL}/reset-password?token={token.token}"
        self._send(
            subject="Reset your SevaJobs password",
            message=(
                f"Hi {user.first_name},\n\n"
                f"Use the link below to reset your password:\n{link}\n\n"
                f"This link expires in {PasswordResetToken.DEFAULT_TTL_HOURS} hours. "
                f"If you did not request this, you can safely ignore this email."
            ),
            recipient=user.email,
        )
        security_logger.info("Password reset token issued for user %s", user.pk)

    @transaction.atomic
    def reset_password(self, token_str: str, new_password: str) -> User:
        token = PasswordResetToken.objects.select_related("user").filter(token=token_str).first()
        if token is None or not token.is_valid():
            raise ValidationError({"token": "Invalid or expired reset token."})
        user = token.user
        user.set_password(new_password)
        user.save(update_fields=["password"])
        token.consume()
        # Burn any other outstanding reset tokens for this user.
        PasswordResetToken.objects.filter(user=user, used_at__isnull=True).update(
            used_at=timezone.now()
        )
        security_logger.info("Password reset completed for user %s", user.pk)
        return user

    # ----- helpers ---------------------------------------------------------
    @staticmethod
    def _send(*, subject: str, message: str, recipient: str) -> None:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            fail_silently=False,
        )
