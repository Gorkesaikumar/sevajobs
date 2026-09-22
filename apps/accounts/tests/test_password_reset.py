"""Automated test suite for Forgot Password and Password Reset workflow."""

from __future__ import annotations

import datetime
from django.test import TestCase, override_settings
from django.urls import reverse
from django.core import mail
from django.core.cache import cache
from django.utils import timezone
from django.contrib.auth import get_user_model

from apps.accounts.models import PasswordResetToken
from apps.accounts.services import AuthService

User = get_user_model()


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_STORE_EAGER_RESULT=False,
    CELERY_CACHE_BACKEND="memory",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    FRONTEND_URL="https://sevajobs.in",
)
class PasswordResetWorkflowTests(TestCase):
    def setUp(self):
        cache.clear()
        mail.outbox.clear()
        self.email = "registered_user@example.com"
        self.password = "InitialPassword123!"
        self.user = User.objects.create_user(
            email=self.email,
            password=self.password,
            first_name="Jane",
            last_name="Doe",
            role=User.Role.JOB_SEEKER,
            is_active=True,
        )

    # Test A: Existing registered user
    def test_forgot_password_registered_user_creates_token_and_schedules_email(self):
        url = reverse("accounts:forgot-password")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, {"email": self.email})

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "If an account exists with this email, you&#x27;ll receive a password reset link shortly.",
            html=False,
        )

        # Check token created in DB
        tokens = PasswordResetToken.objects.filter(user=self.user)
        self.assertEqual(tokens.count(), 1)
        token = tokens.first()
        self.assertTrue(token.is_valid())

        # Check transactional email scheduled & sent to outbox
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertEqual(sent_email.to, [self.email])
        self.assertEqual(sent_email.subject, "Reset your SevaJobs password")

        # Check production-safe reset URL format
        expected_url = f"https://sevajobs.in/accounts/reset-password/{token.token}/"
        self.assertIn(expected_url, sent_email.body)
        self.assertTrue(any(expected_url in alt[0] for alt in sent_email.alternatives))

    # Test B: Case normalization
    def test_email_case_normalization_resolves_registered_user(self):
        url = reverse("accounts:forgot-password")
        mixed_case_email = "REGISTERED_USER@Example.COM"
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, {"email": mixed_case_email})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(PasswordResetToken.objects.filter(user=self.user).count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.email])

    # Test C: Unknown email
    def test_forgot_password_unknown_email_shows_generic_success_without_token_or_email(self):

        url = reverse("accounts:forgot-password")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, {"email": "unknown_user@example.com"})

        self.assertEqual(response.status_code, 200)
        # Prevents email enumeration
        self.assertContains(
            response,
            "If an account exists with this email, you&#x27;ll receive a password reset link shortly.",
            html=False,
        )

        # No token & no email
        self.assertEqual(PasswordResetToken.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    # Test C: Previous token invalidated when new request arrives
    def test_forgot_password_invalidates_previous_unused_token(self):
        auth_service = AuthService()

        # First request
        with self.captureOnCommitCallbacks(execute=True):
            auth_service.request_password_reset(self.email)
        token1 = PasswordResetToken.objects.filter(user=self.user).latest("created_at")
        self.assertTrue(token1.is_valid())

        # Second request
        with self.captureOnCommitCallbacks(execute=True):
            auth_service.request_password_reset(self.email)
        token2 = PasswordResetToken.objects.filter(user=self.user).latest("created_at")

        token1.refresh_from_db()
        # Previous token must be marked used/invalid
        self.assertFalse(token1.is_valid())
        self.assertIsNotNone(token1.used_at)

        # New token is active
        self.assertTrue(token2.is_valid())
        self.assertNotEqual(token1.token, token2.token)

    # Test D: Valid reset token allows changing password and authenticating
    def test_valid_reset_token_changes_password(self):
        token = PasswordResetToken.issue(self.user)
        reset_url = reverse("accounts:reset-password", kwargs={"token": token.token})

        # GET reset page
        get_res = self.client.get(reset_url)
        self.assertEqual(get_res.status_code, 200)
        self.assertFalse(get_res.context.get("token_invalid"))

        # POST new valid password
        new_pass = "NewSecurePassword456!"
        post_res = self.client.post(
            reset_url,
            {"password": new_pass, "password2": new_pass},
        )
        self.assertRedirects(post_res, reverse("accounts:login"), target_status_code=302)

        # Verify token consumed
        token.refresh_from_db()
        self.assertTrue(token.is_used)
        self.assertFalse(token.is_valid())

        # Verify user can authenticate with new password
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new_pass))
        self.assertFalse(self.user.check_password(self.password))

    # Test E: Invalid token rejected
    def test_invalid_reset_token_rejected(self):
        invalid_url = reverse("accounts:reset-password", kwargs={"token": "invalid_token_123"})
        response = self.client.post(
            invalid_url,
            {"password": "NewSecurePassword456!", "password2": "NewSecurePassword456!"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context.get("token_invalid"))

        # Password unchanged
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.password))

    # Test F: Expired token rejected
    def test_expired_reset_token_rejected(self):
        token = PasswordResetToken.issue(self.user)
        token.expires_at = timezone.now() - datetime.timedelta(minutes=1)
        token.save()

        reset_url = reverse("accounts:reset-password", kwargs={"token": token.token})
        response = self.client.post(
            reset_url,
            {"password": "NewSecurePassword456!", "password2": "NewSecurePassword456!"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context.get("token_invalid"))

        # Password unchanged
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.password))

    # Test G: Used token cannot be reused
    def test_used_reset_token_cannot_be_reused(self):
        token = PasswordResetToken.issue(self.user)
        token.consume()

        reset_url = reverse("accounts:reset-password", kwargs={"token": token.token})
        response = self.client.post(
            reset_url,
            {"password": "NewSecurePassword456!", "password2": "NewSecurePassword456!"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context.get("token_invalid"))

        # Password unchanged
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.password))

    # Test H: Password mismatch rejected
    def test_password_mismatch_rejected(self):
        token = PasswordResetToken.issue(self.user)
        reset_url = reverse("accounts:reset-password", kwargs={"token": token.token})

        response = self.client.post(
            reset_url,
            {"password": "NewSecurePassword456!", "password2": "DifferentPassword789!"},
        )
        self.assertEqual(response.status_code, 200)

        # Token still valid (not consumed)
        token.refresh_from_db()
        self.assertTrue(token.is_valid())

        # Password unchanged
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.password))

    # Test I: Weak password rejected by Django validators
    def test_weak_password_rejected(self):
        token = PasswordResetToken.issue(self.user)
        reset_url = reverse("accounts:reset-password", kwargs={"token": token.token})

        response = self.client.post(
            reset_url,
            {"password": "123", "password2": "123"},
        )
        self.assertEqual(response.status_code, 200)

        # Token still valid
        token.refresh_from_db()
        self.assertTrue(token.is_valid())

        # Password unchanged
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.password))

    # Test J: Query parameter token URL support
    def test_reset_password_via_query_parameter_url(self):
        token = PasswordResetToken.issue(self.user)
        query_url = f"{reverse('accounts:reset-password-query')}?token={token.token}"

        response = self.client.get(query_url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context.get("token_invalid"))
        self.assertEqual(response.context.get("token"), token.token)
