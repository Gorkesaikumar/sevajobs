"""Automated tests for Welcome Email registration flow and transaction handling."""

from unittest.mock import patch
from django.test import TestCase, override_settings, Client
from django.contrib.auth import get_user_model
from django.db import transaction, DatabaseError
from django.template.loader import render_to_string
from django.conf import settings

from apps.accounts.models import EmailVerificationToken
from apps.accounts.services import AuthService, UserService
from apps.notifications.email_service import EmailService

User = get_user_model()


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_STORE_EAGER_RESULT=False,
    FRONTEND_URL="https://sevajobs.in",
)
class WelcomeEmailRegistrationTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user_service = UserService()
        self.auth_service = AuthService()

    def test_job_seeker_web_registration_schedules_welcome_email_on_verification(self):
        """Job seeker registration dispatches verification email, and verifying email dispatches Welcome Email."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            response = self.client.post(
                "/accounts/register/",
                {
                    "role": "job_seeker",
                    "first_name": "Arjun",
                    "last_name": "Kumar",
                    "email": "arjun.seeker@example.com",
                    "phone": "9876543210",
                    "password1": "StrongPass123!",
                    "password2": "StrongPass123!",
                },
            )
            self.assertEqual(response.status_code, 302)

            # User created in DB
            user = User.objects.filter(email="arjun.seeker@example.com").first()
            self.assertIsNotNone(user)
            self.assertTrue(user.is_job_seeker)
            self.assertFalse(user.is_email_verified)

            # Verification Email call sent during registration
            verify_calls = [
                call for call in mock_send.call_args_list
                if call.kwargs.get("template_name") == "verification"
            ]
            self.assertEqual(len(verify_calls), 1)

            # Now verify email using token -> triggers Welcome Email
            token = EmailVerificationToken.objects.get(user=user)
            self.auth_service.verify_email(token.token)

            welcome_calls = [
                call for call in mock_send.call_args_list
                if call.kwargs.get("template_name") == "welcome"
            ]
            self.assertEqual(len(welcome_calls), 1)

            kw = welcome_calls[0].kwargs
            self.assertEqual(kw["to_email"], "arjun.seeker@example.com")
            self.assertEqual(kw["subject"], "Welcome to SevaJobs, Arjun!")
            self.assertEqual(kw["template_name"], "welcome")
            self.assertEqual(kw["context"]["first_name"], "Arjun")
            self.assertTrue(kw["context"]["is_job_seeker"])
            self.assertEqual(kw["idempotency_key"], f"welcome:{user.id}")

    def test_recruiter_web_registration_schedules_welcome_email_on_verification(self):
        """Recruiter registration dispatches verification email, and verifying email dispatches Welcome Email."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            response = self.client.post(
                "/accounts/register/",
                {
                    "role": "recruiter",
                    "first_name": "Priya",
                    "last_name": "Sharma",
                    "email": "priya.recruiter@example.com",
                    "phone": "9876543211",
                    "password1": "StrongPass123!",
                    "password2": "StrongPass123!",
                },
            )
            self.assertEqual(response.status_code, 302)

            user = User.objects.filter(email="priya.recruiter@example.com").first()
            self.assertIsNotNone(user)
            self.assertFalse(user.is_job_seeker)

            token = EmailVerificationToken.objects.get(user=user)
            self.auth_service.verify_email(token.token)

            welcome_calls = [
                call for call in mock_send.call_args_list
                if call.kwargs.get("template_name") == "welcome"
            ]
            self.assertEqual(len(welcome_calls), 1)

            kw = welcome_calls[0].kwargs
            self.assertEqual(kw["to_email"], "priya.recruiter@example.com")
            self.assertEqual(kw["subject"], "Welcome to SevaJobs, Priya!")
            self.assertFalse(kw["context"]["is_job_seeker"])

    def test_welcome_html_template_renders_successfully(self):
        """TEST 7: welcome.html renders successfully with header logo."""
        ctx = {
            "frontend_url": "https://sevajobs.in",
            "first_name": "Arjun",
            "is_job_seeker": True,
            "support_email": "support@sevajobs.in",
            "subject": "Welcome to SevaJobs, Arjun!",
        }
        html_content = render_to_string("emails/welcome.html", ctx)
        self.assertIn("Welcome to SevaJobs, Arjun!", html_content)
        self.assertIn('src="https://sevajobs.in/static/images/logo.jpg"', html_content)
        self.assertIn("Explore verified job openings", html_content)

    def test_welcome_txt_template_renders_successfully(self):
        """TEST 8: welcome.txt renders successfully."""
        ctx = {
            "frontend_url": "https://sevajobs.in",
            "first_name": "Arjun",
            "is_job_seeker": True,
            "support_email": "support@sevajobs.in",
            "subject": "Welcome to SevaJobs, Arjun!",
        }
        text_content = render_to_string("emails/welcome.txt", ctx)
        self.assertIn("Welcome to SevaJobs, Arjun!", text_content)
        self.assertIn("https://sevajobs.in/login", text_content)

    def test_failed_registration_no_welcome_email(self):
        """TEST 9: Failed registration (validation error) does not send Welcome Email."""
        with patch.object(EmailService, "send_template_email") as mock_send:
            # Missing required fields
            response = self.client.post(
                "/accounts/register/",
                {
                    "role": "job_seeker",
                    "first_name": "",
                    "email": "invalid-email",
                    "password1": "short",
                    "password2": "mismatch",
                },
            )
            self.assertEqual(response.status_code, 200)  # Form re-rendered with errors
            mock_send.assert_not_called()
            self.assertEqual(User.objects.filter(email="invalid-email").count(), 0)

    def test_transaction_rollback_prevents_welcome_email(self):
        """TEST 10: If registration transaction rolls back, no Welcome Email is scheduled."""
        with patch("apps.notifications.tasks.send_transactional_email_task.delay") as mock_delay:
            try:
                with transaction.atomic():
                    self.user_service.register(
                        email="rollback.user@example.com",
                        password="Password123!",
                        first_name="Rollback",
                        last_name="Test",
                        role=User.Role.JOB_SEEKER,
                    )
                    # Force a rollback inside the atomic block
                    raise DatabaseError("Forced transaction rollback test")
            except DatabaseError:
                pass

            # Transaction rolled back -> user not in DB -> Celery task delay NOT called
            self.assertEqual(User.objects.filter(email="rollback.user@example.com").count(), 0)
            mock_delay.assert_not_called()

    def test_transaction_commit_triggers_celery_task(self):
        """TEST 11: When transaction commits, Celery email task scheduling occurs."""
        with patch("apps.notifications.tasks.send_transactional_email_task.delay") as mock_delay:
            with self.captureOnCommitCallbacks(execute=True):
                self.user_service.register(
                    email="commit.user@example.com",
                    password="Password123!",
                    first_name="Commit",
                    last_name="Test",
                    role=User.Role.JOB_SEEKER,
                )

            self.assertEqual(mock_delay.call_count, 1)
            kw = mock_delay.call_args.kwargs
            self.assertEqual(kw["to_email"], "commit.user@example.com")
            self.assertEqual(kw["subject"], "Verify your SevaJobs email address")
