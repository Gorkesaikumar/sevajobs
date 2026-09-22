"""Automated tests and security checks for Resend Email Backend and Webhooks."""

import json
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.core import mail
from django.core.cache import cache
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives, EmailMessage

from apps.notifications.models import EmailSuppression
from apps.notifications.backends import ResendEmailBackend, _mask_email
from apps.notifications.email_service import EmailService
from apps.notifications.tasks import send_transactional_email_task

User = get_user_model()


@override_settings(
    EMAIL_BACKEND="apps.notifications.backends.ResendEmailBackend",
    RESEND_API_KEY="re_test_key_12345",
    RESEND_FROM_EMAIL="noreply@sevajobs.in",
    RESEND_FROM_NAME="SevaJobs",
    RESEND_WEBHOOK_SECRET="whsec_test_secret_12345",
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_STORE_EAGER_RESULT=False,
    CELERY_CACHE_BACKEND="memory",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class ResendBackendTestCase(TestCase):
    def setUp(self):
        cache.clear()
        mail.outbox.clear()
        self.user = User.objects.create_user(
            email="testuser@sevajobs.in",
            password="TestPassword123!",
            first_name="Praveen",
            last_name="Kumar",
        )

    @patch("resend.Emails.send")
    def test_resend_backend_send_single_email(self, mock_resend_send):
        mock_resend_send.return_value = {"id": "resend-msg-12345"}

        backend = ResendEmailBackend()
        msg = EmailMultiAlternatives(
            subject="Test Subject",
            body="Text content",
            from_email="SevaJobs <noreply@sevajobs.in>",
            to=["recipient@example.com"],
            reply_to=["support@sevajobs.in"],
        )
        msg.attach_alternative("<p>HTML content</p>", "text/html")

        sent_count = backend.send_messages([msg])
        self.assertEqual(sent_count, 1)

        mock_resend_send.assert_called_once()
        call_args = mock_resend_send.call_args[0][0]
        self.assertEqual(call_args["to"], ["recipient@example.com"])
        self.assertEqual(call_args["subject"], "Test Subject")
        self.assertEqual(call_args["html"], "<p>HTML content</p>")
        self.assertEqual(call_args["text"], "Text content")
        self.assertEqual(call_args["reply_to"], ["support@sevajobs.in"])

    @patch("resend.Emails.send")
    def test_email_service_dispatches_via_resend(self, mock_resend_send):
        mock_resend_send.return_value = {"id": "resend-msg-welcome-999"}

        with self.captureOnCommitCallbacks(execute=True):
            success = EmailService.send_template_email(
                template_name="welcome",
                to_email="newuser@example.com",
                subject="Welcome to SevaJobs",
                context={"first_name": "NewUser"},
            )
        self.assertTrue(success)
        mock_resend_send.assert_called_once()
        call_args = mock_resend_send.call_args[0][0]
        self.assertEqual(call_args["to"], ["newuser@example.com"])
        self.assertEqual(call_args["subject"], "Welcome to SevaJobs")
        self.assertIn("NewUser", call_args["html"])

    @patch("resend.Emails.send")
    def test_resend_backend_failure_handling(self, mock_resend_send):
        mock_resend_send.side_effect = Exception("API rate limit exceeded")

        backend = ResendEmailBackend(fail_silently=True)
        msg = EmailMessage(
            subject="Fail Test",
            body="Text",
            to=["fail@example.com"],
        )
        sent_count = backend.send_messages([msg])
        self.assertEqual(sent_count, 0)

    def test_email_masking_utility(self):
        self.assertEqual(_mask_email("john.doe@example.com"), "j******e@example.com")
        self.assertEqual(_mask_email("ab@example.com"), "a*@example.com")
        self.assertEqual(_mask_email("invalid"), "***")


@override_settings(
    RESEND_WEBHOOK_SECRET="whsec_test_secret_12345",
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_STORE_EAGER_RESULT=False,
    CELERY_CACHE_BACKEND="memory",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class ResendWebhookTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.webhook_url = reverse("notifications:resend-webhook")

    @patch("apps.notifications.resend_webhook.ResendWebhookView._verify_signature")
    def test_resend_bounce_webhook_creates_suppression(self, mock_verify):
        payload = {
            "type": "email.bounced",
            "created_at": "2026-09-22T12:00:00.000Z",
            "data": {
                "email_id": "email-bounce-111",
                "to": ["bounceduser@sevajobs.in"],
                "bounce_type": "Permanent",
            }
        }
        mock_verify.return_value = payload

        response = self.client.post(
            self.webhook_url,
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_SVIX_ID="msg_svix_111",
            HTTP_SVIX_TIMESTAMP="1600000000",
            HTTP_SVIX_SIGNATURE="v1,dummy_sig",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "processed")
        self.assertTrue(EmailSuppression.is_suppressed("bounceduser@sevajobs.in"))

    @patch("apps.notifications.resend_webhook.ResendWebhookView._verify_signature")
    def test_resend_complaint_webhook_creates_suppression(self, mock_verify):
        payload = {
            "type": "email.complained",
            "created_at": "2026-09-22T12:00:00.000Z",
            "data": {
                "email_id": "email-complaint-222",
                "to": ["complainant@sevajobs.in"],
            }
        }
        mock_verify.return_value = payload

        response = self.client.post(
            self.webhook_url,
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_SVIX_ID="msg_svix_222",
            HTTP_SVIX_TIMESTAMP="1600000000",
            HTTP_SVIX_SIGNATURE="v1,dummy_sig",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "processed")
        self.assertTrue(EmailSuppression.is_suppressed("complainant@sevajobs.in"))

    @patch("apps.notifications.resend_webhook.ResendWebhookView._verify_signature")
    def test_resend_duplicate_webhook_event_is_idempotent(self, mock_verify):
        payload = {
            "type": "email.bounced",
            "created_at": "2026-09-22T12:00:00.000Z",
            "data": {
                "email_id": "email-bounce-333",
                "to": ["dupebounce@sevajobs.in"],
            }
        }
        mock_verify.return_value = payload

        res1 = self.client.post(
            self.webhook_url,
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_SVIX_ID="msg_svix_dupe_1",
        )
        self.assertEqual(res1.status_code, 200)

        res2 = self.client.post(
            self.webhook_url,
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_SVIX_ID="msg_svix_dupe_1",
        )
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.json()["status"], "duplicate_ignored")

    @patch("apps.notifications.resend_webhook.ResendWebhookView._verify_signature", return_value=None)
    def test_invalid_signature_returns_400(self, mock_verify):
        response = self.client.post(
            self.webhook_url,
            data=json.dumps({"type": "email.bounced"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Invalid or missing webhook signature.")
