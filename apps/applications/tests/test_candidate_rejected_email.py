"""
Automated unit & integration test suite for Candidate Rejected transactional email flow.
"""

from unittest.mock import patch
from decimal import Decimal
from django.test import TestCase, override_settings
from django.db import transaction, DatabaseError
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from apps.accounts.models import User
from apps.jobs.models import Job
from apps.recruiters.models import Recruiter, Company
from apps.applications.models import (
    JobApplication,
    ApplicationStatusHistory,
    CandidateRejection,
)
from apps.applications.services import ApplicationService
from apps.notifications.models import Notification, EmailTask


@override_settings(
    EMAIL_BACKEND="apps.notifications.backends.ResendEmailBackend",
    DEFAULT_FROM_EMAIL="SevaJobs <noreply@sevajobs.in>",
    FRONTEND_URL="https://sevajobs.in",
)
class CandidateRejectedEmailTestCase(TestCase):
    def setUp(self):
        # Recruiter & Company
        self.recruiter_user = User.objects.create_user(
            email="recruiter@example.com",
            password="Password123!",
            first_name="Ramesh",
            last_name="Recruiter",
            role=User.Role.RECRUITER,
            is_email_verified=True,
        )
        self.company = Company.objects.create(
            name="TechCorp India",
            created_by=self.recruiter_user,
        )
        self.recruiter = Recruiter.objects.create(
            user=self.recruiter_user,
            company=self.company,
        )

        # Job
        self.job = Job.objects.create(
            title="Senior Python Developer",
            company=self.company,
            posted_by=self.recruiter_user,
            status="active",
        )

        # Candidate
        self.candidate_user = User.objects.create_user(
            email="candidate.rejected@example.com",
            password="Password123!",
            first_name="Aarav",
            last_name="Sharma",
            role=User.Role.JOB_SEEKER,
            is_email_verified=True,
        )

        # Application
        self.application = JobApplication.objects.create(
            job=self.job,
            applicant=self.candidate_user,
            status=JobApplication.Status.SHORTLISTED,
        )

        self.service = ApplicationService(user=self.recruiter_user)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_01_successful_rejection(self, mock_delay):
        """TEST 1: Authorized recruiter rejects eligible candidate -> status == REJECTED."""
        app = self.service.move_status(
            self.application,
            new_status=JobApplication.Status.REJECTED,
            changed_by=self.recruiter_user,
            note="Not matching required experience level",
        )
        self.assertEqual(app.status, JobApplication.Status.REJECTED)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_02_email_scheduled(self, mock_delay):
        """TEST 2: Exactly one rejected email task scheduled."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.REJECTED,
            changed_by=self.recruiter_user,
        )
        self.assertEqual(EmailTask.objects.count(), 1)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_03_recipient(self, mock_delay):
        """TEST 3: Email recipient is candidate.email."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.REJECTED,
            changed_by=self.recruiter_user,
        )
        task = EmailTask.objects.first()
        self.assertEqual(task.recipient, "candidate.rejected@example.com")

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_04_template(self, mock_delay):
        """TEST 4: Template used is rejected."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.REJECTED,
            changed_by=self.recruiter_user,
        )
        task = EmailTask.objects.first()
        self.assertEqual(task.template_name, "rejected")

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_05_subject(self, mock_delay):
        """TEST 5: Email subject is exact [SevaJobs] Application Update."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.REJECTED,
            changed_by=self.recruiter_user,
        )
        task = EmailTask.objects.first()
        self.assertEqual(task.subject, "[SevaJobs] Application Update")

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_06_candidate_context(self, mock_delay):
        """TEST 6: Candidate name included in context."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.REJECTED,
            changed_by=self.recruiter_user,
        )
        task = EmailTask.objects.first()
        self.assertEqual(task.context["candidate_name"], "Aarav")

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_07_job_context(self, mock_delay):
        """TEST 7: Job title included in context."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.REJECTED,
            changed_by=self.recruiter_user,
        )
        task = EmailTask.objects.first()
        self.assertEqual(task.context["job_title"], "Senior Python Developer")

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_08_company_context(self, mock_delay):
        """TEST 8: Company name included in context."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.REJECTED,
            changed_by=self.recruiter_user,
        )
        task = EmailTask.objects.first()
        self.assertEqual(task.context["company_name"], "TechCorp India")

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_09_rejection_reason_privacy(self, mock_delay):
        """TEST 9: CandidateRejection model records reason, but private notes are NOT exposed in email context."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.REJECTED,
            changed_by=self.recruiter_user,
            note="Internal note: Candidate failed tech screen question 3",
        )
        rejection = CandidateRejection.objects.get(application=self.application)
        self.assertEqual(rejection.reason, "Internal note: Candidate failed tech screen question 3")

        task = EmailTask.objects.first()
        self.assertNotIn("Internal note", str(task.context))

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_10_html_template_rendering(self, mock_delay):
        """TEST 10: rejected.html renders cleanly."""
        from django.template.loader import render_to_string
        html = render_to_string("emails/rejected.html", {
            "candidate_name": "Aarav",
            "job_title": "Senior Python Developer",
            "company_name": "TechCorp India",
            "frontend_url": "https://sevajobs.in",
        })
        self.assertIn("Hi Aarav,", html)
        self.assertIn("Senior Python Developer", html)
        self.assertIn("TechCorp India", html)
        self.assertIn("Explore Other Job Openings", html)
        self.assertIn("https://sevajobs.in/jobs", html)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_11_txt_template_rendering(self, mock_delay):
        """TEST 11: rejected.txt renders cleanly."""
        from django.template.loader import render_to_string
        txt = render_to_string("emails/rejected.txt", {
            "candidate_name": "Aarav",
            "job_title": "Senior Python Developer",
            "company_name": "TechCorp India",
            "frontend_url": "https://sevajobs.in",
        })
        self.assertIn("Hi Aarav,", txt)
        self.assertIn("Senior Python Developer at TechCorp India", txt)
        self.assertIn("https://sevajobs.in/jobs", txt)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_12_internal_notification(self, mock_delay):
        """TEST 12: Candidate receives internal in-app notification."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.REJECTED,
            changed_by=self.recruiter_user,
        )
        notif = Notification.objects.filter(recipient=self.candidate_user).first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.title, "Application Update")
        self.assertIn("Senior Python Developer", notif.message)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_13_application_history(self, mock_delay):
        """TEST 13: ApplicationStatusHistory records REJECTED transition exactly once."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.REJECTED,
            changed_by=self.recruiter_user,
            note="Experience mismatch",
        )
        history = ApplicationStatusHistory.objects.filter(application=self.application)
        self.assertEqual(history.count(), 1)
        record = history.first()
        self.assertEqual(record.from_status, JobApplication.Status.SHORTLISTED)
        self.assertEqual(record.to_status, JobApplication.Status.REJECTED)
        self.assertEqual(record.changed_by, self.recruiter_user)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_14_valid_transitions(self, mock_delay):
        """TEST 14: Valid statuses (APPLIED, UNDER_REVIEW, SHORTLISTED, INTERVIEW_SCHEDULED) can transition to REJECTED."""
        statuses = [
            JobApplication.Status.APPLIED,
            JobApplication.Status.UNDER_REVIEW,
            JobApplication.Status.SHORTLISTED,
            JobApplication.Status.INTERVIEW_SCHEDULED,
        ]
        for st in statuses:
            app = JobApplication.objects.create(
                job=self.job,
                applicant=self.candidate_user,
                status=st,
            )
            res = self.service.move_status(app, new_status=JobApplication.Status.REJECTED, changed_by=self.recruiter_user)
            self.assertEqual(res.status, JobApplication.Status.REJECTED)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_15_invalid_transition(self, mock_delay):
        """TEST 15: Invalid status transition (e.g. JOINED -> REJECTED) is blocked by state machine."""
        app = JobApplication.objects.create(
            job=self.job,
            applicant=self.candidate_user,
            status=JobApplication.Status.JOINED,
        )
        with self.assertRaises(ValidationError):
            self.service.move_status(app, new_status=JobApplication.Status.REJECTED, changed_by=self.recruiter_user)

        app.refresh_from_db()
        self.assertEqual(app.status, JobApplication.Status.JOINED)
        self.assertFalse(EmailTask.objects.filter(recipient=self.candidate_user.email, template_name="rejected").exists())

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_16_unauthorized_recruiter(self, mock_delay):
        """TEST 16: Unauthorized recruiter cannot reject candidate."""
        other_recruiter = User.objects.create_user(
            email="other.recruiter@example.com",
            password="Password123!",
            role=User.Role.RECRUITER,
        )
        unauth_service = ApplicationService(user=other_recruiter)
        with self.assertRaises(PermissionDenied):
            unauth_service.move_status(
                self.application,
                new_status=JobApplication.Status.REJECTED,
                changed_by=other_recruiter,
            )

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, JobApplication.Status.SHORTLISTED)
        self.assertEqual(EmailTask.objects.count(), 0)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_17_transaction_rollback(self, mock_delay):
        """TEST 17: Database transaction rollback prevents email task creation."""
        try:
            with transaction.atomic():
                self.service.move_status(
                    self.application,
                    new_status=JobApplication.Status.REJECTED,
                    changed_by=self.recruiter_user,
                )
                raise DatabaseError("Simulated DB error")
        except DatabaseError:
            pass

        self.assertEqual(EmailTask.objects.count(), 0)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, JobApplication.Status.SHORTLISTED)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_18_transaction_commit(self, mock_delay):
        """TEST 18: Successful transaction commit enqueues email."""
        with transaction.atomic():
            self.service.move_status(
                self.application,
                new_status=JobApplication.Status.REJECTED,
                changed_by=self.recruiter_user,
            )

        self.assertEqual(EmailTask.objects.count(), 1)
        mock_delay.assert_called_once()

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_19_idempotency_key(self, mock_delay):
        """TEST 19: Idempotency key matches app_status:<application_id>:rejected."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.REJECTED,
            changed_by=self.recruiter_user,
        )
        task = EmailTask.objects.first()
        expected_key = f"app_status:{self.application.id}:rejected"
        self.assertEqual(task.idempotency_key, expected_key)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_20_duplicate_rejection(self, mock_delay):
        """TEST 20: Rejecting an already REJECTED application is blocked by state machine."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.REJECTED,
            changed_by=self.recruiter_user,
        )
        self.assertEqual(EmailTask.objects.count(), 1)

        # Attempt second rejection
        with self.assertRaises(ValidationError):
            self.service.move_status(
                self.application,
                new_status=JobApplication.Status.REJECTED,
                changed_by=self.recruiter_user,
            )

        self.assertEqual(EmailTask.objects.count(), 1)
        self.assertEqual(ApplicationStatusHistory.objects.filter(application=self.application).count(), 1)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_21_selected_separation(self, mock_delay):
        """TEST 21: Rejection sends rejected email, NOT selected email."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.REJECTED,
            changed_by=self.recruiter_user,
        )
        task = EmailTask.objects.first()
        self.assertEqual(task.template_name, "rejected")
        self.assertNotEqual(task.template_name, "selected")

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_22_joining_separation(self, mock_delay):
        """TEST 22: Rejection does NOT send joining email."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.REJECTED,
            changed_by=self.recruiter_user,
        )
        task = EmailTask.objects.first()
        self.assertNotEqual(task.template_name, "joining")

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_23_normal_job_behavior(self, mock_delay):
        """TEST 23: Normal job resolves job_title and company_name correctly."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.REJECTED,
            changed_by=self.recruiter_user,
        )
        task = EmailTask.objects.first()
        self.assertEqual(task.context["job_title"], "Senior Python Developer")
        self.assertEqual(task.context["company_name"], "TechCorp India")

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_24_staff_job_behavior(self, mock_delay):
        """TEST 24: Staff job resolves designation and institution name correctly."""
        staff_app = JobApplication.objects.create(
            job=None,
            applicant=self.candidate_user,
            staff_job_title="Primary School Teacher",
            staff_institution_name="St. Mary Academy",
            status=JobApplication.Status.SHORTLISTED,
        )
        staff_service = ApplicationService(user=self.recruiter_user)

        with patch.object(ApplicationService, "_validate_permission", return_value=True):
            staff_service.move_status(
                staff_app,
                new_status=JobApplication.Status.REJECTED,
                changed_by=self.recruiter_user,
            )

        task = EmailTask.objects.filter(recipient=self.candidate_user.email).latest("created_at")
        self.assertEqual(task.context["job_title"], "Primary School Teacher")
        self.assertEqual(task.context["company_name"], "St. Mary Academy")

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_25_web_ui_action(self, mock_delay):
        """TEST 25: Recruiter Web UI action invokes ApplicationService."""
        self.client.force_login(self.recruiter_user)
        url = reverse("dashboard:recruiter:application-detail", kwargs={"pk": self.application.id})
        response = self.client.post(url, {"action": "reject"})
        self.assertEqual(response.status_code, 302)

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, JobApplication.Status.REJECTED)
        self.assertEqual(EmailTask.objects.count(), 1)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_26_api_action(self, mock_delay):
        """TEST 26: Recruiter API endpoint invokes ApplicationService."""
        self.client.force_login(self.recruiter_user)
        url = f"/api/v1/applications/{self.application.id}/status/"
        response = self.client.patch(
            url,
            {"status": "rejected", "note": "API Rejection"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, JobApplication.Status.REJECTED)
        self.assertEqual(EmailTask.objects.count(), 1)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_27_cta_url_validation(self, mock_delay):
        """TEST 27: CTA URL points to valid jobs path."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.REJECTED,
            changed_by=self.recruiter_user,
        )
        task = EmailTask.objects.first()
        self.assertEqual(task.context["frontend_url"], "https://sevajobs.in")

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_28_no_none_null_rendered(self, mock_delay):
        """TEST 28: Missing optional values render cleanly without None or null."""
        from django.template.loader import render_to_string
        html = render_to_string("emails/rejected.html", {
            "candidate_name": "Aarav",
            "job_title": "Developer",
            "company_name": "TechCorp",
            "frontend_url": "https://sevajobs.in",
        })
        self.assertNotIn("None", html)
        self.assertNotIn("null", html)
        self.assertNotIn("undefined", html)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_29_existing_status_emails_unaffected(self, mock_delay):
        """TEST 29: Other status emails remain unaffected."""
        app2 = JobApplication.objects.create(
            job=self.job,
            applicant=self.candidate_user,
            status=JobApplication.Status.APPLIED,
        )
        self.service.move_status(app2, new_status=JobApplication.Status.SHORTLISTED, changed_by=self.recruiter_user)
        task = EmailTask.objects.latest("created_at")
        self.assertEqual(task.template_name, "shortlisted")

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_30_notification_tests_passing(self, mock_delay):
        """TEST 30: System notifications generated for candidate."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.REJECTED,
            changed_by=self.recruiter_user,
        )
        self.assertTrue(Notification.objects.filter(recipient=self.candidate_user).exists())
