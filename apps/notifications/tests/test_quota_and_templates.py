"""
Comprehensive Test Suite for Recruitment Email Templates & Daily Email Quota System.
Covers:
1. Canonical default templates per recruitment lifecycle status
2. Template rendering, custom saving, and resetting to canonical default
3. DailyEmailQuotaService atomic reservations, warning/target thresholds, and hard limit enforcement
4. Quota release upon cancellation and suppression
5. Failed recipient retry with daily quota reservation
6. Daily quota reconciliation against database records
7. JSON quota status endpoint for persistent navbar indicator
8. Admin Email Quota & Delivery Health Dashboard
"""

from datetime import date
from django.contrib.auth import get_user_model
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.notifications.models import (
    EmailCampaign,
    CampaignRecipient,
    RecruitmentEmailTemplate,
    DailyEmailQuotaTracking,
    EmailSuppression,
)
from apps.notifications.quota_service import DailyEmailQuotaService
from apps.notifications.campaign_service import CampaignService
from apps.jobs.models import InstitutionRequirement, RequirementCandidateMatch

User = get_user_model()


class RecruitmentEmailTemplateTests(TestCase):
    """Test suite for recruitment email template functionality."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="admin_templates@sevajobs.in",
            password="testpassword123",
            role="admin",
            is_staff=True,
        )

    def test_canonical_templates_seeded(self):
        """Verify that all 6 recruitment lifecycle templates are present in the database."""
        expected_keys = ["shortlisted", "interviewing", "selected", "joined", "rejected", "general"]
        for key in expected_keys:
            tmpl = RecruitmentEmailTemplate.objects.filter(status_key=key, is_default=True).first()
            self.assertIsNotNone(tmpl, f"Canonical default template missing for status_key '{key}'.")
            self.assertTrue(len(tmpl.subject) > 0, f"Template for '{key}' has empty subject.")
            self.assertTrue(len(tmpl.body_html) > 0, f"Template for '{key}' has empty body.")
            self.assertIn("candidate_name", tmpl.body_html, f"Template for '{key}' lacks candidate_name tag.")

    def test_get_default_template_resolution(self):
        """Test default template lookup and fallback to general for unknown keys."""
        shortlisted_tmpl = RecruitmentEmailTemplate.get_default_template("shortlisted")
        self.assertEqual(shortlisted_tmpl.status_key, "shortlisted")

        interview_alias = RecruitmentEmailTemplate.get_default_template("interview_scheduled")
        self.assertEqual(interview_alias.status_key, "interviewing")

        unknown_tmpl = RecruitmentEmailTemplate.get_default_template("unknown_custom_stage")
        self.assertEqual(unknown_tmpl.status_key, "general")

    def test_template_rendering_with_context(self):
        """Verify merge tag substitution in recruitment templates."""
        tmpl = RecruitmentEmailTemplate.get_default_template("selected")
        context = {
            "candidate_name": "Aarav Sharma",
            "requirement_title": "PGT Mathematics",
            "school_name": "Delhi Public School",
            "location": "Bengaluru",
            "candidate_status": "Selected",
            "support_email": "support@sevajobs.in",
            "unsubscribe_url": "https://sevajobs.in/unsubscribe/test",
        }
        rendered_subject = CampaignService.render_content(body_template=tmpl.subject, context=context)
        rendered_body = CampaignService.render_content(body_template=tmpl.body_html, context=context)

        self.assertIn("Aarav Sharma", rendered_body)
        self.assertIn("PGT Mathematics", rendered_subject)
        self.assertIn("Delhi Public School", rendered_body)
        self.assertNotIn("{{ candidate_name }}", rendered_body)

    def test_save_custom_template_and_reset_to_default(self):
        """Test creating a custom template and restoring canonical defaults."""
        custom = CampaignService.save_as_template(
            status_key="shortlisted",
            name="Custom Physics Shortlist",
            subject="Congratulations! You are shortlisted for Physics at {{ school_name }}",
            body_html="<p>Dear {{ candidate_name }}, custom shortlist text.</p>",
            user=self.user,
            set_as_default=True,
        )
        self.assertTrue(custom.is_default)
        self.assertEqual(custom.status_key, "shortlisted")

        # Current default is now custom
        active_default = RecruitmentEmailTemplate.get_default_template("shortlisted")
        self.assertEqual(active_default.id, custom.id)
        self.assertIn("Custom Physics Shortlist", active_default.name)

        # Reset to canonical default
        reset_tmpl = CampaignService.reset_to_default_template("shortlisted")
        self.assertEqual(reset_tmpl["status_key"], "shortlisted")
        self.assertIn("Shortlisted", reset_tmpl["name"])
        self.assertNotEqual(reset_tmpl["name"], "Custom Physics Shortlist")


class DailyEmailQuotaServiceTests(TestCase):
    """Test suite for daily bulk email quota enforcement, reservations, and reconciliation."""

    def setUp(self):
        # Reset tracking for today's date
        DailyEmailQuotaTracking.objects.filter(date=timezone.now().date()).delete()

    @override_settings(BULK_EMAIL_DAILY_LIMIT=100, BULK_EMAIL_DAILY_TARGET=90, BULK_EMAIL_DAILY_WARNING_THRESHOLD=80)
    def test_initial_quota_state(self):
        """New day starts with zero consumption and full limit available."""
        status = DailyEmailQuotaService.get_quota_status()
        self.assertEqual(status["sent_today"], 0)
        self.assertEqual(status["in_queue"], 0)
        self.assertEqual(status["remaining"], 100)
        self.assertEqual(status["daily_limit"], 100)
        self.assertEqual(status["daily_target"], 90)
        self.assertFalse(status["is_warning"])
        self.assertFalse(status["is_limit_reached"])
        self.assertEqual(status["status"], "normal")

    @override_settings(BULK_EMAIL_DAILY_LIMIT=100, BULK_EMAIL_DAILY_TARGET=90, BULK_EMAIL_DAILY_WARNING_THRESHOLD=80)
    def test_atomic_quota_reservation_success(self):
        """Reserving within available quota succeeds and deducts from remaining capacity."""
        success = DailyEmailQuotaService.reserve_quota(40)
        self.assertTrue(success)

        status = DailyEmailQuotaService.get_quota_status()
        self.assertEqual(status["in_queue"], 40)
        self.assertEqual(status["remaining"], 60)
        self.assertEqual(status["total_consumed"], 40)
        self.assertEqual(status["status"], "normal")

    @override_settings(BULK_EMAIL_DAILY_LIMIT=100, BULK_EMAIL_DAILY_TARGET=90, BULK_EMAIL_DAILY_WARNING_THRESHOLD=80)
    def test_warning_and_target_thresholds(self):
        """Warning state triggers at >=80, target reached triggers at >=90."""
        DailyEmailQuotaService.reserve_quota(82)
        status = DailyEmailQuotaService.get_quota_status()
        self.assertTrue(status["is_warning"])
        self.assertFalse(status["is_target_reached"])
        self.assertEqual(status["status"], "warning")
        self.assertEqual(status["remaining"], 18)

        DailyEmailQuotaService.reserve_quota(10)  # total 92
        status = DailyEmailQuotaService.get_quota_status()
        self.assertTrue(status["is_warning"])
        self.assertTrue(status["is_target_reached"])
        self.assertFalse(status["is_limit_reached"])
        self.assertEqual(status["remaining"], 8)

    @override_settings(BULK_EMAIL_DAILY_LIMIT=100, BULK_EMAIL_DAILY_TARGET=90, BULK_EMAIL_DAILY_WARNING_THRESHOLD=80)
    def test_hard_limit_exceeded_rejected(self):
        """Attempting to exceed the hard limit of 100 emails is rejected."""
        DailyEmailQuotaService.reserve_quota(95)
        # Attempt to reserve 10 more (would be 105 > 100) -> must fail
        rejected = DailyEmailQuotaService.reserve_quota(10)
        self.assertFalse(rejected)

        # Quota remains at 95
        status = DailyEmailQuotaService.get_quota_status()
        self.assertEqual(status["total_consumed"], 95)
        self.assertEqual(status["remaining"], 5)

        # Exact remaining reservation (5) succeeds and reaches hard limit
        accepted = DailyEmailQuotaService.reserve_quota(5)
        self.assertTrue(accepted)
        status = DailyEmailQuotaService.get_quota_status()
        self.assertEqual(status["total_consumed"], 100)
        self.assertEqual(status["remaining"], 0)
        self.assertTrue(status["is_limit_reached"])
        self.assertEqual(status["status"], "limit_reached")

    @override_settings(BULK_EMAIL_DAILY_LIMIT=100)
    def test_release_reserved_quota(self):
        """Cancelled campaigns or suppressed recipients release reservations back to the daily pool."""
        DailyEmailQuotaService.reserve_quota(50)
        self.assertEqual(DailyEmailQuotaService.get_quota_status()["remaining"], 50)

        DailyEmailQuotaService.release_reserved_quota(20)
        status = DailyEmailQuotaService.get_quota_status()
        self.assertEqual(status["in_queue"], 30)
        self.assertEqual(status["remaining"], 70)

    @override_settings(BULK_EMAIL_DAILY_LIMIT=100)
    def test_record_send_and_delivery_lifecycle(self):
        """Recording sends converts reserved into sent; delivery logs webhook confirmations."""
        DailyEmailQuotaService.reserve_quota(30)
        # 25 successful sends, 5 failures
        DailyEmailQuotaService.record_send_success(25)
        DailyEmailQuotaService.record_send_failure(5)

        status = DailyEmailQuotaService.get_quota_status()
        self.assertEqual(status["in_queue"], 0)
        self.assertEqual(status["sent_today"], 25)
        self.assertEqual(status["failed_today"], 5)
        self.assertEqual(status["remaining"], 75)

        # Webhook confirms 20 delivered
        DailyEmailQuotaService.record_delivery_success(20)
        status = DailyEmailQuotaService.get_quota_status()
        self.assertEqual(status["delivered_today"], 20)


class CampaignQuotaIntegrationTests(TestCase):
    """Test campaign creation, launch blocking, and retries under quota restrictions."""

    def setUp(self):
        DailyEmailQuotaTracking.objects.filter(date=timezone.now().date()).delete()
        self.user = User.objects.create_user(
            email="campaign_admin@sevajobs.in",
            password="testpassword123",
            role="admin",
            is_staff=True,
        )
        self.client = Client()
        self.client.force_login(self.user)

        self.requirement = InstitutionRequirement.objects.create(
            institution_name="Delhi Public School",
            phone_number="9876543210",
            subject="Computer Science",
            qualification="B.Tech / MCA",
            teaching_grade="High School (9-10)",
            location="New Delhi",
            posted_by_user=self.user,
        )

        # Create candidates
        self.c1 = User.objects.create_user(email="c1@test.com", password="pw", role="job_seeker", first_name="Candidate", last_name="One")
        self.c2 = User.objects.create_user(email="c2@test.com", password="pw", role="job_seeker", first_name="Candidate", last_name="Two")

        RequirementCandidateMatch.objects.create(
            requirement=self.requirement,
            candidate=self.c1,
            match_score=90,
            status=RequirementCandidateMatch.MatchStatus.SHORTLISTED,
        )
        RequirementCandidateMatch.objects.create(
            requirement=self.requirement,
            candidate=self.c2,
            match_score=85,
            status=RequirementCandidateMatch.MatchStatus.SHORTLISTED,
        )

    @override_settings(BULK_EMAIL_DAILY_LIMIT=100)
    def test_launch_campaign_blocks_when_quota_exhausted(self):
        """Attempting to launch a campaign when remaining quota is insufficient raises ValueError."""
        # Pre-consume 99 quota units
        DailyEmailQuotaService.reserve_quota(99)

        campaign = CampaignService.create_campaign(
            requirement=self.requirement,
            created_by=self.user,
            name="Quota Block Test Campaign",
            subject="Test Subject",
            body_html="<p>Body text</p>",
            selected_statuses=["all"],
        )
        self.assertEqual(campaign.total_recipients, 2)

        # Launching with 2 recipients when only 1 remaining must fail
        with self.assertRaises(ValueError) as ctx:
            CampaignService.launch_campaign(str(campaign.id))

        self.assertIn("Daily email quota exceeded", str(ctx.exception))
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, EmailCampaign.Status.DRAFT)

    @override_settings(BULK_EMAIL_DAILY_LIMIT=100)
    def test_retry_failed_recipients_checks_quota(self):
        """Retrying failed recipients verifies quota before re-queueing."""
        campaign = CampaignService.create_campaign(
            requirement=self.requirement,
            created_by=self.user,
            name="Retry Quota Campaign",
            subject="Test",
            body_html="<p>Body</p>",
            selected_statuses=["all"],
        )
        # Mark recipient as failed
        recipient = campaign.recipients.first()
        recipient.status = CampaignRecipient.RecipientStatus.FAILED
        recipient.attempt_count = 1
        recipient.last_error = "Rate limit"
        recipient.save()
        campaign.status = EmailCampaign.Status.PARTIALLY_FAILED
        campaign.save()

        # Exhaust quota completely
        DailyEmailQuotaService.reserve_quota(100)

        # Retry must fail due to quota
        with self.assertRaises(ValueError) as ctx:
            CampaignService.retry_failed_recipients(str(campaign.id), actor=self.user)
        self.assertIn("Insufficient daily quota", str(ctx.exception))

        # Release some quota and retry successfully
        DailyEmailQuotaService.release_reserved_quota(10)
        retried = CampaignService.retry_failed_recipients(str(campaign.id), actor=self.user)
        self.assertEqual(retried, 1)

        recipient.refresh_from_db()
        self.assertEqual(recipient.status, CampaignRecipient.RecipientStatus.QUEUED)


class QuotaAndTemplatesAPIViewsTests(TestCase):
    """Test REST API endpoint and Admin UI dashboard views."""

    def setUp(self):
        DailyEmailQuotaTracking.objects.filter(date=timezone.now().date()).delete()
        self.admin = User.objects.create_user(
            email="admin_api@sevajobs.in",
            password="testpassword123",
            role="admin",
            is_staff=True,
            is_superuser=True,
        )
        self.client = Client()
        self.client.force_login(self.admin)
        session = self.client.session
        session["current_role_scope"] = "admin"
        session.save()
        self.client.cookies["sessionid_admin"] = session.session_key

        self.requirement = InstitutionRequirement.objects.create(
            institution_name="St. Xavier's School",
            phone_number="9876543211",
            subject="English Literature",
            qualification="M.A. English, B.Ed",
            teaching_grade="High School (9-10)",
            location="Mumbai",
            posted_by_user=self.admin,
        )

    def test_quota_status_api_endpoint(self):
        """Test the lightweight JSON endpoint used by the persistent navbar indicator."""
        url = reverse("notifications:email-quota-status")
        resp = self.client.get(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertEqual(data["status"], "success")
        self.assertIn("sent_today", data)
        self.assertIn("in_queue", data)
        self.assertIn("remaining", data)
        self.assertIn("daily_limit", data)
        self.assertIn("daily_target", data)
        self.assertIn("is_limit_reached", data)

    def test_requirement_bulk_email_ajax_actions(self):
        """Test template loading, saving, and resetting via RequirementBulkEmailView."""
        url = reverse("jobs:requirement-bulk-email", kwargs={"pk": self.requirement.pk})

        # 1. Load template
        resp = self.client.post(url, {"action": "load_template", "status_key": "shortlisted"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["template"]["status_key"], "shortlisted")

        # 2. Save custom template
        resp = self.client.post(
            url,
            {
                "action": "save_template",
                "status_key": "shortlisted",
                "name": "Custom Shortlist English",
                "subject": "Custom Subject for English",
                "body_html": "<p>Custom content</p>",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "success")

        # 3. Reset template to canonical default
        resp = self.client.post(url, {"action": "reset_template", "status_key": "shortlisted"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "success")

    def test_admin_email_quota_dashboard_view(self):
        """Verify Admin Email Quota & Logs Dashboard renders cleanly with metrics, tabs, and logs."""
        url = reverse("admin-panel:email-quota")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Email Quota &amp; Delivery Health")
        self.assertContains(resp, "Recent Bulk Email Campaigns")
        self.assertContains(resp, "Failed Delivery Audit")
        self.assertContains(resp, "Recruitment Status Templates")

        # Test Sync & Reconcile POST action
        post_resp = self.client.post(url, {"action": "reconcile_quota"})
        self.assertEqual(post_resp.status_code, 302)
        self.assertRedirects(post_resp, url)
