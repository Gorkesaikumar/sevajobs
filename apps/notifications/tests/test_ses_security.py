"""Security tests for Amazon SES / AWS SNS webhook and transactional email integration."""

import json
import base64
import datetime
from unittest.mock import patch, MagicMock

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.x509.oid import NameOID

from django.test import TestCase, override_settings
from django.core import mail
from django.core.cache import cache
from django.urls import reverse
from django.contrib.auth import get_user_model

from apps.notifications.models import EmailSuppression
from apps.notifications.email_service import EmailService
from apps.notifications.tasks import send_transactional_email_task
from apps.notifications.views import build_sns_canonical_string

User = get_user_model()


def generate_rsa_key_and_cert():
    """Generate in-memory RSA keypair and self-signed X.509 PEM certificate."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "sns.amazonaws.com"),
    ])
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        private_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    ).not_valid_after(
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365)
    ).sign(private_key, hashes.SHA256())

    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    return private_key, cert_pem, cert


def sign_sns_payload(payload, private_key, version="2"):
    """Construct canonical string, compute signature, and attach to payload."""
    payload["SignatureVersion"] = version
    canonical_bytes = build_sns_canonical_string(payload)
    if isinstance(canonical_bytes, str):
        canonical_bytes = canonical_bytes.encode("utf-8")
    hash_algorithm = hashes.SHA256() if version == "2" else hashes.SHA1()
    
    signature_bytes = private_key.sign(
        canonical_bytes,
        padding.PKCS1v15(),
        hash_algorithm,
    )
    payload["Signature"] = base64.b64encode(signature_bytes).decode("utf-8")
    return payload


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_STORE_EAGER_RESULT=False,
    CELERY_CACHE_BACKEND="memory",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class SNSWebhookSecurityTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.private_key, cls.cert_pem, cls.cert_obj = generate_rsa_key_and_cert()
        cls.cert_url = "https://sns.ap-south-2.amazonaws.com/SimpleNotificationService-a160d5d2222e96414902ac793d58efe6.pem"
        cls.webhook_url = reverse("notifications:ses-webhook")

    def setUp(self):
        cache.clear()
        mail.outbox.clear()

    def _post_sns(self, payload):
        with patch("apps.notifications.views.get_sns_x509_certificate", return_value=self.cert_obj):
            return self.client.post(
                self.webhook_url,
                data=json.dumps(payload),
                content_type="application/json",
            )

    def _get_err(self, response):
        data = response.json()
        return data.get("detail") or data.get("error")

    # 1. Valid SNS Notification accepted
    def test_valid_sns_notification_accepted(self):
        message_data = {
            "notificationType": "Bounce",
            "bounce": {
                "bounceType": "Permanent",
                "bounceSubType": "General",
                "bouncedRecipients": [{"emailAddress": "validbounce@sevajobs.in"}],
            },
            "mail": {"messageId": "msg-11111", "timestamp": "2026-09-20T12:00:00Z"}
        }
        payload = {
            "Type": "Notification",
            "MessageId": "msg-id-1",
            "TopicArn": "arn:aws:sns:ap-south-2:123456789012:sevajobs-bounces",
            "Timestamp": "2026-09-20T12:00:00Z",
            "Message": json.dumps(message_data),
            "SigningCertURL": self.cert_url,
        }
        sign_sns_payload(payload, self.private_key)

        response = self._post_sns(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "processed")
        self.assertTrue(EmailSuppression.is_suppressed("validbounce@sevajobs.in"))

    # 2. Invalid signature rejected
    def test_invalid_signature_rejected(self):
        payload = {
            "Type": "Notification",
            "MessageId": "msg-id-2",
            "TopicArn": "arn:aws:sns:ap-south-2:123456789012:sevajobs-bounces",
            "Timestamp": "2026-09-20T12:00:00Z",
            "Message": "Hello",
            "SigningCertURL": self.cert_url,
            "SignatureVersion": "2",
            "Signature": base64.b64encode(b"invalid_signature_bytes").decode("utf-8"),
        }
        response = self._post_sns(payload)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._get_err(response), "Invalid or unverified SNS signature")

    # 3. Missing signature rejected
    def test_missing_signature_rejected(self):
        payload = {
            "Type": "Notification",
            "MessageId": "msg-id-3",
            "Message": "Hello",
            "SigningCertURL": self.cert_url,
        }
        response = self._post_sns(payload)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._get_err(response), "Invalid or unverified SNS signature")

    # 4. Invalid SigningCertURL rejected
    def test_invalid_signing_cert_url_rejected(self):
        payload = {
            "Type": "Notification",
            "MessageId": "msg-id-4",
            "Message": "Hello",
            "SigningCertURL": "ftp://sns.ap-south-2.amazonaws.com/cert.pem",
            "SignatureVersion": "2",
            "Signature": "dummy",
        }
        response = self._post_sns(payload)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._get_err(response), "Invalid or unverified SNS signature")

    # 5. HTTP SigningCertURL rejected
    def test_http_signing_cert_url_rejected(self):
        payload = {
            "Type": "Notification",
            "MessageId": "msg-id-5",
            "Message": "Hello",
            "SigningCertURL": "http://sns.ap-south-2.amazonaws.com/cert.pem",
            "SignatureVersion": "2",
            "Signature": "dummy",
        }
        response = self._post_sns(payload)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._get_err(response), "Invalid or unverified SNS signature")

    # 6. Malicious hostname rejected
    def test_malicious_hostname_rejected(self):
        malicious_urls = [
            "https://sns.amazonaws.com.attacker.com/cert.pem",
            "https://attacker.com/sns.amazonaws.com/cert.pem",
            "https://sns.ap-south-2.amazonaws.com.attacker.com/cert.pem",
            "https://user:pass@sns.ap-south-2.amazonaws.com/cert.pem",
            "https://sns.ap-south-2.amazonaws.com:8443/cert.pem",
            "https://sns.ap-south-2.amazonaws.com/cert.txt",
        ]
        for bad_url in malicious_urls:
            payload = {
                "Type": "Notification",
                "MessageId": "msg-id-6",
                "Message": "Hello",
                "SigningCertURL": bad_url,
                "SignatureVersion": "2",
                "Signature": "dummy",
            }
            response = self._post_sns(payload)
            self.assertEqual(response.status_code, 400, f"Failed to reject malicious URL: {bad_url}")
            self.assertEqual(self._get_err(response), "Invalid or unverified SNS signature")

    # 7. Malformed certificate rejected
    def test_malformed_certificate_rejected(self):
        payload = {
            "Type": "Notification",
            "MessageId": "msg-id-7",
            "TopicArn": "arn:aws:sns:ap-south-2:123456789012:sevajobs-bounces",
            "Timestamp": "2026-09-20T12:00:00Z",
            "Message": "Hello",
            "SigningCertURL": self.cert_url,
        }
        sign_sns_payload(payload, self.private_key)

        with patch("apps.notifications.views.get_sns_x509_certificate", side_effect=ValueError("Invalid cert format")):
            response = self.client.post(self.webhook_url, data=json.dumps(payload), content_type="application/json")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(self._get_err(response), "Invalid or unverified SNS signature")

    # 8. Certificate download failure handled
    def test_certificate_download_failure_handled(self):
        payload = {
            "Type": "Notification",
            "MessageId": "msg-id-8",
            "TopicArn": "arn:aws:sns:ap-south-2:123456789012:sevajobs-bounces",
            "Timestamp": "2026-09-20T12:00:00Z",
            "Message": "Hello",
            "SigningCertURL": self.cert_url,
        }
        sign_sns_payload(payload, self.private_key)

        with patch("apps.notifications.views.get_sns_x509_certificate", side_effect=Exception("Connection timeout")):
            response = self.client.post(self.webhook_url, data=json.dumps(payload), content_type="application/json")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(self._get_err(response), "Invalid or unverified SNS signature")

    # 9. Valid SubscriptionConfirmation handled
    def test_valid_subscription_confirmation_handled(self):
        payload = {
            "Type": "SubscriptionConfirmation",
            "MessageId": "msg-sub-1",
            "Token": "token123",
            "TopicArn": "arn:aws:sns:ap-south-2:123456789012:sevajobs-bounces",
            "Message": "Subscription confirmation requested",
            "SubscribeURL": "https://sns.ap-south-2.amazonaws.com/?Action=ConfirmSubscription&TopicArn=arn:aws:sns:ap-south-2:123:sevajobs-bounces",
            "Timestamp": "2026-09-20T12:00:00Z",
            "SigningCertURL": self.cert_url,
        }
        sign_sns_payload(payload, self.private_key)

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            response = self._post_sns(payload)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "subscription_confirmation_received")
            mock_urlopen.assert_called_once()

    # 10. Unverified SubscriptionConfirmation rejected
    def test_unverified_subscription_confirmation_rejected(self):
        payload = {
            "Type": "SubscriptionConfirmation",
            "MessageId": "msg-sub-2",
            "Token": "token123",
            "TopicArn": "arn:aws:sns:ap-south-2:123456789012:sevajobs-bounces",
            "Message": "Subscription confirmation requested",
            "SubscribeURL": "https://sns.ap-south-2.amazonaws.com/?Action=ConfirmSubscription",
            "Timestamp": "2026-09-20T12:00:00Z",
            "SigningCertURL": self.cert_url,
            "SignatureVersion": "2",
            "Signature": base64.b64encode(b"fake_signature").decode("utf-8"),
        }
        with patch("urllib.request.urlopen") as mock_urlopen:
            response = self._post_sns(payload)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(self._get_err(response), "Invalid or unverified SNS signature")
            mock_urlopen.assert_not_called()

    # 11. Malicious SubscribeURL rejected
    def test_malicious_subscribe_url_rejected(self):
        payload = {
            "Type": "SubscriptionConfirmation",
            "MessageId": "msg-sub-3",
            "Token": "token123",
            "TopicArn": "arn:aws:sns:ap-south-2:123456789012:sevajobs-bounces",
            "Message": "Subscription confirmation requested",
            "SubscribeURL": "https://attacker.com/exploit",
            "Timestamp": "2026-09-20T12:00:00Z",
            "SigningCertURL": self.cert_url,
        }
        sign_sns_payload(payload, self.private_key)

        with patch("urllib.request.urlopen") as mock_urlopen:
            response = self._post_sns(payload)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(self._get_err(response), "Invalid SubscribeURL")
            mock_urlopen.assert_not_called()

    # 12. Permanent bounce creates suppression
    def test_permanent_bounce_creates_suppression(self):
        message_data = {
            "notificationType": "Bounce",
            "bounce": {
                "bounceType": "Permanent",
                "bounceSubType": "General",
                "bouncedRecipients": [{"emailAddress": "PermanentBounce@SevaJobs.in"}],
            },
            "mail": {"messageId": "msg-perm-1", "timestamp": "2026-09-20T12:00:00Z"}
        }
        payload = {
            "Type": "Notification",
            "MessageId": "msg-id-12",
            "TopicArn": "arn:aws:sns:ap-south-2:123456789012:sevajobs-bounces",
            "Timestamp": "2026-09-20T12:00:00Z",
            "Message": json.dumps(message_data),
            "SigningCertURL": self.cert_url,
        }
        sign_sns_payload(payload, self.private_key)

        response = self._post_sns(payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(EmailSuppression.is_suppressed("permanentbounce@sevajobs.in"))

    # 13. Transient bounce does NOT create permanent suppression
    def test_transient_bounce_does_not_create_suppression(self):
        message_data = {
            "notificationType": "Bounce",
            "bounce": {
                "bounceType": "Transient",
                "bounceSubType": "General",
                "bouncedRecipients": [{"emailAddress": "transientbounce@sevajobs.in"}],
            },
            "mail": {"messageId": "msg-trans-1", "timestamp": "2026-09-20T12:00:00Z"}
        }
        payload = {
            "Type": "Notification",
            "MessageId": "msg-id-13",
            "TopicArn": "arn:aws:sns:ap-south-2:123456789012:sevajobs-bounces",
            "Timestamp": "2026-09-20T12:00:00Z",
            "Message": json.dumps(message_data),
            "SigningCertURL": self.cert_url,
        }
        sign_sns_payload(payload, self.private_key)

        response = self._post_sns(payload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(EmailSuppression.is_suppressed("transientbounce@sevajobs.in"))

    # 14. Complaint creates suppression
    def test_complaint_creates_suppression(self):
        message_data = {
            "notificationType": "Complaint",
            "complaint": {
                "complaintFeedbackType": "abuse",
                "complainedRecipients": [{"emailAddress": "complainant@sevajobs.in"}],
            },
            "mail": {"messageId": "msg-comp-1", "timestamp": "2026-09-20T12:00:00Z"}
        }
        payload = {
            "Type": "Notification",
            "MessageId": "msg-id-14",
            "TopicArn": "arn:aws:sns:ap-south-2:123456789012:sevajobs-bounces",
            "Timestamp": "2026-09-20T12:00:00Z",
            "Message": json.dumps(message_data),
            "SigningCertURL": self.cert_url,
        }
        sign_sns_payload(payload, self.private_key)

        response = self._post_sns(payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(EmailSuppression.is_suppressed("complainant@sevajobs.in"))

    # 15. Duplicate bounce is idempotent
    def test_duplicate_bounce_is_idempotent(self):
        message_data = {
            "notificationType": "Bounce",
            "bounce": {
                "bounceType": "Permanent",
                "bounceSubType": "General",
                "bouncedRecipients": [{"emailAddress": "dupebounce@sevajobs.in"}],
            },
            "mail": {"messageId": "msg-dupe-1", "timestamp": "2026-09-20T12:00:00Z"}
        }
        payload = {
            "Type": "Notification",
            "MessageId": "msg-id-15",
            "TopicArn": "arn:aws:sns:ap-south-2:123456789012:sevajobs-bounces",
            "Timestamp": "2026-09-20T12:00:00Z",
            "Message": json.dumps(message_data),
            "SigningCertURL": self.cert_url,
        }
        sign_sns_payload(payload, self.private_key)

        res1 = self._post_sns(payload)
        res2 = self._post_sns(payload)
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(EmailSuppression.objects.filter(email="dupebounce@sevajobs.in").count(), 1)

    # 16. Duplicate complaint is idempotent
    def test_duplicate_complaint_is_idempotent(self):
        message_data = {
            "notificationType": "Complaint",
            "complaint": {
                "complaintFeedbackType": "abuse",
                "complainedRecipients": [{"emailAddress": "dupecomplaint@sevajobs.in"}],
            },
            "mail": {"messageId": "msg-dupe-2", "timestamp": "2026-09-20T12:00:00Z"}
        }
        payload = {
            "Type": "Notification",
            "MessageId": "msg-id-16",
            "TopicArn": "arn:aws:sns:ap-south-2:123456789012:sevajobs-bounces",
            "Timestamp": "2026-09-20T12:00:00Z",
            "Message": json.dumps(message_data),
            "SigningCertURL": self.cert_url,
        }
        sign_sns_payload(payload, self.private_key)

        res1 = self._post_sns(payload)
        res2 = self._post_sns(payload)
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(EmailSuppression.objects.filter(email="dupecomplaint@sevajobs.in").count(), 1)

    # 17. Malformed Message JSON handled safely
    def test_malformed_message_json_handled_safely(self):
        payload = {
            "Type": "Notification",
            "MessageId": "msg-id-17",
            "TopicArn": "arn:aws:sns:ap-south-2:123456789012:sevajobs-bounces",
            "Timestamp": "2026-09-20T12:00:00Z",
            "Message": "NOT_JSON_DATA",
            "SigningCertURL": self.cert_url,
        }
        sign_sns_payload(payload, self.private_key)

        response = self._post_sns(payload)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._get_err(response), "Invalid JSON in Message payload")

    # 18. Unsupported notification type handled safely
    def test_unsupported_notification_type_handled_safely(self):
        message_data = {
            "notificationType": "AmazonS3Event",
        }
        payload = {
            "Type": "Notification",
            "MessageId": "msg-id-18",
            "TopicArn": "arn:aws:sns:ap-south-2:123456789012:sevajobs-bounces",
            "Timestamp": "2026-09-20T12:00:00Z",
            "Message": json.dumps(message_data),
            "SigningCertURL": self.cert_url,
        }
        sign_sns_payload(payload, self.private_key)

        response = self._post_sns(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ignored_notification_type")

    # Test PII reduction in stored details
    def test_pii_reduction_in_email_suppression_details(self):
        message_data = {
            "notificationType": "Bounce",
            "bounce": {
                "bounceType": "Permanent",
                "bounceSubType": "General",
                "bouncedRecipients": [
                    {
                        "emailAddress": "piitest@sevajobs.in",
                        "diagnosticCode": "smtp; 550 5.1.1 User unknown",
                        "status": "5.1.1",
                    }
                ],
            },
            "mail": {
                "messageId": "ses-msg-id-999",
                "timestamp": "2026-09-20T15:00:00Z",
                "destination": ["piitest@sevajobs.in"],
                "headers": [{"name": "X-Secret-Header", "value": "SecretToken123"}]
            }
        }
        payload = {
            "Type": "Notification",
            "MessageId": "msg-id-pii",
            "TopicArn": "arn:aws:sns:ap-south-2:123456789012:sevajobs-bounces",
            "Timestamp": "2026-09-20T12:00:00Z",
            "Message": json.dumps(message_data),
            "SigningCertURL": self.cert_url,
        }
        sign_sns_payload(payload, self.private_key)

        response = self._post_sns(payload)
        self.assertEqual(response.status_code, 200)

        suppression = EmailSuppression.objects.get(email="piitest@sevajobs.in")
        details = suppression.details

        # Ensure only minimized diagnostic info is saved, NO full SNS envelopes or raw headers
        self.assertEqual(details.get("bounce_type"), "Permanent")
        self.assertEqual(details.get("bounce_sub_type"), "General")
        self.assertEqual(details.get("diagnostic_code"), "smtp; 550 5.1.1 User unknown")
        self.assertEqual(details.get("ses_message_id"), "ses-msg-id-999")
        self.assertNotIn("headers", json.dumps(details))
        self.assertNotIn("X-Secret-Header", json.dumps(details))
        self.assertNotIn("SigningCertURL", json.dumps(details))


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_STORE_EAGER_RESULT=False,
    CELERY_CACHE_BACKEND="memory",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class EmailTemplatesAndTriggersTestCase(TestCase):
    """Test all transactional email templates and service triggers."""

    def setUp(self):
        cache.clear()
        mail.outbox.clear()

    def test_all_email_templates_render_and_send(self):
        templates = [
            ("welcome", {"first_name": "John"}),
            ("verification", {"first_name": "John", "verification_url": "http://localhost/verify?t=1", "ttl_hours": 48}),
            ("password_reset", {"first_name": "John", "reset_url": "http://localhost/reset?t=1", "ttl_hours": 24}),
            ("password_changed", {"first_name": "John"}),
            ("application_submitted", {"candidate_name": "John", "job_title": "Software Engineer", "company_name": "Tech Corp"}),
            ("recruiter_new_application", {"recruiter_name": "Jane", "candidate_name": "John", "job_title": "Software Engineer", "application_url": "http://localhost/app/1"}),
            ("shortlisted", {"candidate_name": "John", "job_title": "Software Engineer", "company_name": "Tech Corp"}),
            ("interview_scheduled", {"candidate_name": "John", "job_title": "Software Engineer", "company_name": "Tech Corp", "interview_date": "2026-10-01", "interview_mode": "Online"}),
            ("selected", {"candidate_name": "John", "job_title": "Software Engineer", "company_name": "Tech Corp"}),
            ("rejected", {"candidate_name": "John", "job_title": "Software Engineer", "company_name": "Tech Corp"}),
            ("joining", {"candidate_name": "John", "job_title": "Software Engineer", "company_name": "Tech Corp", "joining_date": "2026-10-15"}),
            ("job_approval_decision", {"recruiter_name": "Jane", "job_title": "Software Engineer", "status": "Approved", "reason": "Looks good"}),
        ]

        for template_name, context in templates:
            mail.outbox.clear()
            with self.captureOnCommitCallbacks(execute=True):
                success = EmailService.send_template_email(
                    template_name=template_name,
                    to_email="test@example.com",
                    subject=f"Test {template_name}",
                    context=context,
                )
            self.assertTrue(success, f"Failed to render template: {template_name}")
            self.assertEqual(len(mail.outbox), 1, f"No email sent for template: {template_name}")
            self.assertEqual(mail.outbox[0].subject, f"Test {template_name}")
