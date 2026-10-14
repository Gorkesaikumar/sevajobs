"""Comprehensive integration and unit tests for SevaJobs Bulk Job Alerts."""

from datetime import timedelta
import json
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import JobSeekerProfile, User
from apps.jobs.models import Job, StaffJob, InstitutionRequirement
from apps.jobs.job_alert_matching_service import CandidateJobAlertMatchingService
from apps.notifications.default_templates import DEFAULT_JOB_ALERT_TEMPLATE, FIVE_ALERT_TEMPLATES
from apps.notifications.job_alert_service import JobAlertCampaignService
from apps.notifications.models import (
    CandidateJobAlertDelivery,
    EmailSuppression,
    JobAlertCampaign,
    JobAlertRecipient,
)
from apps.notifications.quota_service import DailyEmailQuotaService
from apps.notifications.tasks import send_bulk_job_alerts_task, send_daily_job_alerts_digest
from apps.notifications.unsubscribe_service import (
    JobAlertPreferenceService,
    UnsubscribeService,
)
from apps.recruiters.models import Company, RecruiterProfile


class JobAlertCampaignServiceTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin_user",
            email="admin@sevajobs.in",
            password="testpassword123",
            role="admin",
        )
        self.candidate = User.objects.create_user(
            username="candidate1",
            email="candidate1@example.com",
            password="testpassword123",
            first_name="Smrithi",
            last_name="Rajan",
            role="job_seeker",
            is_active=True,
        )
        self.profile = JobSeekerProfile.objects.create(
            user=self.candidate,
            designation="English Teacher",
            subject="English",
            preferred_location="Chennai",
            experience_years=3,
            job_alerts_enabled=True,
        )
        # Create an approved active job
        self.company = Company.objects.create(name="St. Jude's Academy", location="Chennai")
        self.recruiter = RecruiterProfile.objects.create(user=self.admin, company=self.company)
        self.job = Job.objects.create(
            title="English Teacher (PGT)",
            slug="english-teacher-pgt-01",
            company=self.company,
            recruiter=self.recruiter,
            location="Chennai",
            experience_level=Job.ExperienceLevel.THREE_SIX_YEARS,
            status=Job.Status.ACTIVE,
            approval_status=Job.ApprovalStatus.APPROVED,
            is_active=True,
            deadline=timezone.now().date() + timedelta(days=30),
        )

    def test_sanitize_subject_strips_crlf(self):
        raw = "Urgent Vacancies\r\nBcc: victim@example.com\nNew Line"
        cleaned = JobAlertCampaignService.sanitize_subject(raw)
        self.assertNotIn("\r", cleaned)
        self.assertNotIn("\n", cleaned)
        self.assertEqual(cleaned, "Urgent Vacancies Bcc: victim@example.com New Line")

    def test_sanitize_html_removes_scripts_and_events(self):
        raw = "<p>Hello</p><script>alert('hack')</script><a href='javascript:void(0)' onclick='evil()'>Click</a>"
        cleaned = JobAlertCampaignService.sanitize_html(raw)
        self.assertNotIn("<script", cleaned)
        self.assertNotIn("javascript:", cleaned)
        self.assertNotIn("onclick", cleaned)
        self.assertIn("<p>Hello</p>", cleaned)

    def test_render_content_substitutes_merge_tags(self):
        template = "Dear {{ candidate_name }}, we found roles in {{ candidate_subject }}!"
        context = {"candidate_name": "Smrithi", "candidate_subject": "English"}
        result = JobAlertCampaignService.render_content(body_template=template, context=context)
        self.assertEqual(result, "Dear Smrithi, we found roles in English!")

    def test_create_campaign_and_snapshot_recipients(self):
        campaign = JobAlertCampaignService.create_campaign(
            created_by=self.admin,
            name="Test English Campaign",
            subject="New English Teaching Vacancies",
            body_html="<p>Jobs: {{ matching_jobs }}</p>",
            targeting_criteria={"subject": "English"},
        )
        self.assertEqual(campaign.status, JobAlertCampaign.Status.DRAFT)
        self.assertEqual(campaign.total_recipients, 1)
        self.assertEqual(campaign.recipients.count(), 1)
        recipient = campaign.recipients.first()
        self.assertEqual(recipient.email, "candidate1@example.com")
        self.assertEqual(recipient.matched_job_count, 1)
        self.assertEqual(recipient.status, JobAlertRecipient.RecipientStatus.PENDING)

    def test_launch_and_cancel_campaign_manages_quota(self):
        DailyEmailQuotaService.reconcile_today()
        initial_status = DailyEmailQuotaService.get_quota_status()

        campaign = JobAlertCampaignService.create_campaign(
            created_by=self.admin,
            name="Quota Test Campaign",
            subject="Job Alerts",
            body_html="<p>Jobs</p>",
            targeting_criteria={"subject": "English"},
        )
        self.assertEqual(campaign.total_recipients, 1)

        # Launch campaign
        with patch("apps.notifications.tasks.send_bulk_job_alerts_task.delay") as mock_delay:
            success = JobAlertCampaignService.launch_campaign(str(campaign.id))
            self.assertTrue(success)

        campaign.refresh_from_db()
        self.assertEqual(campaign.status, JobAlertCampaign.Status.QUEUED)
        post_launch_status = DailyEmailQuotaService.get_quota_status()
        self.assertEqual(post_launch_status["in_queue"], initial_status["in_queue"] + 1)

        # Cancel campaign
        cancelled = JobAlertCampaignService.cancel_campaign(str(campaign.id))
        self.assertTrue(cancelled)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, JobAlertCampaign.Status.CANCELLED)

        post_cancel_status = DailyEmailQuotaService.get_quota_status()
        self.assertEqual(post_cancel_status["in_queue"], initial_status["in_queue"])


class JobAlertPreferenceServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="candidate_pref",
            email="pref_test@example.com",
            password="testpassword123",
            role="job_seeker",
        )
        self.profile = JobSeekerProfile.objects.create(
            user=self.user,
            job_alerts_enabled=True,
        )

    def test_generate_and_verify_token(self):
        token = JobAlertPreferenceService.generate_token("pref_test@example.com")
        email = JobAlertPreferenceService.verify_token(token)
        self.assertEqual(email, "pref_test@example.com")

    def test_tampered_token_rejected(self):
        token = JobAlertPreferenceService.generate_token("pref_test@example.com")
        tampered = token + "xyz"
        self.assertIsNone(JobAlertPreferenceService.verify_token(tampered))

    def test_update_preference(self):
        self.assertTrue(self.profile.job_alerts_enabled)
        updated = JobAlertPreferenceService.update_preference("pref_test@example.com", False)
        self.assertTrue(updated)
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.job_alerts_enabled)


class JobAlertTaskAndWebhookTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin_wh",
            email="admin_wh@sevajobs.in",
            password="testpassword123",
            role="admin",
        )
        self.candidate = User.objects.create_user(
            username="candidate_task",
            email="candidate_task@example.com",
            password="testpassword123",
            role="job_seeker",
            is_active=True,
        )
        self.profile = JobSeekerProfile.objects.create(
            user=self.candidate,
            designation="Teacher",
            subject="English",
            job_alerts_enabled=True,
        )
        self.company = Company.objects.create(name="St. Jude's Academy", location="Chennai")
        self.recruiter = RecruiterProfile.objects.create(user=self.admin, company=self.company)
        self.job = Job.objects.create(
            title="English Teacher",
            slug="english-teacher-task-02",
            company=self.company,
            recruiter=self.recruiter,
            location="Chennai",
            experience_level=Job.ExperienceLevel.THREE_SIX_YEARS,
            status=Job.Status.ACTIVE,
            approval_status=Job.ApprovalStatus.APPROVED,
            is_active=True,
            deadline=timezone.now().date() + timedelta(days=30),
        )

    @patch("django.core.mail.EmailMultiAlternatives.send", return_value=1)
    def test_send_bulk_job_alerts_task_delivers_and_records(self, mock_send):
        campaign = JobAlertCampaignService.create_campaign(
            created_by=self.admin,
            name="Delivery Task Test",
            subject="Matching Jobs Found",
            body_html="<p>Jobs: {{ matching_jobs }}</p>",
            targeting_criteria={"subject": "English"},
        )
        # Transition to QUEUED
        campaign.transition_to(JobAlertCampaign.Status.QUEUED)
        campaign.recipients.update(status=JobAlertRecipient.RecipientStatus.QUEUED)

        # Run task directly
        result = send_bulk_job_alerts_task(str(campaign.id))
        self.assertEqual(result["sent"], 1)

        campaign.refresh_from_db()
        self.assertEqual(campaign.status, JobAlertCampaign.Status.COMPLETED)
        self.assertEqual(campaign.sent_count, 1)

        recipient = campaign.recipients.first()
        self.assertEqual(recipient.status, JobAlertRecipient.RecipientStatus.SENT)

        # Verify CandidateJobAlertDelivery record was created
        delivery = CandidateJobAlertDelivery.objects.filter(candidate=self.candidate, job_id=str(self.job.id)).first()
        self.assertIsNotNone(delivery)

    @override_settings(RESEND_WEBHOOK_SECRET="whsec_dummy_test_secret")
    @patch("apps.notifications.resend_webhook.ResendWebhookView._verify_signature")
    def test_resend_webhook_updates_job_alert_recipient(self, mock_verify):
        campaign = JobAlertCampaign.objects.create(
            name="Webhook Test",
            created_by=self.admin,
            subject="Subject",
            body_html="<p>Body</p>",
            status=JobAlertCampaign.Status.COMPLETED,
            sent_count=1,
        )
        recipient = JobAlertRecipient.objects.create(
            campaign=campaign,
            candidate=self.candidate,
            recipient_name="Smrithi",
            email="candidate_task@example.com",
            status=JobAlertRecipient.RecipientStatus.SENT,
            provider_message_id="resend_msg_test_99",
            sent_at=timezone.now(),
        )

        client = Client()
        delivered_payload = {
            "type": "email.delivered",
            "created_at": "2026-10-14T10:00:00.000Z",
            "data": {
                "email_id": "resend_msg_test_99",
                "to": ["candidate_task@example.com"],
            },
        }
        mock_verify.return_value = delivered_payload

        # Resend webhook endpoint
        resp = client.post(
            reverse("notifications:resend-webhook"),
            data=json.dumps(delivered_payload),
            content_type="application/json",
            HTTP_SVIX_ID="test_evt_101",
        )
        self.assertEqual(resp.status_code, 200)

        recipient.refresh_from_db()
        self.assertEqual(recipient.status, JobAlertRecipient.RecipientStatus.DELIVERED)
        self.assertIsNotNone(recipient.delivered_at)

        campaign.refresh_from_db()
        self.assertEqual(campaign.delivered_count, 1)


class AdminJobAlertViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(
            username="admin_view_user",
            email="admin_view@sevajobs.in",
            password="testpassword123",
            role="admin",
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(self.admin)
        session = self.client.session
        session["current_role_scope"] = "admin"
        session.save()
        self.client.cookies["sessionid_admin"] = session.session_key

        self.candidate = User.objects.create_user(
            username="cand_view",
            email="cand_view@example.com",
            password="testpassword123",
            role="job_seeker",
            is_active=True,
        )
        self.profile = JobSeekerProfile.objects.create(
            user=self.candidate,
            designation="Teacher",
            subject="English",
            preferred_location="Chennai",
            job_alerts_enabled=True,
        )

    def test_bulk_job_alerts_get_renders_wizard(self):
        resp = self.client.get(reverse("admin-panel:bulk-job-alerts"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Bulk Job Alerts")
        self.assertContains(resp, "Target Audience")
        self.assertContains(resp, "Select Matching Strategy")

    def test_calculate_audience_ajax(self):
        payload = {
            "action": "calculate_audience",
            "subject": "English",
            "matching_strategy": "auto",
        }
        resp = self.client.post(
            reverse("admin-panel:bulk-job-alerts"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("total_job_seekers_found", data)
        self.assertIn("candidates", data)

    def test_preview_email_ajax(self):
        payload = {
            "action": "preview_email",
            "candidate_id": str(self.candidate.id),
            "subject": "Roles for {{ candidate_name }}",
            "body_html": "<p>Hello {{ candidate_name }}</p>",
            "matching_strategy": "auto",
        }
        resp = self.client.post(
            reverse("admin-panel:bulk-job-alerts"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("rendered_html", data)
        self.assertIn("rendered_subject", data)

    def test_job_alert_campaigns_list_view(self):
        campaign = JobAlertCampaign.objects.create(
            name="History Campaign",
            created_by=self.admin,
            subject="Subject",
            body_html="<p>Body</p>",
        )
        resp = self.client.get(reverse("admin-panel:job-alert-campaigns"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "History Campaign")

    def test_job_alert_campaign_detail_view(self):
        campaign = JobAlertCampaign.objects.create(
            name="Detail Campaign",
            created_by=self.admin,
            subject="Subject",
            body_html="<p>Body</p>",
        )
        resp = self.client.get(reverse("admin-panel:job-alert-campaign-detail", kwargs={"campaign_id": campaign.id}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Detail Campaign")


class FiveAlertTypesTests(TestCase):
    """Integration tests for all 5 SevaJobs Alert Types, Beat schedule, and audience matching."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin_five",
            email="admin_five@sevajobs.in",
            password="testpassword123",
            role="admin",
            is_staff=True,
            is_superuser=True,
        )
        self.client = Client()
        self.client.force_login(self.admin)
        session = self.client.session
        session["current_role_scope"] = "admin"
        session["admin_user_id"] = str(self.admin.id)
        session.save()
        self.client.cookies["sessionid_admin"] = session.session_key

        self.candidate = User.objects.create_user(
            username="teacher_smrithi",
            email="smrithi@example.com",
            first_name="Smrithi",
            last_name="Rajan",
            role="job_seeker",
            is_active=True,
        )
        self.profile = JobSeekerProfile.objects.create(
            user=self.candidate,
            designation="English Teacher",
            subject="English",
            preferred_location="Chennai",
            experience_years=4,
            job_alerts_enabled=True,
        )

        self.recruiter_user = User.objects.create_user(
            username="school_recruiter",
            email="recruiter@chennaischool.org",
            first_name="Anand",
            last_name="Kumar",
            role="recruiter",
            is_active=True,
        )
        self.company = Company.objects.create(
            name="Chennai Model School",
            location="Chennai",
            city="Chennai",
            institute_type=Company.InstituteType.SCHOOL,
            is_verified=True,
        )
        self.recruiter_profile = RecruiterProfile.objects.create(
            user=self.recruiter_user,
            company=self.company,
        )

    def test_toggle_schedule_endpoint(self):
        # 1. Toggle to opposite
        resp = self.client.post(
            reverse("admin-panel:bulk-job-alerts"),
            data=json.dumps({"action": "toggle_schedule"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        new_state = data["is_enabled"]
        self.assertEqual(JobAlertCampaignService.is_daily_schedule_enabled(), new_state)

        # 2. Toggle back
        resp2 = self.client.post(
            reverse("admin-panel:bulk-job-alerts"),
            data=json.dumps({"action": "toggle_schedule"}),
            content_type="application/json",
        )
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.json()
        self.assertEqual(data2["is_enabled"], not new_state)

    def test_daily_digest_beat_task_skips_when_schedule_paused(self):
        JobAlertCampaignService.set_daily_schedule_enabled(False)
        result = send_daily_job_alerts_digest()
        self.assertEqual(result["status"], "paused_by_admin")

        # Resume schedule
        JobAlertCampaignService.set_daily_schedule_enabled(True)

    def test_walkin_alert_workflow(self):
        walkin = Job.objects.create(
            title="Walk-in: High School English Faculty",
            slug="walkin-hs-english",
            company=self.company,
            recruiter=self.recruiter_profile,
            location="Chennai",
            status=Job.Status.ACTIVE,
            approval_status=Job.ApprovalStatus.APPROVED,
            is_active=True,
            is_walkin=True,
            walkin_start_date=timezone.now().date(),
            walkin_end_date=timezone.now().date() + timedelta(days=2),
            walkin_time="9:30 AM to 1:00 PM",
            walkin_venue="Administrative Auditorium, Chennai Model School Campus",
            walkin_contact_instructions="Carry 2 copies of CV and original degree certificates.",
        )

        eval_result = CandidateJobAlertMatchingService.evaluate_walkin_audience(
            walkin_job_id=str(walkin.id),
            filters={"subject": "English"},
        )
        self.assertGreaterEqual(eval_result["eligible_candidates_count"], 1)

        campaign = JobAlertCampaignService.create_campaign(
            created_by=self.admin,
            name="Urgent English Walk-in Alert",
            subject="Urgent Walk-in: English Teacher Needed",
            body_html="<p>Venue: {{ walkin_venue }}</p><p>{{ walkin_attendance_note }}</p>",
            alert_type=JobAlertCampaign.AlertType.WALKIN_ALERT,
            walkin_job_id=str(walkin.id),
            candidate_ids=[str(self.candidate.id)],
        )
        self.assertEqual(campaign.alert_type, JobAlertCampaign.AlertType.WALKIN_ALERT)
        self.assertEqual(campaign.priority, 2)
        self.assertEqual(campaign.recipients.count(), 1)

        recip = campaign.recipients.first()
        context = JobAlertCampaignService.build_context_for_recipient(campaign, recip)
        self.assertIn("Administrative Auditorium", context["walkin_venue"])
        self.assertIn("without prior application", context["walkin_attendance_note"])

    def test_employer_alert_workflow(self):
        eval_result = CandidateJobAlertMatchingService.evaluate_employer_audience(filters={"location": "Chennai"})
        self.assertGreaterEqual(eval_result["eligible_candidates_count"], 1)

        campaign = JobAlertCampaignService.create_campaign(
            created_by=self.admin,
            name="Urgent Faculty Requirement Hiring Drive",
            subject="Find Certified Teachers for Your Institution",
            body_html="<p>Post jobs: <a href='{{ post_job_url }}'>Post Job</a></p>",
            alert_type=JobAlertCampaign.AlertType.EMPLOYER_ALERT,
            candidate_ids=[str(self.recruiter_user.id)],
        )
        self.assertEqual(campaign.alert_type, JobAlertCampaign.AlertType.EMPLOYER_ALERT)
        self.assertEqual(campaign.priority, 5)
        self.assertEqual(campaign.recipients.count(), 1)

        recip = campaign.recipients.first()
        self.assertEqual(recip.recipient_type, JobAlertRecipient.RecipientType.EMPLOYER)
        context = JobAlertCampaignService.build_context_for_recipient(campaign, recip)
        self.assertIn("/jobs/post/", context["post_job_url"])
        self.assertIn("/requirements/create/", context["submit_requirement_url"])

    def test_requirement_alert_workflow(self):
        req = InstitutionRequirement.objects.create(
            institution_name="Chennai Model School",
            phone_number="9876543210",
            posted_by_user=self.recruiter_user,
            subject="English",
            qualification="B.Ed",
            teaching_grade=InstitutionRequirement.TeachingGrade.TGT,
            positions_count=2,
            min_experience_years=2,
            location="Chennai",
            status=InstitutionRequirement.RequirementStatus.ASSIGNED,
        )

        eval_result = CandidateJobAlertMatchingService.evaluate_requirement_audience(
            requirement_id=str(req.id),
            filters={"subject": "English"},
        )
        self.assertGreaterEqual(eval_result["eligible_candidates_count"], 1)

        campaign = JobAlertCampaignService.create_campaign(
            created_by=self.admin,
            name="VIP Requirement: English Teacher",
            subject="Exclusive Opening: {{ subject }} Faculty",
            body_html="<p>Institution: {{ institution_name }}</p>",
            alert_type=JobAlertCampaign.AlertType.REQUIREMENT_ALERT,
            requirement_id=str(req.id),
            candidate_ids=[str(self.candidate.id)],
        )
        self.assertEqual(campaign.alert_type, JobAlertCampaign.AlertType.REQUIREMENT_ALERT)
        self.assertEqual(campaign.priority, 3)
        self.assertEqual(campaign.recipients.count(), 1)

        recip = campaign.recipients.first()
        context = JobAlertCampaignService.build_context_for_recipient(campaign, recip)
        self.assertEqual(context["institution_name"], "Chennai Model School")
        self.assertEqual(context["subject"], "English")

    def test_walkin_alert_without_mandatory_public_jobs(self):
        """
        Verify that Walk-in Alert does NOT require matching public jobs or applications.
        Eligible candidates qualify based directly on their profile and walk-in details.
        """
        # Delete all public jobs to ensure database contains zero public jobs
        Job.objects.filter(is_walkin=False).delete()
        StaffJob.objects.all().delete()
        self.assertEqual(Job.objects.filter(is_walkin=False).count(), 0)

        # Create a walk-in in Hyderabad (different location from candidate's Chennai)
        walkin = Job.objects.create(
            title="PGT English Teacher",
            slug="pgt-english-hyderabad-walkin",
            company=self.company,
            recruiter=self.recruiter_profile,
            location="Hyderabad",
            city="Hyderabad",
            status=Job.Status.ACTIVE,
            approval_status=Job.ApprovalStatus.APPROVED,
            is_active=True,
            is_walkin=True,
            walkin_start_date=timezone.now().date(),
            walkin_end_date=timezone.now().date() + timedelta(days=5),
            walkin_time="10:00 AM - 4:00 PM",
            walkin_venue="Ram Suns Public School, Hyderabad",
            walkin_contact_instructions="Bring 2 copies of CV and certificates.",
        )

        # Candidate is English Teacher in Chennai with 3 yrs experience
        eval_result = CandidateJobAlertMatchingService.evaluate_walkin_audience(
            walkin_job_id=str(walkin.id),
            filters={},  # No filters specified by admin
            dedup_window_days=14,
        )

        # Profile-based qualification must succeed without public jobs
        self.assertGreaterEqual(eval_result["eligible_candidates_count"], 1)
        self.assertEqual(eval_result["no_matching_jobs_count"], 0)
        self.assertGreaterEqual(eval_result["matching_profiles_count"], 1)

        candidate_review = next(c for c in eval_result["candidates_review"] if c["candidate_id"] == str(self.candidate.id))
        self.assertTrue(candidate_review["is_eligible"])
        self.assertEqual(candidate_review["matched_job_count"], 1)
        self.assertEqual(candidate_review["matched_jobs"][0]["title"], "PGT English Teacher")
        self.assertEqual(candidate_review["matched_jobs"][0]["job_type"], "Walk-in Interview")

        # Create campaign and dispatch
        campaign = JobAlertCampaignService.create_campaign(
            created_by=self.admin,
            name="Urgent Hyderabad English Walk-in",
            subject="Urgent Walk-in: PGT English Teacher",
            body_html="<p>Venue: {{ walkin_venue }}</p>",
            alert_type=JobAlertCampaign.AlertType.WALKIN_ALERT,
            walkin_job_id=str(walkin.id),
            candidate_ids=[str(self.candidate.id)],
        )
        self.assertEqual(campaign.recipients.count(), 1)
        recipient = campaign.recipients.first()
        self.assertEqual(recipient.matched_job_count, 1)

        # Launch campaign
        DailyEmailQuotaService.reconcile_today()
        JobAlertCampaignService.launch_campaign(str(campaign.id))

        with patch("apps.notifications.tasks.get_connection") as mock_conn:
            mock_backend = MagicMock()
            mock_conn.return_value = mock_backend
            mock_backend.send_messages.return_value = 1
            res = send_bulk_job_alerts_task(str(campaign.id))

        campaign.refresh_from_db()
        self.assertEqual(campaign.status, JobAlertCampaign.Status.COMPLETED)
        self.assertEqual(campaign.sent_count, 1)

        # Delivery record created with job_type=walkin
        delivery_exists = CandidateJobAlertDelivery.objects.filter(
            candidate=self.candidate,
            job_id=walkin.id,
            job_type=CandidateJobAlertDelivery.JobType.WALKIN,
        ).exists()
        self.assertTrue(delivery_exists)

        # Next evaluation within dedup window: candidate excluded as duplicate
        eval_dedup = CandidateJobAlertMatchingService.evaluate_walkin_audience(
            walkin_job_id=str(walkin.id),
            filters={},
            dedup_window_days=14,
        )
        cand_dedup = next(c for c in eval_dedup["candidates_review"] if c["candidate_id"] == str(self.candidate.id))
        self.assertFalse(cand_dedup["is_eligible"])
        self.assertIn("already delivered", cand_dedup["exclusion_reason"])

        # With dedup disabled (0 days), candidate is eligible again
        eval_no_dedup = CandidateJobAlertMatchingService.evaluate_walkin_audience(
            walkin_job_id=str(walkin.id),
            filters={"dedup_window_days": 0},
            dedup_window_days=0,
        )
        cand_no_dedup = next(c for c in eval_no_dedup["candidates_review"] if c["candidate_id"] == str(self.candidate.id))
        self.assertTrue(cand_no_dedup["is_eligible"])

    def test_walkin_audience_subject_mismatch_guard(self):
        """
        Verify that a candidate specializing in Mathematics does NOT qualify
        for an English Teacher walk-in.
        """
        math_cand = User.objects.create_user(
            username="math_teacher_99",
            email="math99@example.com",
            password="testpassword123",
            role="job_seeker",
            is_active=True,
        )
        JobSeekerProfile.objects.create(
            user=math_cand,
            designation="Mathematics Teacher",
            subject="Mathematics",
            experience_years=5,
            job_alerts_enabled=True,
        )

        walkin = Job.objects.create(
            title="PGT English Teacher",
            company=self.company,
            recruiter=self.recruiter_profile,
            location="Chennai",
            status=Job.Status.ACTIVE,
            approval_status=Job.ApprovalStatus.APPROVED,
            is_active=True,
            is_walkin=True,
            walkin_start_date=timezone.now().date(),
        )

        eval_result = CandidateJobAlertMatchingService.evaluate_walkin_audience(
            walkin_job_id=str(walkin.id),
            filters={},
        )
        math_review = next(c for c in eval_result["candidates_review"] if c["candidate_id"] == str(math_cand.id))
        self.assertFalse(math_review["is_eligible"])
        self.assertIn("Subject conflict", math_review["exclusion_reason"])


class PreviewEmailEndpointTests(TestCase):
    """Ensure preview_email renders personalized preview cleanly without 500 errors across all 5 alert types."""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(
            username="preview_admin",
            email="admin_preview@sevajobs.in",
            password="testpassword123",
            role="admin",
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(self.admin)
        session = self.client.session
        session["current_role_scope"] = "admin"
        session.save()
        self.client.cookies["sessionid_admin"] = session.session_key
        self.company = Company.objects.create(name="St. Jude's International School", location="Chennai")
        self.recruiter = RecruiterProfile.objects.create(user=self.admin, company=self.company)
        self.walkin_job = Job.objects.create(
            title="PGT English Teacher",
            company=self.company,
            recruiter=self.recruiter,
            location="Chennai",
            status=Job.Status.ACTIVE,
            approval_status=Job.ApprovalStatus.APPROVED,
            is_active=True,
            is_walkin=True,
            walkin_start_date=timezone.now().date(),
            walkin_venue="Main Campus Auditorium, Chennai",
        )
        self.url = reverse("admin-panel:bulk-job-alerts")

    def test_preview_email_walkin_alert_with_job_id(self):
        payload = {
            "action": "preview_email",
            "alert_type": "walkin_alert",
            "walkin_job_id": str(self.walkin_job.id),
            "candidate_id": "",
            "subject": "",
            "body_html": "",
        }
        resp = self.client.post(self.url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("PGT English Teacher", data["rendered_subject"])
        self.assertIn("St. Jude's International School", data["rendered_subject"])
        self.assertIn("Main Campus Auditorium", data["rendered_html"])

    def test_preview_email_walkin_alert_without_job_id(self):
        payload = {
            "action": "preview_email",
            "alert_type": "walkin_alert",
            "walkin_job_id": "",
            "candidate_id": "",
            "subject": "",
            "body_html": "",
        }
        resp = self.client.post(self.url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertNotIn("{{", data["rendered_subject"])

    def test_preview_email_all_five_types(self):
        for alert_type in ["daily_digest", "interview_alert", "walkin_alert", "employer_alert", "requirement_alert"]:
            payload = {
                "action": "preview_email",
                "alert_type": alert_type,
                "walkin_job_id": str(self.walkin_job.id),
                "candidate_id": "",
                "subject": "",
                "body_html": "",
            }
            resp = self.client.post(self.url, data=json.dumps(payload), content_type="application/json")
            self.assertEqual(resp.status_code, 200, f"Failed for {alert_type}")
            data = resp.json()
            self.assertEqual(data["status"], "success", f"Status failed for {alert_type}")
            self.assertTrue(len(data["rendered_html"]) > 100)
            self.assertNotIn("{{", data["rendered_subject"])


