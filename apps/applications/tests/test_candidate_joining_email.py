"""
Automated unit & integration test suite for Candidate Joining transactional email flow.
"""

from unittest.mock import patch
from datetime import date
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
    OfferDetails,
)
from apps.applications.services import ApplicationService
from apps.notifications.models import Notification, EmailTask


@override_settings(
    EMAIL_BACKEND="apps.notifications.backends.ResendEmailBackend",
    DEFAULT_FROM_EMAIL="SevaJobs <noreply@sevajobs.in>",
    FRONTEND_URL="https://sevajobs.in",
)
class CandidateJoiningEmailTestCase(TestCase):
    def setUp(self):
        # Recruiter & Company
        self.recruiter_user = User.objects.create_user(
            email="recruiter.joining@example.com",
            password="Password123!",
            first_name="Meera",
            last_name="Singh",
            role=User.Role.RECRUITER,
            is_email_verified=True,
        )
        self.company = Company.objects.create(
            name="Apex Innovations",
            created_by=self.recruiter_user,
        )
        self.recruiter = Recruiter.objects.create(
            user=self.recruiter_user,
            company=self.company,
        )

        # Job
        self.job = Job.objects.create(
            title="Lead Software Architect",
            company=self.company,
            posted_by=self.recruiter_user,
            status="active",
        )

        # Candidate
        self.candidate_user = User.objects.create_user(
            email="candidate.joined@example.com",
            password="Password123!",
            first_name="Rohan",
            last_name="Verma",
            role=User.Role.JOB_SEEKER,
            is_email_verified=True,
        )

        # Application in OFFER_ACCEPTED status (valid pre-joining status)
        self.application = JobApplication.objects.create(
            job=self.job,
            applicant=self.candidate_user,
            status=JobApplication.Status.OFFER_ACCEPTED,
        )

        # Offer details
        self.offer = OfferDetails.objects.create(
            application=self.application,
            annual_ctc=1200000,
            monthly_salary=100000,
            joining_date=date(2026, 10, 1),
            status="accepted",
        )

        self.service = ApplicationService(user=self.recruiter_user)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_01_successful_joined_transition(self, mock_delay):
        """TEST 1: Authorized actor marks eligible application JOINED -> status == JOINED."""
        app = self.service.move_status(
            self.application,
            new_status=JobApplication.Status.JOINED,
            changed_by=self.recruiter_user,
        )
        self.assertEqual(app.status, JobApplication.Status.JOINED)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_02_correct_template(self, mock_delay):
        """TEST 2: Template used is joining."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.JOINED,
            changed_by=self.recruiter_user,
        )
        task = EmailTask.objects.first()
        self.assertEqual(task.template_name, "joining")

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_03_email_scheduled_once(self, mock_delay):
        """TEST 3: Exactly one joining email is scheduled."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.JOINED,
            changed_by=self.recruiter_user,
        )
        self.assertEqual(EmailTask.objects.count(), 1)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_04_recipient(self, mock_delay):
        """TEST 4: Email recipient is candidate.email."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.JOINED,
            changed_by=self.recruiter_user,
        )
        task = EmailTask.objects.first()
        self.assertEqual(task.recipient, "candidate.joined@example.com")

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_05_subject(self, mock_delay):
        """TEST 5: Subject contains [SevaJobs] 🎉 Joining Confirmed — <job_title>."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.JOINED,
            changed_by=self.recruiter_user,
        )
        task = EmailTask.objects.first()
        self.assertEqual(task.subject, "[SevaJobs] 🎉 Joining Confirmed — Lead Software Architect")

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_06_candidate_context(self, mock_delay):
        """TEST 6: Candidate name in context."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.JOINED,
            changed_by=self.recruiter_user,
        )
        task = EmailTask.objects.first()
        self.assertEqual(task.context["candidate_name"], "Rohan")

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_07_job_context(self, mock_delay):
        """TEST 7: Job title in context."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.JOINED,
            changed_by=self.recruiter_user,
        )
        task = EmailTask.objects.first()
        self.assertEqual(task.context["job_title"], "Lead Software Architect")

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_08_company_context(self, mock_delay):
        """TEST 8: Company name in context."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.JOINED,
            changed_by=self.recruiter_user,
        )
        task = EmailTask.objects.first()
        self.assertEqual(task.context["company_name"], "Apex Innovations")

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_09_joining_metadata(self, mock_delay):
        """TEST 9: Joining date formatted correctly in context metadata."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.JOINED,
            changed_by=self.recruiter_user,
        )
        task = EmailTask.objects.first()
        self.assertEqual(task.context["joining_date"], "01 October 2026")

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_10_html_template_rendering(self, mock_delay):
        """TEST 10: joining.html renders cleanly."""
        from django.template.loader import render_to_string
        html = render_to_string("emails/joining.html", {
            "candidate_name": "Rohan",
            "job_title": "Lead Software Architect",
            "company_name": "Apex Innovations",
            "frontend_url": "https://sevajobs.in",
        })
        self.assertIn("Hi Rohan,", html)
        self.assertIn("Lead Software Architect", html)
        self.assertIn("Apex Innovations", html)
        self.assertIn("https://sevajobs.in/dashboard/seeker/applied-jobs/", html)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_11_txt_template_rendering(self, mock_delay):
        """TEST 11: joining.txt renders cleanly."""
        from django.template.loader import render_to_string
        txt = render_to_string("emails/joining.txt", {
            "candidate_name": "Rohan",
            "job_title": "Lead Software Architect",
            "company_name": "Apex Innovations",
            "frontend_url": "https://sevajobs.in",
        })
        self.assertIn("Hi Rohan,", txt)
        self.assertIn("Lead Software Architect at Apex Innovations", txt)
        self.assertIn("https://sevajobs.in/dashboard/seeker/applied-jobs/", txt)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_12_internal_notification(self, mock_delay):
        """TEST 12: Candidate receives internal in-app notification."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.JOINED,
            changed_by=self.recruiter_user,
        )
        notif = Notification.objects.filter(recipient=self.candidate_user).first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.title, "🎉 Joining Confirmed — Lead Software Architect")

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_13_application_history(self, mock_delay):
        """TEST 13: ApplicationStatusHistory records JOINED transition exactly once."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.JOINED,
            changed_by=self.recruiter_user,
        )
        history = ApplicationStatusHistory.objects.filter(application=self.application)
        self.assertEqual(history.count(), 1)
        record = history.first()
        self.assertEqual(record.from_status, JobApplication.Status.OFFER_ACCEPTED)
        self.assertEqual(record.to_status, JobApplication.Status.JOINED)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_14_valid_transition(self, mock_delay):
        """TEST 14: Valid previous status (OFFER_ACCEPTED) transitions to JOINED."""
        app = self.service.move_status(
            self.application,
            new_status=JobApplication.Status.JOINED,
            changed_by=self.recruiter_user,
        )
        self.assertEqual(app.status, JobApplication.Status.JOINED)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_15_invalid_transition(self, mock_delay):
        """TEST 15: Invalid status transition (e.g. SHORTLISTED -> JOINED) is blocked by state machine."""
        app = JobApplication.objects.create(
            job=self.job,
            applicant=self.candidate_user,
            status=JobApplication.Status.SHORTLISTED,
        )
        with self.assertRaises(ValidationError):
            self.service.move_status(app, new_status=JobApplication.Status.JOINED, changed_by=self.recruiter_user)

        app.refresh_from_db()
        self.assertEqual(app.status, JobApplication.Status.SHORTLISTED)
        self.assertFalse(EmailTask.objects.filter(recipient=self.candidate_user.email, template_name="joining").exists())

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_16_rejected_protection(self, mock_delay):
        """TEST 16: REJECTED -> JOINED transition is blocked by state machine."""
        app = JobApplication.objects.create(
            job=self.job,
            applicant=self.candidate_user,
            status=JobApplication.Status.REJECTED,
        )
        with self.assertRaises(ValidationError):
            self.service.move_status(app, new_status=JobApplication.Status.JOINED, changed_by=self.recruiter_user)

        app.refresh_from_db()
        self.assertEqual(app.status, JobApplication.Status.REJECTED)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_17_unauthorized_recruiter(self, mock_delay):
        """TEST 17: Unauthorized recruiter cannot mark candidate as JOINED."""
        other_recruiter = User.objects.create_user(
            email="other.recruiter.joining@example.com",
            password="Password123!",
            role=User.Role.RECRUITER,
        )
        unauth_service = ApplicationService(user=other_recruiter)
        with self.assertRaises(PermissionDenied):
            unauth_service.move_status(
                self.application,
                new_status=JobApplication.Status.JOINED,
                changed_by=other_recruiter,
            )

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, JobApplication.Status.OFFER_ACCEPTED)
        self.assertEqual(EmailTask.objects.count(), 0)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_18_transaction_rollback(self, mock_delay):
        """TEST 18: Database rollback prevents joining email task creation."""
        try:
            with transaction.atomic():
                self.service.move_status(
                    self.application,
                    new_status=JobApplication.Status.JOINED,
                    changed_by=self.recruiter_user,
                )
                raise DatabaseError("Simulated DB failure")
        except DatabaseError:
            pass

        self.assertEqual(EmailTask.objects.count(), 0)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, JobApplication.Status.OFFER_ACCEPTED)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_19_transaction_commit(self, mock_delay):
        """TEST 19: Successful transaction commit enqueues email."""
        with transaction.atomic():
            self.service.move_status(
                self.application,
                new_status=JobApplication.Status.JOINED,
                changed_by=self.recruiter_user,
            )

        self.assertEqual(EmailTask.objects.count(), 1)
        mock_delay.assert_called_once()

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_20_idempotency_key(self, mock_delay):
        """TEST 20: Idempotency key matches app_status:<application_id>:joined."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.JOINED,
            changed_by=self.recruiter_user,
        )
        task = EmailTask.objects.first()
        expected_key = f"app_status:{self.application.id}:joined"
        self.assertEqual(task.idempotency_key, expected_key)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_21_duplicate_joined_action(self, mock_delay):
        """TEST 21: Attempting JOINED transition twice is blocked by terminal status rules."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.JOINED,
            changed_by=self.recruiter_user,
        )
        self.assertEqual(EmailTask.objects.count(), 1)

        # Second attempt
        with self.assertRaises(ValidationError):
            self.service.move_status(
                self.application,
                new_status=JobApplication.Status.JOINED,
                changed_by=self.recruiter_user,
            )

        self.assertEqual(EmailTask.objects.count(), 1)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_22_selected_email_separation(self, mock_delay):
        """TEST 22: JOINED transition sends joining email, NOT selected email."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.JOINED,
            changed_by=self.recruiter_user,
        )
        task = EmailTask.objects.first()
        self.assertEqual(task.template_name, "joining")
        self.assertNotEqual(task.template_name, "selected")

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_23_rejected_email_separation(self, mock_delay):
        """TEST 23: JOINED transition does NOT send rejected email."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.JOINED,
            changed_by=self.recruiter_user,
        )
        task = EmailTask.objects.first()
        self.assertNotEqual(task.template_name, "rejected")

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_24_joining_date_handling(self, mock_delay):
        """TEST 24: OfferDetails status updated to joined when application becomes JOINED."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.JOINED,
            changed_by=self.recruiter_user,
        )
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.status, "joined")

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_25_missing_offer_details_web_ui(self, mock_delay):
        """TEST 25: RecruiterMarkJoinedView redirects with error if offer details missing."""
        app_no_offer = JobApplication.objects.create(
            job=self.job,
            applicant=self.candidate_user,
            status=JobApplication.Status.OFFER_ACCEPTED,
        )
        self.client.force_login(self.recruiter_user)
        url = reverse("dashboard:recruiter:mark-joined", kwargs={"pk": app_no_offer.id})
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, 302)
        app_no_offer.refresh_from_db()
        self.assertEqual(app_no_offer.status, JobApplication.Status.OFFER_ACCEPTED)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_26_normal_job_behavior(self, mock_delay):
        """TEST 26: Normal job resolves job_title and company_name correctly."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.JOINED,
            changed_by=self.recruiter_user,
        )
        task = EmailTask.objects.first()
        self.assertEqual(task.context["job_title"], "Lead Software Architect")
        self.assertEqual(task.context["company_name"], "Apex Innovations")

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_27_staff_job_behavior(self, mock_delay):
        """TEST 27: Staff job resolves designation and institution name correctly."""
        staff_app = JobApplication.objects.create(
            job=None,
            applicant=self.candidate_user,
            staff_job_title="Vice Principal",
            staff_institution_name="DPS International",
            status=JobApplication.Status.OFFER_ACCEPTED,
        )
        staff_service = ApplicationService(user=self.recruiter_user)

        with patch.object(ApplicationService, "_validate_permission", return_value=True):
            staff_service.move_status(
                staff_app,
                new_status=JobApplication.Status.JOINED,
                changed_by=self.recruiter_user,
            )

        task = EmailTask.objects.filter(recipient=self.candidate_user.email).latest("created_at")
        self.assertEqual(task.context["job_title"], "Vice Principal")
        self.assertEqual(task.context["company_name"], "DPS International")

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_28_cta_route_validation(self, mock_delay):
        """TEST 28: CTA button points to valid candidate route."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.JOINED,
            changed_by=self.recruiter_user,
        )
        task = EmailTask.objects.first()
        self.assertEqual(task.context["frontend_url"], "https://sevajobs.in")

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_29_web_ui_mark_joined_view(self, mock_delay):
        """TEST 29: RecruiterMarkJoinedView invokes ApplicationService."""
        self.client.force_login(self.recruiter_user)
        url = reverse("dashboard:recruiter:mark-joined", kwargs={"pk": self.application.id})
        response = self.client.post(url, {
            "employee_id": "EMP-9081",
            "remarks": "Joined on time",
            "joining_date": "2026-10-01",
        })
        self.assertEqual(response.status_code, 302)

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, JobApplication.Status.JOINED)
        self.assertEqual(EmailTask.objects.count(), 1)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_30_api_mark_joined(self, mock_delay):
        """TEST 30: API status update endpoint invokes ApplicationService for JOINED."""
        self.client.force_login(self.recruiter_user)
        url = f"/api/v1/applications/{self.application.id}/status/"
        response = self.client.patch(
            url,
            {"status": "joined"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, JobApplication.Status.JOINED)
        self.assertEqual(EmailTask.objects.count(), 1)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_31_no_duplicate_claims(self, mock_delay):
        """TEST 31: JOINED transition creates exactly 1 history record and 1 email task."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.JOINED,
            changed_by=self.recruiter_user,
        )
        self.assertEqual(ApplicationStatusHistory.objects.filter(application=self.application).count(), 1)
        self.assertEqual(EmailTask.objects.count(), 1)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_32_no_duplicate_invoices(self, mock_delay):
        """TEST 32: JOINED transition preserves database state without extra tasks."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.JOINED,
            changed_by=self.recruiter_user,
        )
        self.assertEqual(EmailTask.objects.filter(template_name="joining").count(), 1)

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_33_existing_status_workflows_unaffected(self, mock_delay):
        """TEST 33: Other status email flows remain intact."""
        app2 = JobApplication.objects.create(
            job=self.job,
            applicant=self.candidate_user,
            status=JobApplication.Status.APPLIED,
        )
        self.service.move_status(app2, new_status=JobApplication.Status.SHORTLISTED, changed_by=self.recruiter_user)
        task = EmailTask.objects.latest("created_at")
        self.assertEqual(task.template_name, "shortlisted")

    @patch("apps.notifications.email_service.send_celery_email_task.delay")
    def test_34_notification_tests_passing(self, mock_delay):
        """TEST 34: Notification model stores candidate notification."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.JOINED,
            changed_by=self.recruiter_user,
        )
        self.assertTrue(Notification.objects.filter(recipient=self.candidate_user).exists())
