"""
Automated unit and integration tests for SevaJobs Admin Walk-in Management Module.
Verifies walk-in creation, editing, validation rules, lifecycle status transitions,
candidate match count evaluation, and integration with Bulk Job Alerts.
"""

from datetime import timedelta
import json
from unittest.mock import patch

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import AuditLog, JobSeekerProfile, User
from apps.jobs.models import Job
from apps.jobs.job_alert_matching_service import CandidateJobAlertMatchingService
from apps.recruiters.models import Company, RecruiterProfile


class AdminWalkInManagementTests(TestCase):
    """Test suite covering Walk-in Management in Admin Dashboard."""

    def setUp(self):
        # 1. Admin user with admin role scope
        self.admin = User.objects.create_superuser(
            username="admin_walkin",
            email="admin_walkin@sevajobs.in",
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

        # 2. Registered Company
        self.company = Company.objects.create(
            name="Delhi Public School, Chennai",
            location="Chennai, Tamil Nadu",
            city="Chennai",
            address="100 Mount Road, Guindy, Chennai",
            phone="9876543210",
            contact_person_name="Principal Dr. S. Sharma",
        )

        # 3. Candidate Profile for testing matching
        self.candidate = User.objects.create_user(
            username="math_teacher",
            email="math_teacher@example.com",
            password="testpassword123",
            first_name="Ravi",
            last_name="Kumar",
            role="job_seeker",
            is_active=True,
        )
        self.profile = JobSeekerProfile.objects.create(
            user=self.candidate,
            designation="Mathematics Teacher",
            subject="Mathematics",
            preferred_location="Chennai",
            experience_years=3,
            job_alerts_enabled=True,
        )

    def test_walkin_list_view_renders_successfully(self):
        """Walk-in Management page renders with 200, metrics, and sidebar link."""
        resp = self.client.get(reverse("admin-panel:walk-ins"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Walk-in Management")
        self.assertContains(resp, "+ Create Walk-in")
        self.assertContains(resp, "Total Walk-ins")
        self.assertContains(resp, "Published &amp; Active")
        self.assertContains(resp, "Happening / Upcoming")
        self.assertContains(resp, "Drafts / Inactive")

    def test_create_walkin_as_draft(self):
        """Admin can create a walk-in vacancy and save as Draft."""
        start_date = timezone.now().date() + timedelta(days=2)
        payload = {
            "title": "PGT Mathematics Teacher",
            "company": str(self.company.id),
            "subject": "Mathematics",
            "walkin_start_date": start_date.strftime("%Y-%m-%d"),
            "walkin_end_date": start_date.strftime("%Y-%m-%d"),
            "walkin_time": "9:30 AM - 1:00 PM",
            "walkin_venue": "Campus Administrative Block, Room 102",
            "walkin_contact_instructions": "Bring 2 CVs and original certificates.",
            "location": "Chennai, Tamil Nadu",
            "vacancies": 2,
            "salary_min": 30000,
            "salary_max": 45000,
            "action": "draft",
        }

        resp = self.client.post(reverse("admin-panel:walk-in-create"), data=payload)
        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, reverse("admin-panel:walk-ins"))

        job = Job.objects.filter(title="PGT Mathematics Teacher", is_walkin=True).first()
        self.assertIsNotNone(job)
        self.assertEqual(job.status, Job.Status.DRAFT)
        self.assertEqual(job.approval_status, Job.ApprovalStatus.PENDING)
        self.assertTrue(job.is_walkin)
        self.assertEqual(job.company, self.company)
        self.assertEqual(job.metadata.get("subject"), "Mathematics")
        self.assertEqual(job.metadata.get("walkin_status"), "draft")

        # Draft walk-in should NOT appear in active public walk-in vacancies
        active_walkins = CandidateJobAlertMatchingService.get_walkin_vacancies()
        active_ids = [w["id"] for w in active_walkins]
        self.assertNotIn(str(job.id), active_ids)

    def test_create_walkin_as_published(self):
        """Admin can create and publish a walk-in vacancy immediately."""
        start_date = timezone.now().date() + timedelta(days=1)
        end_date = start_date + timedelta(days=1)
        payload = {
            "title": "Senior Physics Faculty",
            "company": str(self.company.id),
            "subject": "Physics",
            "walkin_start_date": start_date.strftime("%Y-%m-%d"),
            "walkin_end_date": end_date.strftime("%Y-%m-%d"),
            "walkin_time": "10:00 AM - 3:00 PM",
            "walkin_venue": "Main Auditorium, Delhi Public School Campus",
            "walkin_contact_instructions": "Carry original certificates, marksheets, and 2 passport photos.",
            "location": "Chennai",
            "vacancies": 1,
            "action": "publish",
        }

        resp = self.client.post(reverse("admin-panel:walk-in-create"), data=payload)
        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, reverse("admin-panel:walk-ins"))

        job = Job.objects.filter(title="Senior Physics Faculty", is_walkin=True).first()
        self.assertIsNotNone(job)
        self.assertEqual(job.status, Job.Status.ACTIVE)
        self.assertEqual(job.approval_status, Job.ApprovalStatus.APPROVED)
        self.assertTrue(job.is_active)
        self.assertTrue(job.is_published)
        self.assertIsNotNone(job.published_at)

        # Published walk-in MUST appear in get_walkin_vacancies() immediately
        active_walkins = CandidateJobAlertMatchingService.get_walkin_vacancies()
        active_ids = [w["id"] for w in active_walkins]
        self.assertIn(str(job.id), active_ids)

        # Find the walk-in item and check label formatting
        target_w = next(w for w in active_walkins if w["id"] == str(job.id))
        self.assertEqual(target_w["title"], "Senior Physics Faculty")
        self.assertEqual(target_w["organization"], "Delhi Public School, Chennai")
        self.assertIn("Main Auditorium", target_w["venue"])

    def test_create_walkin_with_custom_organization(self):
        """Admin can enter a new organization name if it is not in the dropdown."""
        start_date = timezone.now().date() + timedelta(days=3)
        payload = {
            "title": "TGT English Teacher",
            "custom_organization_name": "Sunrise International Academy",
            "subject": "English",
            "walkin_start_date": start_date.strftime("%Y-%m-%d"),
            "walkin_time": "9:00 AM - 12:00 PM",
            "walkin_venue": "School Campus, Anna Nagar, Chennai",
            "location": "Chennai",
            "action": "publish",
        }

        resp = self.client.post(reverse("admin-panel:walk-in-create"), data=payload)
        self.assertEqual(resp.status_code, 302)

        # Verified new company was created automatically
        new_company = Company.objects.filter(name="Sunrise International Academy").first()
        self.assertIsNotNone(new_company)

        job = Job.objects.filter(title="TGT English Teacher", company=new_company).first()
        self.assertIsNotNone(job)
        self.assertEqual(job.status, Job.Status.ACTIVE)

    def test_past_date_rejected_on_publish(self):
        """Publishing a walk-in with a past date is rejected with validation error."""
        past_date = timezone.now().date() - timedelta(days=5)
        payload = {
            "title": "Expired Walk-in Test",
            "company": str(self.company.id),
            "walkin_start_date": past_date.strftime("%Y-%m-%d"),
            "walkin_time": "10:00 AM - 1:00 PM",
            "walkin_venue": "Campus Hall",
            "action": "publish",
        }

        resp = self.client.post(reverse("admin-panel:walk-in-create"), data=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertFormError(
            resp.context["form"],
            "walkin_start_date",
            "Walk-in date cannot be in the past when publishing. Choose today or a future date.",
        )

    def test_end_date_before_start_date_rejected(self):
        """End date cannot be earlier than start date."""
        today = timezone.now().date()
        payload = {
            "title": "Invalid Date Range Test",
            "company": str(self.company.id),
            "walkin_start_date": (today + timedelta(days=5)).strftime("%Y-%m-%d"),
            "walkin_end_date": (today + timedelta(days=2)).strftime("%Y-%m-%d"),
            "walkin_time": "10:00 AM - 1:00 PM",
            "walkin_venue": "Campus Hall",
            "action": "publish",
        }

        resp = self.client.post(reverse("admin-panel:walk-in-create"), data=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertFormError(
            resp.context["form"],
            "walkin_end_date",
            "Walk-in end date cannot be earlier than start date.",
        )

    def test_edit_walkin_vacancy(self):
        """Admin can edit an existing walk-in vacancy."""
        start_date = timezone.now().date() + timedelta(days=2)
        job = Job.objects.create(
            title="Primary Science Teacher",
            slug="primary-science-teacher-dps",
            company=self.company,
            recruiter=RecruiterProfile.objects.create(user=self.admin, company=self.company),
            is_walkin=True,
            walkin_start_date=start_date,
            walkin_time="9:30 AM - 12:30 PM",
            walkin_venue="Old Venue Block",
            status=Job.Status.DRAFT,
            approval_status=Job.ApprovalStatus.PENDING,
            metadata={"subject": "Science"},
        )

        update_payload = {
            "title": "Primary Science & EVS Teacher",
            "company": str(self.company.id),
            "subject": "Science",
            "walkin_start_date": start_date.strftime("%Y-%m-%d"),
            "walkin_time": "10:00 AM - 2:00 PM",
            "walkin_venue": "New Academic Block, Room 204",
            "walkin_contact_instructions": "Bring original degree certificates and 2 CVs.",
            "location": "Chennai",
            "action": "publish",
        }

        resp = self.client.post(
            reverse("admin-panel:walk-in-edit", kwargs={"job_id": job.id}),
            data=update_payload,
        )
        self.assertEqual(resp.status_code, 302)

        job.refresh_from_db()
        self.assertEqual(job.title, "Primary Science & EVS Teacher")
        self.assertEqual(job.walkin_time, "10:00 AM - 2:00 PM")
        self.assertEqual(job.walkin_venue, "New Academic Block, Room 204")
        self.assertEqual(job.status, Job.Status.ACTIVE)
        self.assertTrue(job.is_published)

    def test_walkin_status_actions(self):
        """Test status transitions: publish, unpublish, and cancel."""
        start_date = timezone.now().date() + timedelta(days=2)
        job = Job.objects.create(
            title="Biology Lecturer",
            slug="biology-lecturer-dps",
            company=self.company,
            recruiter=RecruiterProfile.objects.filter(company=self.company).first()
                      or RecruiterProfile.objects.create(user=self.admin, company=self.company),
            is_walkin=True,
            walkin_start_date=start_date,
            walkin_end_date=start_date,
            walkin_time="9:00 AM - 1:00 PM",
            walkin_venue="Biology Lab 1",
            status=Job.Status.DRAFT,
            approval_status=Job.ApprovalStatus.PENDING,
        )

        # 1. Action: Publish
        resp = self.client.post(
            reverse("admin-panel:walk-in-action", kwargs={"job_id": job.id}),
            data={"action": "publish"},
        )
        self.assertEqual(resp.status_code, 302)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.ACTIVE)
        self.assertEqual(job.approval_status, Job.ApprovalStatus.APPROVED)
        self.assertTrue(job.is_published)

        # 2. Action: Unpublish
        resp = self.client.post(
            reverse("admin-panel:walk-in-action", kwargs={"job_id": job.id}),
            data={"action": "unpublish"},
        )
        self.assertEqual(resp.status_code, 302)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.DRAFT)
        self.assertFalse(job.is_published)

        # 3. Action: Cancel
        resp = self.client.post(
            reverse("admin-panel:walk-in-action", kwargs={"job_id": job.id}),
            data={"action": "cancel"},
        )
        self.assertEqual(resp.status_code, 302)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.CLOSED)
        self.assertFalse(job.is_active)
        self.assertEqual(job.metadata.get("walkin_status"), "cancelled")

    def test_candidate_matching_count_for_walkin(self):
        """CandidateJobAlertMatchingService accurately calculates matching candidate counts."""
        start_date = timezone.now().date() + timedelta(days=1)
        job = Job.objects.create(
            title="PGT Mathematics Teacher",
            slug="pgt-mathematics-teacher-dps",
            company=self.company,
            recruiter=RecruiterProfile.objects.filter(company=self.company).first()
                      or RecruiterProfile.objects.create(user=self.admin, company=self.company),
            is_walkin=True,
            walkin_start_date=start_date,
            walkin_venue="Main Campus",
            location="Chennai",
            status=Job.Status.ACTIVE,
            approval_status=Job.ApprovalStatus.APPROVED,
            metadata={"subject": "Mathematics"},
        )

        match_count = CandidateJobAlertMatchingService.count_matching_candidates_for_walkin(job)
        # self.candidate is an active English/Mathematics teacher with 3 yrs exp in Chennai
        self.assertEqual(match_count, 1)

    def test_bulk_job_alerts_integration_dropdown(self):
        """Published walk-in vacancy appears in Bulk Job Alerts dropdown with formatted label."""
        start_date = timezone.now().date() + timedelta(days=2)
        job = Job.objects.create(
            title="PGT Chemistry Faculty",
            slug="pgt-chem-dps",
            company=self.company,
            recruiter=RecruiterProfile.objects.filter(company=self.company).first()
                      or RecruiterProfile.objects.create(user=self.admin, company=self.company),
            is_walkin=True,
            walkin_start_date=start_date,
            walkin_end_date=start_date,
            walkin_time="10:00 AM - 1:00 PM",
            walkin_venue="Chemistry Dept Hall",
            location="Chennai",
            status=Job.Status.ACTIVE,
            approval_status=Job.ApprovalStatus.APPROVED,
        )

        resp = self.client.get(reverse("admin-panel:bulk-job-alerts"))
        self.assertEqual(resp.status_code, 200)

        # Check walkin_vacancies context
        walkin_vacancies = resp.context.get("walkin_vacancies", [])
        w_ids = [w["id"] for w in walkin_vacancies]
        self.assertIn(str(job.id), w_ids)

        # Verify the HTML rendered includes the option with the formatted label
        dates_and_time = f"{start_date.strftime('%b %d, %Y')} (10:00 AM - 1:00 PM)"
        expected_option = f"{job.title} — {self.company.name} — Chennai — {dates_and_time}"
        self.assertContains(resp, expected_option)

    def test_detail_json_api(self):
        """AdminWalkInDetailView returns 200 and complete JSON descriptor for preview modal."""
        start_date = timezone.now().date() + timedelta(days=2)
        job = Job.objects.create(
            title="Economics Teacher",
            slug="economics-teacher-dps",
            company=self.company,
            recruiter=RecruiterProfile.objects.filter(company=self.company).first()
                      or RecruiterProfile.objects.create(user=self.admin, company=self.company),
            is_walkin=True,
            walkin_start_date=start_date,
            walkin_time="9:30 AM - 12:30 PM",
            walkin_venue="Room 101",
            location="Chennai",
            status=Job.Status.ACTIVE,
            approval_status=Job.ApprovalStatus.APPROVED,
            metadata={"subject": "Economics", "contact_person": "Mrs. Priya", "contact_phone": "9840012345"},
        )

        resp = self.client.get(reverse("admin-panel:walk-in-detail", kwargs={"job_id": job.id}))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        w = data["walkin"]
        self.assertEqual(w["title"], "Economics Teacher")
        self.assertEqual(w["organization"], self.company.name)
        self.assertEqual(w["contact_person"], "Mrs. Priya")
        self.assertEqual(w["contact_phone"], "9840012345")
        self.assertIn("job-alerts", w["alert_url"])

    def test_launch_walkin_campaign_url_with_query_params(self):
        """Clicking 'Launch Walk-in Alert Campaign' opens Bulk Job Alerts without NoReverseMatch."""
        start_date = timezone.now().date() + timedelta(days=2)
        job = Job.objects.create(
            title="PGT English Teacher",
            company=self.company,
            recruiter=RecruiterProfile.objects.filter(company=self.company).first()
                      or RecruiterProfile.objects.create(user=self.admin, company=self.company),
            is_walkin=True,
            walkin_start_date=start_date,
            walkin_time="10:00 AM - 3:00 PM",
            walkin_venue="Campus Hall",
            location="Chennai",
            status=Job.Status.ACTIVE,
            approval_status=Job.ApprovalStatus.APPROVED,
        )
        self.assertTrue(bool(job.slug))

        # Request URL matching user's exact flow: ?alert_type=walkin_alert&walkin_id=<id>
        url = f"{reverse('admin-panel:bulk-job-alerts')}?alert_type=walkin_alert&walkin_id={job.id}"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, str(job.id))
        self.assertContains(resp, "PGT English Teacher")
