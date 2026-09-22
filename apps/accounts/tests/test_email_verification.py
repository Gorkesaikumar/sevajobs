"""Automated tests for mandatory Email Verification flow."""

from unittest.mock import patch
from datetime import timedelta
from django.test import TestCase, override_settings, Client
from django.contrib.auth import get_user_model
from django.db import transaction, DatabaseError
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status

from apps.accounts.models import EmailVerificationToken
from apps.accounts.services import AuthService, UserService
from apps.notifications.email_service import EmailService

User = get_user_model()


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_STORE_EAGER_RESULT=False,
    FRONTEND_URL="https://sevajobs.in",
)
class EmailVerificationTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.api_client = APIClient()
        self.auth_service = AuthService()
        self.user_service = UserService()

    def test_new_user_registration_is_unverified_and_schedules_verification_email(self):
        """TEST 1 & 2 & 3 & 7 & 8 & 9 & 10: Registration creates is_email_verified=False user, dispatches email, and redirects to verify-email-required."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            response = self.client.post(
                "/accounts/register/",
                {
                    "role": "job_seeker",
                    "first_name": "Vikram",
                    "last_name": "Singh",
                    "email": "vikram.unverified@example.com",
                    "phone": "9876543290",
                    "password1": "StrongPass123!",
                    "password2": "StrongPass123!",
                },
            )
            self.assertEqual(response.status_code, 302)
            self.assertIn("/accounts/verify-email-required/", response.url)

            user = User.objects.filter(email="vikram.unverified@example.com").first()
            self.assertIsNotNone(user)
            self.assertFalse(user.is_email_verified)

            # Verification email scheduled
            verify_calls = [
                call for call in mock_send.call_args_list
                if call.kwargs.get("template_name") == "verification"
            ]
            self.assertEqual(len(verify_calls), 1)

            kw = verify_calls[0].kwargs
            self.assertEqual(kw["to_email"], "vikram.unverified@example.com")
            self.assertEqual(kw["subject"], "Verify your SevaJobs email address")
            self.assertIn("/accounts/verify-email/", kw["context"]["verification_url"])

    def test_unverified_user_login_blocked_and_redirected(self):
        """TEST 4: Unverified user entering valid credentials is blocked and redirected to verify-email-required."""
        user = User.objects.create_user(
            email="unverified.login@example.com",
            password="TestPassword123!",
            first_name="Unverified",
            is_email_verified=False,
            role=User.Role.JOB_SEEKER,
        )
        response = self.client.post(
            "/jobseeker/login/",
            {
                "email": "unverified.login@example.com",
                "password": "TestPassword123!",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/verify-email-required/", response.url)

    def test_unverified_authenticated_user_accessing_dashboard_blocked_by_middleware(self):
        """TEST 5: Unverified authenticated user attempting protected dashboard route is blocked by RoleAccessMiddleware."""
        user = User.objects.create_user(
            email="unverified.dashboard@example.com",
            password="TestPassword123!",
            first_name="Unverified",
            is_email_verified=False,
            role=User.Role.JOB_SEEKER,
        )
        self.client.force_login(user, backend="django.contrib.auth.backends.ModelBackend")
        response = self.client.get("/accounts/profile/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/verify-email-required/", response.url)

    def test_unverified_user_attempting_protected_api_rejected_with_403(self):
        """TEST 6: Unverified user attempting API login receives HTTP 403 Forbidden with verification required message."""
        user = User.objects.create_user(
            email="unverified.api@example.com",
            password="TestPassword123!",
            first_name="UnverifiedAPI",
            is_email_verified=False,
            role=User.Role.JOB_SEEKER,
        )
        response = self.api_client.post(
            "/api/v1/auth/login/",
            {
                "email": "unverified.api@example.com",
                "password": "TestPassword123!",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["detail"], "Email verification required.")
        self.assertFalse(response.data["is_email_verified"])

    def test_valid_token_verifies_email_consumes_token_and_schedules_welcome_email(self):
        """TEST 11 & 12 & 20 & 21: Valid token sets is_email_verified=True, consumes token, and schedules Welcome Email once."""
        user = User.objects.create_user(
            email="token.verify@example.com",
            password="TestPassword123!",
            first_name="TokenUser",
            is_email_verified=False,
            role=User.Role.JOB_SEEKER,
        )
        token = EmailVerificationToken.issue(user)

        with patch.object(EmailService, "send_template_email") as mock_send:
            verified_user = self.auth_service.verify_email(token.token)
            self.assertTrue(verified_user.is_email_verified)

            # Token consumed
            token.refresh_from_db()
            self.assertIsNotNone(token.used_at)

            # Welcome Email scheduled exactly once
            welcome_calls = [
                call for call in mock_send.call_args_list
                if call.kwargs.get("template_name") == "welcome"
            ]
            self.assertEqual(len(welcome_calls), 1)
            self.assertEqual(welcome_calls[0].kwargs["to_email"], "token.verify@example.com")

    def test_used_token_cannot_be_reused(self):
        """TEST 13: Used token is rejected on subsequent verification attempts."""
        user = User.objects.create_user(
            email="used.token@example.com",
            password="TestPassword123!",
            first_name="UsedToken",
            is_email_verified=False,
            role=User.Role.JOB_SEEKER,
        )
        token = EmailVerificationToken.issue(user)
        self.auth_service.verify_email(token.token)

        # Attempting to use the already consumed token again throws ValidationError
        from rest_framework.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.auth_service.verify_email(token.token)

    def test_expired_token_rejected(self):
        """TEST 14: Expired token (older than TTL) is rejected."""
        user = User.objects.create_user(
            email="expired.token@example.com",
            password="TestPassword123!",
            first_name="ExpiredToken",
            is_email_verified=False,
            role=User.Role.JOB_SEEKER,
        )
        token = EmailVerificationToken.objects.create(
            user=user,
            token="expired_token_12345",
            expires_at=timezone.now() - timedelta(hours=1),
        )
        from rest_framework.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.auth_service.verify_email(token.token)

    def test_invalid_token_rejected(self):
        """TEST 15: Invalid token string is rejected safely."""
        from rest_framework.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.auth_service.verify_email("completely_invalid_token_xyz")

    def test_resend_verification_invalidates_old_token_and_creates_fresh_one(self):
        """TEST 16 & 17: Resend verification invalidates old token, issues fresh token, and stays silent for verified users."""
        user = User.objects.create_user(
            email="resend.user@example.com",
            password="TestPassword123!",
            first_name="ResendUser",
            is_email_verified=False,
            role=User.Role.JOB_SEEKER,
        )
        old_token = EmailVerificationToken.issue(user)

        with patch.object(EmailService, "send_template_email") as mock_send:
            self.auth_service.resend_verification("resend.user@example.com")

            old_token.refresh_from_db()
            self.assertIsNotNone(old_token.used_at)

            # Fresh token issued
            new_token = EmailVerificationToken.objects.filter(user=user, used_at__isnull=True).first()
            self.assertIsNotNone(new_token)
            self.assertNotEqual(old_token.token, new_token.token)

            # Resend for already verified user sends no verification email
            user.is_email_verified = True
            user.save()
            mock_send.reset_mock()
            self.auth_service.resend_verification("resend.user@example.com")
            mock_send.assert_not_called()

    def test_verified_user_login_and_dashboard_access(self):
        """TEST 18 & 19: Verified user login succeeds and grants full dashboard access."""
        user = User.objects.create_user(
            email="verified.seeker@example.com",
            password="TestPassword123!",
            first_name="VerifiedSeeker",
            is_email_verified=True,
            role=User.Role.JOB_SEEKER,
        )
        login_response = self.client.post(
            "/jobseeker/login/",
            {
                "email": "verified.seeker@example.com",
                "password": "TestPassword123!",
            },
        )
        self.assertEqual(login_response.status_code, 302)
        self.assertIn("/dashboard/seeker/", login_response.url)

        dashboard_response = self.client.get("/dashboard/seeker/")
        self.assertEqual(dashboard_response.status_code, 200)

    def test_failed_registration_rollback_sends_no_verification_email(self):
        """TEST 22: Database rollback during user creation dispatches no verification email."""
        with patch("apps.notifications.tasks.send_transactional_email_task.delay") as mock_delay:
            try:
                with transaction.atomic():
                    self.user_service.register(
                        email="failed.rollback@example.com",
                        password="Password123!",
                        first_name="Rollback",
                        last_name="Test",
                        role=User.Role.JOB_SEEKER,
                    )
                    raise DatabaseError("Force rollback")
            except DatabaseError:
                pass

            self.assertEqual(User.objects.filter(email="failed.rollback@example.com").count(), 0)
            mock_delay.assert_not_called()
