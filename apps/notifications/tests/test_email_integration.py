"""Automated tests for Amazon SES transactional email integration."""

import json
from unittest.mock import patch, MagicMock
from smtplib import SMTPServerDisconnected, SMTPDataError

from django.test import TestCase, override_settings
from django.core import mail
from django.core.cache import cache
from django.urls import reverse
from django.contrib.auth import get_user_model

from apps.notifications.models import EmailSuppression
from apps.notifications.email_service import EmailService
from apps.notifications.tasks import send_transactional_email_task
from apps.accounts.services import AuthService, UserService

User = get_user_model()


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_STORE_EAGER_RESULT=False,
    CELERY_CACHE_BACKEND="memory",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class EmailIntegrationTestCase(TestCase):
    def setUp(self):
        cache.clear()
        mail.outbox.clear()
        self.user = User.objects.create_user(
            email="testuser@example.com",
            password="TestPassword123!",
            first_name="Praveen",
            last_name="Kumar",
        )

    def test_email_service_renders_html_and_text_and_sends(self):
        """Test that EmailService renders templates and dispatches email correctly."""
        with self.captureOnCommitCallbacks(execute=True):
            success = EmailService.send_template_email(
                template_name="verification",
                to_email="testuser@example.com",
                subject="Verify your SevaJobs email address",
                context={
                    "first_name": "Praveen",
                    "verification_url": "http://localhost:3000/verify-email?token=xyz123",
                    "ttl_hours": 48,
                },
                idempotency_key="test_verify_key_1",
            )
        self.assertTrue(success)
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertEqual(sent_email.subject, "Verify your SevaJobs email address")
        self.assertEqual(sent_email.to, ["testuser@example.com"])
        self.assertIn("Praveen", sent_email.body)
        self.assertTrue(any(alt[1] == "text/html" for alt in sent_email.alternatives))

    def test_email_idempotency_prevents_duplicate_delivery(self):
        """Test that duplicate calls with the same idempotency key are skipped."""
        task_res1 = send_transactional_email_task(
            subject="Test Subject",
            to_email="testuser@example.com",
            html_message="<p>Hello</p>",
            plain_message="Hello",
            idempotency_key="unique_key_123",
        )
        self.assertEqual(task_res1["status"], "sent")
        self.assertEqual(len(mail.outbox), 1)

        # Second attempt with same key should be skipped
        task_res2 = send_transactional_email_task(
            subject="Test Subject",
            to_email="testuser@example.com",
            html_message="<p>Hello</p>",
            plain_message="Hello",
            idempotency_key="unique_key_123",
        )
        self.assertEqual(task_res2["status"], "skipped_duplicate")
        self.assertEqual(len(mail.outbox), 1)

    def test_email_suppression_blocks_bounced_recipient(self):
        """Test that suppressed email addresses are not sent emails."""
        EmailSuppression.suppress("bounced@example.com", reason="bounce", bounce_type="Permanent")
        
        with self.captureOnCommitCallbacks(execute=True):
            success = EmailService.send_template_email(
                template_name="welcome",
                to_email="bounced@example.com",
                subject="Welcome!",
                context={"first_name": "Bounced"},
            )
        self.assertFalse(success)
        self.assertEqual(len(mail.outbox), 0)

    @patch("django.core.mail.EmailMultiAlternatives.send")
    def test_celery_task_permanent_bounce_creates_suppression(self, mock_send):
        """Test permanent 5xx SMTP error automatically creates an EmailSuppression record."""
        err = SMTPDataError(550, b"Requested action not taken: mailbox unavailable")
        mock_send.side_effect = err

        result = send_transactional_email_task(
            subject="Test Permanent Failure",
            to_email="invalid@example.com",
            html_message="<p>Hi</p>",
            plain_message="Hi",
        )
        self.assertEqual(result["status"], "failed_permanent")
        self.assertTrue(EmailSuppression.is_suppressed("invalid@example.com"))

    @patch("apps.notifications.views.verify_sns_signature", return_value=True)
    def test_sns_webhook_subscription_confirmation(self, mock_verify):
        """Test AWS SNS SubscriptionConfirmation webhook handling."""
        url = reverse("notifications:ses-webhook")
        payload = {
            "Type": "SubscriptionConfirmation",
            "SigningCertURL": "https://sns.ap-south-2.amazonaws.com/SimpleNotificationService-123.pem",
            "SignatureVersion": "2",
            "Signature": "dummy",
            "SubscribeURL": "https://sns.ap-south-2.amazonaws.com/?Action=ConfirmSubscription&TopicArn=arn:aws:sns:ap-south-2:123:sevajobs-bounces",
        }
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            response = self.client.post(url, data=payload, content_type="application/json")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "subscription_confirmation_received")

    @patch("apps.notifications.views.verify_sns_signature", return_value=True)
    def test_sns_webhook_bounce_processing(self, mock_verify):
        """Test AWS SNS Bounce event processing."""
        url = reverse("notifications:ses-webhook")
        message_body = {
            "notificationType": "Bounce",
            "bounce": {
                "bounceType": "Permanent",
                "bounceSubType": "General",
                "bouncedRecipients": [{"emailAddress": "hardbounce@sevajobs.in"}],
            },
        }
        payload = {
            "Type": "Notification",
            "SigningCertURL": "https://sns.ap-south-2.amazonaws.com/SimpleNotificationService-123.pem",
            "SignatureVersion": "2",
            "Signature": "dummy",
            "Message": json.dumps(message_body),
        }
        response = self.client.post(url, data=payload, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "processed")
        self.assertTrue(EmailSuppression.is_suppressed("hardbounce@sevajobs.in"))

    def test_auth_service_triggers_html_email(self):
        """Test AuthService verification and password reset workflows trigger EmailService."""
        auth_service = AuthService()
        with self.captureOnCommitCallbacks(execute=True):
            auth_service.send_verification_email(self.user)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Verify your SevaJobs email address", mail.outbox[0].subject)

        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            auth_service.request_password_reset(self.user.email)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Reset your SevaJobs password", mail.outbox[0].subject)
