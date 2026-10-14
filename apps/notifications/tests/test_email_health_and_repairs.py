"""
Comprehensive test suite verifying Resend integration repairs, email health diagnostics,
webhook Svix signature verification, walk-in alerts, requirement matching, and quota integrity.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone as dt_timezone
import json
import time
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from svix.webhooks import Webhook

from apps.jobs.models import InstitutionRequirement
from apps.notifications.backends import ResendEmailBackend
from apps.notifications.health_service import EmailHealthService, mask_secret
from apps.notifications.models import (
    CampaignRecipient,
    DailyEmailQuotaTracking,
    EmailCampaign,
    EmailSuppression,
    JobAlertCampaign,
    JobAlertRecipient,
)
from apps.notifications.quota_service import DailyEmailQuotaService
from apps.notifications.tasks import (
    send_bulk_campaign_task,
    send_bulk_job_alerts_task,
)

User = get_user_model()

# Valid 32-byte base64 Svix secret (whsec_ + base64)
TEST_SVIX_SECRET = "whsec_" + base64.b64encode(b"01234567890123456789012345678901").decode()


@override_settings(
    EMAIL_BACKEND="apps.notifications.backends.ResendEmailBackend",
    RESEND_API_KEY="re_test_dummy_key_12345",
    RESEND_FROM_EMAIL="support@sevajobs.in",
    RESEND_FROM_NAME="SevaJobs Support",
    RESEND_WEBHOOK_SECRET=TEST_SVIX_SECRET,
    CELERY_TASK_ALWAYS_EAGER=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class ResendBackendRepairsTestCase(TestCase):
    def setUp(self):
        cache.clear()
        mail.outbox.clear()

    @patch("resend.Emails.send")
    def test_backend_preserves_extra_headers_and_tags(self, mock_send):
        mock_send.return_value = {"id": "resend_msg_test_abc123"}

        backend = ResendEmailBackend()
        msg = EmailMultiAlternatives(
            subject="Special Notification",
            body="Plain body",
            from_email="support@sevajobs.in",
            to=["user@example.com"],
            headers={
                "List-Unsubscribe": "<https://sevajobs.in/unsubscribe>",
                "X-Campaign-ID": "campaign_99",
                "campaign_id": "99",
                "alert_type": "teaching_requirement",
            },
        )
        msg.attach_alternative("<p>HTML body</p>", "text/html")
        msg.attach("sample.txt", b"Hello attachment", "text/plain")

        sent = backend.send_messages([msg])
        self.assertEqual(sent, 1)

        mock_send.assert_called_once()
        payload = mock_send.call_args[0][0]

        # Verify headers preserved
        self.assertIn("headers", payload)
        self.assertEqual(payload["headers"].get("List-Unsubscribe"), "<https://sevajobs.in/unsubscribe>")
        self.assertEqual(payload["headers"].get("X-Campaign-ID"), "campaign_99")

        # Verify tags structured
        self.assertIn("tags", payload)
        tag_names = [t["name"] for t in payload["tags"]]
        self.assertIn("campaign_id", tag_names)
        self.assertIn("alert_type", tag_names)

        # Verify attachment passed
        self.assertIn("attachments", payload)
        self.assertEqual(len(payload["attachments"]), 1)
        self.assertEqual(payload["attachments"][0]["filename"], "sample.txt")

        # Verify provider_message_id populated on message
        self.assertEqual(getattr(msg, "provider_message_id", None), "resend_msg_test_abc123")
        self.assertEqual(msg.extra_headers.get("provider_message_id"), "resend_msg_test_abc123")


@override_settings(
    RESEND_WEBHOOK_SECRET=TEST_SVIX_SECRET,
    CELERY_TASK_ALWAYS_EAGER=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class ResendWebhookSvixVerificationTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.webhook_url = reverse("notifications:resend-webhook")
        self.admin = User.objects.create_superuser(
            email="admin_webhook@sevajobs.in",
            password="AdminPass123!",
            first_name="Admin",
            last_name="Webhook",
        )

    def _sign_payload(self, payload_dict: dict) -> tuple[str, str, str, str]:
        """Signs payload using real svix Webhook signer with timezone-aware datetime."""
        raw_body = json.dumps(payload_dict)
        wh = Webhook(TEST_SVIX_SECRET)
        msg_id = f"msg_{int(time.time()*1000)}"
        now_dt = datetime.now(dt_timezone.utc)
        sig = wh.sign(msg_id, now_dt, raw_body)
        timestamp = str(int(now_dt.timestamp()))
        return raw_body, msg_id, timestamp, sig

    def test_authentic_svix_signature_delivered_event(self):
        # Setup campaign recipient with provider_message_id
        req = InstitutionRequirement.objects.create(
            institution_name="Delhi Public School",
            phone_number="9876543210",
            subject="Mathematics",
            qualification="B.Ed",
            location="Delhi",
            status="assigned",
        )
        campaign = EmailCampaign.objects.create(
            name="Math Teachers",
            requirement=req,
            subject="Urgent Requirement",
            body_html="<p>Test</p>",
            body_plain="Test",
            created_by=self.admin,
            status=EmailCampaign.Status.PROCESSING,
        )
        recip = CampaignRecipient.objects.create(
            campaign=campaign,
            email="teacher@example.com",
            recipient_name="Teacher",
            status=CampaignRecipient.RecipientStatus.SENT,
            provider_message_id="resend_deliv_msg_777",
        )

        payload = {
            "type": "email.delivered",
            "created_at": timezone.now().isoformat(),
            "data": {
                "email_id": "resend_deliv_msg_777",
                "to": ["teacher@example.com"],
            },
        }

        raw_body, msg_id, timestamp, sig = self._sign_payload(payload)

        resp = self.client.post(
            self.webhook_url,
            data=raw_body,
            content_type="application/json",
            HTTP_SVIX_ID=msg_id,
            HTTP_SVIX_TIMESTAMP=timestamp,
            HTTP_SVIX_SIGNATURE=sig,
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("status"), "acknowledged")

        # Verify recipient record updated to DELIVERED
        recip.refresh_from_db()
        self.assertEqual(recip.status, CampaignRecipient.RecipientStatus.DELIVERED)
        self.assertIsNotNone(recip.delivered_at)

    def test_invalid_svix_signature_rejected_with_400(self):
        payload = {"type": "email.delivered", "data": {"email_id": "fake_id"}}
        raw_body = json.dumps(payload)

        resp = self.client.post(
            self.webhook_url,
            data=raw_body,
            content_type="application/json",
            HTTP_SVIX_ID="msg_invalid_123",
            HTTP_SVIX_TIMESTAMP=str(int(time.time())),
            HTTP_SVIX_SIGNATURE="v1,completely_invalid_signature_hex",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Invalid or missing webhook signature", resp.json().get("detail", ""))


@override_settings(
    EMAIL_BACKEND="apps.notifications.backends.ResendEmailBackend",
    RESEND_API_KEY="re_test_dummy_key_12345",
    RESEND_FROM_EMAIL="support@sevajobs.in",
    RESEND_FROM_NAME="SevaJobs Support",
    CELERY_TASK_ALWAYS_EAGER=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class BulkAlertTasksAndQuotaRepairsTestCase(TestCase):
    def setUp(self):
        cache.clear()
        mail.outbox.clear()
        self.admin = User.objects.create_superuser(
            email="admin_bulk@sevajobs.in",
            password="AdminPass123!",
            first_name="Admin",
            last_name="Bulk",
        )

    @patch("resend.Emails.send")
    def test_send_bulk_job_alerts_walkin_without_linked_job(self, mock_send):
        """Walk-in alerts with null walkin_job should dispatch successfully without skipping."""
        mock_send.return_value = {"id": "resend_walkin_msg_888"}

        campaign = JobAlertCampaign.objects.create(
            alert_type=JobAlertCampaign.AlertType.WALKIN_ALERT,
            name="Mega Walk-In Interview Drive",
            subject="Walk-in Alert",
            body_html="<p>Walk in tomorrow at Community Hall.</p>",
            body_plain="Walk in tomorrow at Community Hall.",
            walkin_job=None,  # Standalone walk-in event
            created_by=self.admin,
            status=JobAlertCampaign.Status.QUEUED,
        )

        recipient = JobAlertRecipient.objects.create(
            campaign=campaign,
            email="walkin_candidate@example.com",
            recipient_name="Candidate One",
            status=JobAlertRecipient.RecipientStatus.QUEUED,
        )

        # Execute task
        result = send_bulk_job_alerts_task(str(campaign.id))
        self.assertGreater(result.get("sent", 0), 0)

        recipient.refresh_from_db()
        self.assertEqual(recipient.status, JobAlertRecipient.RecipientStatus.SENT)
        self.assertEqual(recipient.provider_message_id, "resend_walkin_msg_888")

    @patch("resend.Emails.send")
    def test_send_bulk_campaign_with_lowercase_assigned_requirement(self, mock_send):
        """Requirements with status='assigned' should not be rejected by uppercase checks."""
        mock_send.return_value = {"id": "resend_req_msg_555"}

        req = InstitutionRequirement.objects.create(
            institution_name="St. Xavier's School",
            phone_number="9876543211",
            subject="Physics",
            qualification="M.Sc B.Ed",
            location="Mumbai",
            status="assigned",  # lowercase in database
        )

        campaign = EmailCampaign.objects.create(
            name="Physics Teacher Requirement",
            requirement=req,
            subject="Job Opportunity: Physics Teacher",
            body_html="<p>We need a Physics Teacher</p>",
            body_plain="We need a Physics Teacher",
            created_by=self.admin,
            status=EmailCampaign.Status.QUEUED,
        )

        recip = CampaignRecipient.objects.create(
            campaign=campaign,
            email="physics_teacher@example.com",
            recipient_name="Teacher Raman",
            status=CampaignRecipient.RecipientStatus.QUEUED,
        )

        result = send_bulk_campaign_task(str(campaign.id))
        self.assertGreater(result.get("sent", 0), 0)

        recip.refresh_from_db()
        self.assertEqual(recip.status, CampaignRecipient.RecipientStatus.SENT)
        self.assertEqual(recip.provider_message_id, "resend_req_msg_555")

    def test_quota_service_returns_used_key_and_reconciles_safely(self):
        status = DailyEmailQuotaService.get_quota_status()
        self.assertIn("used", status)
        self.assertIn("total_consumed", status)
        self.assertIn("daily_limit", status)
        self.assertEqual(status["daily_limit"], 100)
        self.assertEqual(status["used"], status["total_consumed"])


class EmailHealthServiceAndAdminViewTestCase(TestCase):
    def setUp(self):
        cache.clear()
        mail.outbox.clear()
        self.admin = User.objects.create_superuser(
            email="superadmin@sevajobs.in",
            password="SuperPass123!",
            first_name="Super",
            last_name="Admin",
            role=User.Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.client = Client()
        self.client.login(username="superadmin@sevajobs.in", password="SuperPass123!")
        session = self.client.session
        session["current_role_scope"] = "admin"
        session.save()
        if "sessionid" in self.client.cookies:
            self.client.cookies["sessionid_admin"] = self.client.cookies["sessionid"].value

    def test_mask_secret_helper(self):
        self.assertEqual(mask_secret(""), "[NOT SET]")
        self.assertEqual(mask_secret(None), "[NOT SET]")
        self.assertEqual(mask_secret("123"), "***")
        self.assertTrue(mask_secret("re_production_secret_123456").startswith("re_***"))

    def test_email_health_service_run_diagnostics(self):
        report = EmailHealthService.run_diagnostics(check_api=False)
        self.assertIn("overall_status", report)
        self.assertIn("configuration", report)
        self.assertIn("provider_client", report)
        self.assertIn("queue_worker", report)
        self.assertIn("quota_status", report)
        self.assertIn("recent_activity", report)

    def test_email_health_service_send_diagnostic_test(self):
        res = EmailHealthService.send_diagnostic_test("admin_test@sevajobs.in", actor_email="superadmin@sevajobs.in")
        self.assertEqual(res.get("status"), "sent")
        self.assertEqual(res.get("recipient"), "admin_test@sevajobs.in")

    def test_management_command_email_health_check(self):
        from io import StringIO
        out = StringIO()
        call_command("email_health_check", stdout=out)
        output = out.getvalue()
        self.assertIn("SEVAJOBS EMAIL INFRASTRUCTURE HEALTH CHECK REPORT", output)
        self.assertIn("Email Backend", output)

    def test_admin_email_quota_dashboard_view_renders_diagnostics(self):
        url = reverse("admin-panel:email-quota")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("health_diagnostics", response.context)
        self.assertContains(response, "Health &amp; Diagnostics")
        self.assertContains(response, "Safe Diagnostic Test")

    def test_admin_email_quota_dashboard_post_diagnostic_test_email(self):
        url = reverse("admin-panel:email-quota")
        response = self.client.post(
            url,
            {"action": "send_diagnostic_test_email", "test_recipient": "diagnostics_test@sevajobs.in"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Diagnostic email dispatched to diagnostics_test@sevajobs.in")
