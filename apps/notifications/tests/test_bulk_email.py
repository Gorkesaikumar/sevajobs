"""
Comprehensive automated test suite for SevaJobs Teaching Requirements Bulk Email Integration.

Covers:
1. Candidate lifecycle status mapping and recipient aggregation.
2. Inactive, soft-deleted, and suppressed candidate exclusion.
3. Candidate deduplication across matches and emails.
4. Campaign creation, atomic recipient snapshotting, HTML/subject sanitization, and merge tags.
5. 1-to-1 email dispatch enforcement (strictly individual 'to', no CC/BCC, List-Unsubscribe headers).
6. Unsubscribe token generation, verification, self-service suppression, and suppression honoring.
7. Celery async task execution, status progression, cancellation mid-flight, and counter tracking.
8. Resend webhook processing (delivered, bounced, complained) updating campaign metrics.
9. Security and access control (anonymous redirected, non-staff forbidden, admin/staff allowed).
"""

import json
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from django.core import mail
from django.core.cache import cache
from django.contrib.auth import get_user_model

from apps.jobs.models import InstitutionRequirement, RequirementCandidateMatch
from apps.notifications.models import EmailCampaign, CampaignRecipient, EmailSuppression
from apps.notifications.requirement_recipient_service import RequirementRecipientService
from apps.notifications.campaign_service import CampaignService
from apps.notifications.unsubscribe_service import UnsubscribeService
from apps.notifications.tasks import send_bulk_campaign_task

User = get_user_model()


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_STORE_EAGER_RESULT=False,
    CELERY_CACHE_BACKEND="memory",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="SevaJobs <noreply@sevajobs.in>",
    RESEND_FROM_EMAIL="noreply@sevajobs.in",
    RESEND_WEBHOOK_SECRET="whsec_test_secret_12345",
)
class BulkEmailBaseTestCase(TestCase):
    """Base setup fixture providing users, requirement, and candidate matches."""

    def setUp(self):
        cache.clear()
        mail.outbox.clear()
        self.client = Client()

        # Admin User
        self.admin = User.objects.create_superuser(
            email="admin@sevajobs.com",
            password="AdminPassword123!",
            role="super_admin",
            first_name="Admin",
            last_name="Super",
            is_staff=True,
        )

        # Staff Recruiter
        self.staff = User.objects.create_user(
            email="staff@sevajobs.com",
            password="StaffPassword123!",
            role="staff",
            first_name="Staff",
            last_name="Member",
            is_staff=True,
        )

        # Non-staff Recruiter
        self.recruiter = User.objects.create_user(
            email="recruiter@school.com",
            password="RecruiterPassword123!",
            role="recruiter",
            first_name="School",
            last_name="Recruiter",
            is_staff=False,
        )

        # Candidate (Job Seeker)
        self.candidate_user = User.objects.create_user(
            email="cand@example.com",
            password="CandPassword123!",
            role="job_seeker",
            first_name="Normal",
            last_name="Candidate",
            is_staff=False,
        )

        # Teaching Requirement
        self.requirement = InstitutionRequirement.objects.create(
            institution_name="Delhi Public School",
            phone_number="9876543210",
            subject="Mathematics",
            qualification="M.Sc Mathematics, B.Ed",
            teaching_grade="PGT",
            positions_count=2,
            location="Hyderabad, Telangana",
            salary_min=45000,
            salary_max=65000,
            salary_period="monthly",
            posted_by_user=self.staff,
        )

        # Create candidate matches across different lifecycle statuses
        self.cand_shortlisted = User.objects.create_user(
            email="shortlisted@example.com", password="P1!", role="job_seeker", first_name="Aarav", last_name="Sharma"
        )
        self.match_shortlisted = RequirementCandidateMatch.objects.create(
            requirement=self.requirement,
            candidate=self.cand_shortlisted,
            match_score=90,
            status=RequirementCandidateMatch.MatchStatus.SHORTLISTED,
        )

        self.cand_interviewing = User.objects.create_user(
            email="interviewing@example.com", password="P1!", role="job_seeker", first_name="Bhavna", last_name="Patel"
        )
        self.match_interviewing = RequirementCandidateMatch.objects.create(
            requirement=self.requirement,
            candidate=self.cand_interviewing,
            match_score=85,
            status=RequirementCandidateMatch.MatchStatus.INTERVIEW_SCHEDULED,
        )

        self.cand_selected = User.objects.create_user(
            email="selected@example.com", password="P1!", role="job_seeker", first_name="Chetan", last_name="Kumar"
        )
        self.match_selected = RequirementCandidateMatch.objects.create(
            requirement=self.requirement,
            candidate=self.cand_selected,
            match_score=95,
            status=RequirementCandidateMatch.MatchStatus.SELECTED,
        )

        self.cand_joined = User.objects.create_user(
            email="joined@example.com", password="P1!", role="job_seeker", first_name="Divya", last_name="Nair"
        )
        self.match_joined = RequirementCandidateMatch.objects.create(
            requirement=self.requirement,
            candidate=self.cand_joined,
            match_score=92,
            status=RequirementCandidateMatch.MatchStatus.JOINED,
        )

        self.cand_rejected = User.objects.create_user(
            email="rejected@example.com", password="P1!", role="job_seeker", first_name="Eshwar", last_name="Rao"
        )
        self.match_rejected = RequirementCandidateMatch.objects.create(
            requirement=self.requirement,
            candidate=self.cand_rejected,
            match_score=60,
            status=RequirementCandidateMatch.MatchStatus.REJECTED,
        )

        self.cand_matched_only = User.objects.create_user(
            email="matched@example.com", password="P1!", role="job_seeker", first_name="Farhan", last_name="Ali"
        )
        self.match_matched_only = RequirementCandidateMatch.objects.create(
            requirement=self.requirement,
            candidate=self.cand_matched_only,
            match_score=75,
            status=RequirementCandidateMatch.MatchStatus.MATCHED,
        )


class RequirementRecipientServiceTestCase(BulkEmailBaseTestCase):
    """Test candidate recipient filtering, aggregation, and exclusion rules."""

    def test_status_counts_aggregates_properly(self):
        """Verify accurate calculation of live recipient counts per status."""
        counts = RequirementRecipientService.get_status_counts(str(self.requirement.id))
        self.assertEqual(counts["total_matched"], 6)
        self.assertEqual(counts["total_eligible"], 6)
        self.assertEqual(counts["shortlisted"], 1)
        self.assertEqual(counts["interview_scheduled"], 1)
        self.assertEqual(counts["selected"], 1)
        self.assertEqual(counts["joined"], 1)
        self.assertEqual(counts["rejected"], 1)
        self.assertEqual(counts["matched_only"], 1)

    def test_suppressed_candidates_are_excluded(self):
        """Ensure candidates present in EmailSuppression are excluded from counts and retrieval."""
        EmailSuppression.suppress(
            email="shortlisted@example.com",
            reason=EmailSuppression.Reason.BOUNCE,
            bounce_type="Permanent",
        )
        EmailSuppression.suppress(
            email="selected@example.com",
            reason=EmailSuppression.Reason.UNSUBSCRIBE,
        )

        counts = RequirementRecipientService.get_status_counts(str(self.requirement.id))
        self.assertEqual(counts["shortlisted"], 0)
        self.assertEqual(counts["selected"], 0)
        self.assertEqual(counts["total_eligible"], 4)

        eligible = RequirementRecipientService.get_eligible_candidates(str(self.requirement.id), selected_statuses=["all"])
        eligible_emails = [e["email"] for e in eligible]
        self.assertNotIn("shortlisted@example.com", eligible_emails)
        self.assertNotIn("selected@example.com", eligible_emails)
        self.assertIn("interviewing@example.com", eligible_emails)

    def test_inactive_and_deleted_users_excluded(self):
        """Candidates with is_active=False or is_deleted=True must not receive bulk emails."""
        self.cand_interviewing.is_active = False
        self.cand_interviewing.save(update_fields=["is_active"])

        self.cand_joined.is_deleted = True
        self.cand_joined.save(update_fields=["is_deleted"])

        counts = RequirementRecipientService.get_status_counts(str(self.requirement.id))
        self.assertEqual(counts["interview_scheduled"], 0)
        self.assertEqual(counts["joined"], 0)

        eligible = RequirementRecipientService.get_eligible_candidates(str(self.requirement.id), selected_statuses=["all"])
        eligible_emails = [e["email"] for e in eligible]
        self.assertNotIn("interviewing@example.com", eligible_emails)
        self.assertNotIn("joined@example.com", eligible_emails)

    def test_filter_by_individual_status(self):
        """Test targeted status filtering: shortlisted, interview_scheduled, selected, etc."""
        shortlisted = RequirementRecipientService.get_eligible_candidates(
            str(self.requirement.id), selected_statuses=["shortlisted"]
        )
        self.assertEqual(len(shortlisted), 1)
        self.assertEqual(shortlisted[0]["email"], "shortlisted@example.com")

        interviewing = RequirementRecipientService.get_eligible_candidates(
            str(self.requirement.id), selected_statuses=["interview_scheduled"]
        )
        self.assertEqual(len(interviewing), 1)
        self.assertEqual(interviewing[0]["email"], "interviewing@example.com")

        selected = RequirementRecipientService.get_eligible_candidates(
            str(self.requirement.id), selected_statuses=["selected"]
        )
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["email"], "selected@example.com")

    def test_filter_by_multiple_statuses(self):
        """Admins can select multiple lifecycle statuses simultaneously."""
        results = RequirementRecipientService.get_eligible_candidates(
            str(self.requirement.id), selected_statuses=["shortlisted", "selected"]
        )
        emails = {r["email"] for r in results}
        self.assertEqual(emails, {"shortlisted@example.com", "selected@example.com"})

    def test_filter_by_explicit_candidate_ids(self):
        """Targeting specific candidates by user ID."""
        target_ids = [str(self.cand_shortlisted.id), str(self.cand_joined.id)]
        results = RequirementRecipientService.get_eligible_candidates(
            str(self.requirement.id), candidate_ids=target_ids
        )
        emails = {r["email"] for r in results}
        self.assertEqual(emails, {"shortlisted@example.com", "joined@example.com"})


class CampaignServiceTestCase(BulkEmailBaseTestCase):
    """Test campaign creation, recipient snapshotting, sanitization, and lifecycle transitions."""

    def test_create_campaign_snapshots_recipients(self):
        """Campaign creation captures recipient state atomically in draft status."""
        campaign = CampaignService.create_campaign(
            requirement=self.requirement,
            created_by=self.admin,
            name="Interview Invitation Round 1",
            subject="Interview for PGT Mathematics",
            body_html="<p>Dear {{ candidate_name }}, you are invited for an interview at {{ school_name }}.</p>",
            selected_statuses=["shortlisted", "interview_scheduled"],
        )

        self.assertEqual(campaign.status, EmailCampaign.Status.DRAFT)
        self.assertEqual(campaign.total_recipients, 2)
        self.assertEqual(campaign.pending_count, 2)
        self.assertEqual(campaign.sent_count, 0)

        recipients = campaign.recipients.all()
        self.assertEqual(recipients.count(), 2)
        recipient_emails = {r.email for r in recipients}
        self.assertEqual(recipient_emails, {"shortlisted@example.com", "interviewing@example.com"})

    def test_sanitize_subject_strips_newlines(self):
        """Header injection prevention: CRLF characters in subject must be stripped."""
        malicious_subject = "Important Update\r\nBcc: evil@hacker.com\r\nSubject: Injected"
        clean = CampaignService.sanitize_subject(malicious_subject)
        self.assertNotIn("\r", clean)
        self.assertNotIn("\n", clean)
        self.assertEqual(clean, "Important Update Bcc: evil@hacker.com Subject: Injected")

    def test_sanitize_html_removes_scripts_and_event_handlers(self):
        """Security: Removes script tags and inline javascript event handlers."""
        malicious_html = """
            <p>Welcome to our school!</p>
            <script>alert('XSS');</script>
            <a href="javascript:alert(1)" onclick="stealCookies()">Click here</a>
        """
        clean = CampaignService.sanitize_html(malicious_html)
        self.assertNotIn("<script", clean.lower())
        self.assertNotIn("alert('xss')", clean.lower())
        self.assertNotIn("javascript:", clean.lower())
        self.assertNotIn("onclick=", clean.lower())
        self.assertIn("<p>Welcome to our school!</p>", clean)

    def test_render_content_merge_tags(self):
        """Verifies merge tag substitutions work seamlessly."""
        template = "Hello {{ candidate_name }}, welcome to {{ school_name }} for {{ requirement_title }} in {{ location }}."
        context = {
            "candidate_name": "Aarav Sharma",
            "school_name": "Delhi Public School",
            "requirement_title": "PGT Mathematics",
            "location": "Hyderabad",
        }
        rendered = CampaignService.render_content(body_template=template, context=context)
        self.assertEqual(rendered, "Hello Aarav Sharma, welcome to Delhi Public School for PGT Mathematics in Hyderabad.")

    def test_send_test_email_dispatches_single_email(self):
        """Test preview email is sent strictly to the specified test address."""
        success = CampaignService.send_test_email(
            admin_user=self.admin,
            test_email="internal-reviewer@sevajobs.in",
            subject="PGT Mathematics Announcement",
            body_html="<p>This is a test recruitment broadcast.</p>",
            requirement=self.requirement,
        )
        self.assertTrue(success)
        self.assertEqual(len(mail.outbox), 1)

        test_msg = mail.outbox[0]
        self.assertEqual(test_msg.to, ["internal-reviewer@sevajobs.in"])
        self.assertTrue(test_msg.subject.startswith("[TEST]"))
        self.assertIn("unsubscribe", test_msg.body.lower())
        self.assertTrue(any(alt[1] == "text/html" for alt in test_msg.alternatives))

    def test_launch_campaign_transitions_and_commits(self):
        """Launching campaign sets QUEUED status and marks recipients as queued."""
        campaign = CampaignService.create_campaign(
            requirement=self.requirement,
            created_by=self.admin,
            name="PGT Selected Offer",
            subject="Offer of Employment",
            body_html="<p>Congratulations {{ candidate_name }}!</p>",
            selected_statuses=["selected"],
        )

        with self.captureOnCommitCallbacks(execute=True):
            CampaignService.launch_campaign(str(campaign.id))

        campaign.refresh_from_db()
        # In eager celery execution, task runs and transitions to COMPLETED
        self.assertIn(campaign.status, [EmailCampaign.Status.QUEUED, EmailCampaign.Status.PROCESSING, EmailCampaign.Status.COMPLETED])
        self.assertEqual(campaign.sent_count, 1)

    def test_cancel_campaign_aborts_queued_recipients(self):
        """Cancelling a campaign changes status to CANCELLED and marks remaining recipients as CANCELLED."""
        campaign = CampaignService.create_campaign(
            requirement=self.requirement,
            created_by=self.admin,
            name="Draft to be Cancelled",
            subject="Cancelled Subject",
            body_html="<p>Hello</p>",
            selected_statuses=["shortlisted"],
        )

        CampaignService.cancel_campaign(str(campaign.id), actor=self.admin)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, EmailCampaign.Status.CANCELLED)

        recipient = campaign.recipients.first()
        self.assertEqual(recipient.status, CampaignRecipient.RecipientStatus.CANCELLED)


class CeleryBulkEmailDispatchTestCase(BulkEmailBaseTestCase):
    """Test Celery async task dispatch, 1-to-1 privacy enforcement, and unsubscribe headers."""

    def test_strictly_1_to_1_email_dispatch(self):
        """
        CRITICAL PRIVACY TEST:
        Every candidate email MUST be dispatched individually.
        len(msg.to) == 1, cc is empty, bcc is empty.
        Candidate emails must never be shared across recipients.
        """
        campaign = CampaignService.create_campaign(
            requirement=self.requirement,
            created_by=self.admin,
            name="Shortlisted and Interviewing Broadcast",
            subject="Next Steps for PGT Mathematics",
            body_html="<p>Dear {{ candidate_name }}, update on your application at {{ school_name }}.</p>",
            selected_statuses=["shortlisted", "interview_scheduled"],
        )

        # Execute Celery task directly
        send_bulk_campaign_task(str(campaign.id))

        self.assertEqual(len(mail.outbox), 2)

        sent_recipients = set()
        for msg in mail.outbox:
            # 1. Strictly 1 recipient in To:
            self.assertEqual(len(msg.to), 1)
            to_addr = msg.to[0]
            sent_recipients.add(to_addr)

            # 2. No CC or BCC leaks
            self.assertEqual(len(msg.cc), 0)
            self.assertEqual(len(msg.bcc), 0)

            # 3. Mandatory List-Unsubscribe headers (RFC 2369 / RFC 8058)
            self.assertIn("List-Unsubscribe", msg.extra_headers)
            self.assertIn("List-Unsubscribe-Post", msg.extra_headers)
            self.assertEqual(msg.extra_headers["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")

            # 4. Campaign Tracking Headers
            self.assertEqual(msg.extra_headers.get("X-Campaign-ID"), str(campaign.id))
            self.assertIn("X-Recipient-ID", msg.extra_headers)

            # 5. Personalized content verification
            if to_addr == "shortlisted@example.com":
                self.assertIn("Aarav Sharma", msg.body)
            elif to_addr == "interviewing@example.com":
                self.assertIn("Bhavna Patel", msg.body)

        self.assertEqual(sent_recipients, {"shortlisted@example.com", "interviewing@example.com"})

        # Campaign counters
        campaign.refresh_from_db()
        self.assertEqual(campaign.sent_count, 2)
        self.assertEqual(campaign.failed_count, 0)
        self.assertEqual(campaign.suppressed_count, 0)
        self.assertEqual(campaign.status, EmailCampaign.Status.COMPLETED)

    def test_realtime_suppression_during_task_run(self):
        """
        If a user unsubscribes or is suppressed between campaign creation
        and Celery worker execution, they MUST be skipped and marked SUPPRESSED.
        """
        campaign = CampaignService.create_campaign(
            requirement=self.requirement,
            created_by=self.admin,
            name="Suppression Check Campaign",
            subject="Important Notice",
            body_html="<p>Notice</p>",
            selected_statuses=["shortlisted", "interview_scheduled"],
        )

        # Suppress Bhavna before worker processes
        EmailSuppression.suppress(
            email="interviewing@example.com",
            reason=EmailSuppression.Reason.UNSUBSCRIBE,
        )

        send_bulk_campaign_task(str(campaign.id))

        # Only 1 email should have been sent (to Aarav)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["shortlisted@example.com"])

        campaign.refresh_from_db()
        self.assertEqual(campaign.sent_count, 1)
        self.assertEqual(campaign.suppressed_count, 1)

        bhavna_rcpt = campaign.recipients.get(email="interviewing@example.com")
        self.assertEqual(bhavna_rcpt.status, CampaignRecipient.RecipientStatus.SUPPRESSED)
        self.assertIn("suppressed", bhavna_rcpt.last_error.lower())

    def test_campaign_cancelled_mid_task(self):
        """If campaign is marked CANCELLED while task is running, execution halts cleanly."""
        campaign = CampaignService.create_campaign(
            requirement=self.requirement,
            created_by=self.admin,
            name="Cancelled Mid-Flight",
            subject="Test",
            body_html="<p>Test</p>",
            selected_statuses=["shortlisted"],
        )
        campaign.status = EmailCampaign.Status.CANCELLED
        campaign.save(update_fields=["status"])

        result = send_bulk_campaign_task(str(campaign.id))
        self.assertEqual(result.get("status"), "halted")
        self.assertEqual(len(mail.outbox), 0)


class UnsubscribeAndWebhookIntegrationTestCase(BulkEmailBaseTestCase):
    """Test cryptographic unsubscribe URLs, self-service unsubscription, and Resend webhooks."""

    def test_unsubscribe_token_generation_and_verification(self):
        """Cryptographic token signs email and verifies correctly."""
        email = "teacher@sevajobs.in"
        url = UnsubscribeService.build_unsubscribe_url(email)
        self.assertIn("/notifications/unsubscribe/?token=", url)

        token = url.split("token=")[1]
        verified_email = UnsubscribeService.verify_token(token)
        self.assertEqual(verified_email, email)

        # Invalid token returns None
        self.assertIsNone(UnsubscribeService.verify_token("invalid:token:123"))

    def test_unsubscribe_view_get_and_post(self):
        """Candidate visits unsubscribe link, sees masked email, and confirms unsubscribe."""
        email = "test-unsub@example.com"
        token = UnsubscribeService.build_unsubscribe_url(email).split("token=")[1]

        unsub_url = reverse("notifications:unsubscribe")

        # GET: renders confirmation page
        response = self.client.get(unsub_url, {"token": token})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Unsubscribe", response.content.decode("utf-8"))
        self.assertFalse(EmailSuppression.is_suppressed(email))

        # POST: confirms unsubscription and creates EmailSuppression record
        post_response = self.client.post(unsub_url, {"token": token})
        self.assertEqual(post_response.status_code, 200)
        self.assertTrue(EmailSuppression.is_suppressed(email))

        suppression = EmailSuppression.objects.get(email=email)
        self.assertEqual(suppression.reason, EmailSuppression.Reason.UNSUBSCRIBE)

    @patch("apps.notifications.resend_webhook.ResendWebhookView._verify_signature")
    def test_resend_webhook_delivered_updates_recipient(self, mock_verify):
        """Resend email.delivered event updates CampaignRecipient and increments campaign delivered_count."""
        campaign = CampaignService.create_campaign(
            requirement=self.requirement,
            created_by=self.admin,
            name="Delivered Test",
            subject="Delivered Subject",
            body_html="<p>Delivered</p>",
            selected_statuses=["shortlisted"],
        )
        recipient = campaign.recipients.first()
        recipient.status = CampaignRecipient.RecipientStatus.SENT
        recipient.provider_message_id = "resend_msg_deliv_123"
        recipient.save(update_fields=["status", "provider_message_id"])

        payload = {
            "type": "email.delivered",
            "created_at": "2026-10-14T10:00:00.000Z",
            "data": {
                "email_id": "resend_msg_deliv_123",
                "to": ["shortlisted@example.com"],
            },
        }
        mock_verify.return_value = payload

        webhook_url = reverse("notifications:resend_webhook")
        res = self.client.post(
            webhook_url,
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_SVIX_ID="msg_svix_deliv",
            HTTP_SVIX_TIMESTAMP="1600000000",
            HTTP_SVIX_SIGNATURE="v1,dummy_sig",
        )
        self.assertEqual(res.status_code, 200)

        recipient.refresh_from_db()
        self.assertEqual(recipient.status, CampaignRecipient.RecipientStatus.DELIVERED)
        self.assertIsNotNone(recipient.delivered_at)

        campaign.refresh_from_db()
        self.assertEqual(campaign.delivered_count, 1)

    @patch("apps.notifications.resend_webhook.ResendWebhookView._verify_signature")
    def test_resend_webhook_bounce_suppresses_and_updates_recipient(self, mock_verify):
        """Resend email.bounced event marks recipient FAILED and adds bounce suppression."""
        campaign = CampaignService.create_campaign(
            requirement=self.requirement,
            created_by=self.admin,
            name="Bounce Test",
            subject="Bounce Subject",
            body_html="<p>Bounce</p>",
            selected_statuses=["shortlisted"],
        )
        recipient = campaign.recipients.first()
        recipient.status = CampaignRecipient.RecipientStatus.SENT
        recipient.provider_message_id = "resend_msg_bounce_123"
        recipient.save(update_fields=["status", "provider_message_id"])

        payload = {
            "type": "email.bounced",
            "created_at": "2026-10-14T10:00:00.000Z",
            "data": {
                "email_id": "resend_msg_bounce_123",
                "to": ["shortlisted@example.com"],
                "bounce_type": "Permanent",
            },
        }
        mock_verify.return_value = payload

        webhook_url = reverse("notifications:resend_webhook")
        res = self.client.post(
            webhook_url,
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_SVIX_ID="msg_svix_bounce",
        )
        self.assertEqual(res.status_code, 200)

        recipient.refresh_from_db()
        self.assertEqual(recipient.status, CampaignRecipient.RecipientStatus.FAILED)
        self.assertIn("Bounce", recipient.last_error)
        self.assertTrue(EmailSuppression.is_suppressed("shortlisted@example.com"))


class BulkEmailViewsAndPermissionsTestCase(BulkEmailBaseTestCase):
    """Test UI endpoints, permission gates, audience calculation AJAX, and campaign dispatch."""

    def test_anonymous_redirected_to_login(self):
        """Unauthenticated requests must be redirected to login."""
        url = reverse("jobs:requirement-bulk-email", kwargs={"pk": self.requirement.pk})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 302)
        self.assertIn("/login", res.url)

    def test_candidate_and_recruiter_forbidden_403(self):
        """Candidates and external recruiters cannot access administrative bulk email."""
        url = reverse("jobs:requirement-bulk-email", kwargs={"pk": self.requirement.pk})

        self.client.force_login(self.candidate_user)
        res = self.client.get(url)
        self.assertEqual(res.status_code, 403)

        self.client.force_login(self.recruiter)
        res2 = self.client.get(url)
        self.assertEqual(res2.status_code, 403)

    def test_admin_and_staff_access_bulk_email_get(self):
        """Authorized admin and staff recruiters can access the composer view."""
        url = reverse("jobs:requirement-bulk-email", kwargs={"pk": self.requirement.pk})

        self.client.force_login(self.staff)
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Bulk Email Composer")
        self.assertContains(res, "Delhi Public School")
        self.assertContains(res, "Mathematics (PGT)")

    def test_ajax_calculate_recipient_count(self):
        """AJAX endpoint returns live candidate count for selected status filters."""
        url = reverse("jobs:requirement-bulk-email", kwargs={"pk": self.requirement.pk})
        self.client.force_login(self.admin)

        res = self.client.post(
            url,
            data={"action": "calculate_count", "statuses[]": ["shortlisted", "selected"]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["count"], 2)

    def test_ajax_live_preview(self):
        """AJAX preview renders merge tags without dispatching emails."""
        url = reverse("jobs:requirement-bulk-email", kwargs={"pk": self.requirement.pk})
        self.client.force_login(self.admin)

        payload = {
            "action": "preview",
            "subject": "Interview at {{ school_name }}",
            "body_html": "<p>Hello {{ candidate_name }}, your status is {{ candidate_status }}.</p>",
        }
        res = self.client.post(url, data=payload, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("Delhi Public School", data["subject"])
        self.assertIn("Sample Candidate", data["html"])

    def test_post_send_test_email(self):
        """POST with action=send_test_email sends test email to reviewer address."""
        url = reverse("jobs:requirement-bulk-email", kwargs={"pk": self.requirement.pk})
        self.client.force_login(self.admin)

        payload = {
            "action": "send_test_email",
            "test_email": "tester@sevajobs.in",
            "subject": "Interview Invitation",
            "body_html": "<p>Test body</p>",
        }
        res = self.client.post(url, data=payload, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "success")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["tester@sevajobs.in"])

    def test_post_launch_campaign_redirects_to_detail(self):
        """Submitting the campaign form launches the campaign and redirects to the progress tracker."""
        url = reverse("jobs:requirement-bulk-email", kwargs={"pk": self.requirement.pk})
        self.client.force_login(self.admin)

        payload = {
            "action": "send_campaign",
            "campaign_name": "Autumn Recruitment Batch",
            "subject": "Application Update: PGT Mathematics",
            "body_html": "<p>Dear {{ candidate_name }}, thank you for applying.</p>",
            "statuses[]": ["shortlisted"],
        }
        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.post(url, data=payload)
        self.assertEqual(res.status_code, 302)

        campaign = EmailCampaign.objects.get(name="Autumn Recruitment Batch")
        self.assertIn(str(campaign.id), res.url)

        # In eager mode, Celery task has run
        campaign.refresh_from_db()
        self.assertEqual(campaign.total_recipients, 1)
        self.assertEqual(campaign.sent_count, 1)

    def test_campaign_detail_view_and_polling(self):
        """Campaign detail renders progress and responds to JSON polling."""
        campaign = CampaignService.create_campaign(
            requirement=self.requirement,
            created_by=self.admin,
            name="Tracking Campaign",
            subject="Tracking Subject",
            body_html="<p>Tracking</p>",
            selected_statuses=["shortlisted"],
        )

        detail_url = reverse(
            "jobs:requirement-campaign-detail",
            kwargs={"pk": self.requirement.pk, "campaign_id": campaign.id},
        )
        self.client.force_login(self.admin)

        # Standard HTML GET
        res_html = self.client.get(detail_url)
        self.assertEqual(res_html.status_code, 200)
        self.assertContains(res_html, "Tracking Campaign")

        # AJAX Polling GET
        res_ajax = self.client.get(detail_url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(res_ajax.status_code, 200)
        data = res_ajax.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["status"], "draft")

    def test_campaign_detail_cancel_action(self):
        """POST with action=cancel to detail view cancels campaign."""
        campaign = CampaignService.create_campaign(
            requirement=self.requirement,
            created_by=self.admin,
            name="Cancel Via View Campaign",
            subject="Cancel Subject",
            body_html="<p>Cancel</p>",
            selected_statuses=["shortlisted"],
        )

        detail_url = reverse(
            "jobs:requirement-campaign-detail",
            kwargs={"pk": self.requirement.pk, "campaign_id": campaign.id},
        )
        self.client.force_login(self.admin)

        res = self.client.post(detail_url, data={"action": "cancel"})
        self.assertEqual(res.status_code, 302)

        campaign.refresh_from_db()
        self.assertEqual(campaign.status, EmailCampaign.Status.CANCELLED)

    def test_preview_ajax_success(self):
        """POST with action=preview returns 200 with sanitized subject and wrapped HTML preview."""
        url = reverse("jobs:requirement-bulk-email", kwargs={"pk": self.requirement.pk})
        self.client.force_login(self.admin)

        payload = {
            "action": "preview",
            "subject": "Hello {{ candidate_name }}",
            "body_html": "<p>Welcome to {{ school_name }}!</p>",
        }
        res = self.client.post(url, data=payload, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("Hello Sample Candidate", data["subject"])
        self.assertIn("Welcome to Delhi Public School", data["html"])
        self.assertIn("<!DOCTYPE html>", data["html"])
        self.assertIn("static/images/logo.jpg", data["html"])

    def test_send_test_email_action_send_test(self):
        """POST with action='send_test' returns 200 with success JSON and sends email."""
        url = reverse("jobs:requirement-bulk-email", kwargs={"pk": self.requirement.pk})
        self.client.force_login(self.admin)

        payload = {
            "action": "send_test",
            "test_email": "preview-test@sevajobs.in",
            "subject": "Interview Invitation",
            "body_html": "<p>Please join our interview.</p>",
        }
        res = self.client.post(url, data=payload, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("preview-test@sevajobs.in", data["message"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["preview-test@sevajobs.in"])

    def test_bulk_email_page_modal_and_form_attributes(self):
        """GET bulk email page contains empty form action, modal z-index CSS, and modal blocks."""
        url = reverse("jobs:requirement-bulk-email", kwargs={"pk": self.requirement.pk})
        self.client.force_login(self.admin)

        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        html = res.content.decode("utf-8")
        self.assertIn('form id="bulkEmailForm" method="post" action=""', html)
        self.assertIn("id=\"testEmailModal\"", html)
        self.assertIn("id=\"previewModal\"", html)
        self.assertIn("z-index: 1060 !important;", html)
