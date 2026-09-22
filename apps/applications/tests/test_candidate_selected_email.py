"""Automated test suite for Candidate Selected transactional email flow."""

from datetime import date, timedelta
from unittest.mock import patch
from django.test import TestCase, override_settings, Client
from django.contrib.auth import get_user_model
from django.db import transaction, DatabaseError
from django.template.loader import render_to_string
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework import status

from apps.jobs.models import Job, Company, StaffJob
from apps.recruiters.models import RecruiterProfile
from apps.applications.models import (
    JobApplication, Resume, ApplicationStatusHistory, CandidateSelection, OfferDetails
)
from apps.applications.services import ApplicationService
from apps.notifications.email_service import EmailService
from apps.notifications.models import Notification

User = get_user_model()


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_STORE_EAGER_RESULT=False,
    FRONTEND_URL="https://sevajobs.in",
)
class CandidateSelectedEmailTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.api_client = APIClient()
        self.service = ApplicationService()

        # Job Seeker (Candidate)
        self.candidate = User.objects.create_user(
            email="candidate.selected@example.com",
            password="Password123!",
            first_name="Pooja",
            last_name="Nair",
            phone="9876543210",
            is_email_verified=True,
            role=User.Role.JOB_SEEKER,
        )

        # Recruiter
        self.recruiter_user = User.objects.create_user(
            email="recruiter.selected@example.com",
            password="Password123!",
            first_name="Arun",
            last_name="Kapoor",
            is_email_verified=True,
            role=User.Role.RECRUITER,
        )

        self.company = Company.objects.create(
            name="Zenith Soft",
            website="https://zenithsoft.in",
        )

        self.recruiter_profile, _ = RecruiterProfile.objects.get_or_create(
            user=self.recruiter_user,
            defaults={"company": self.company, "designation": "Head of Engineering"}
        )

        # Unauthorized Recruiter
        self.other_recruiter_user = User.objects.create_user(
            email="unauth.recruiter@example.com",
            password="Password123!",
            first_name="Unauth",
            last_name="Recruiter",
            is_email_verified=True,
            role=User.Role.RECRUITER,
        )
        self.other_company = Company.objects.create(name="Other Corp")
        self.other_profile, _ = RecruiterProfile.objects.get_or_create(
            user=self.other_recruiter_user,
            defaults={"company": self.other_company, "designation": "HR"}
        )

        # Staff User
        self.staff_user = User.objects.create_user(
            email="staff.selected@example.com",
            password="Password123!",
            first_name="Meera",
            last_name="Joshi",
            is_email_verified=True,
            role=User.Role.STAFF,
            is_staff=True,
        )

        # Active Normal Job
        self.job = Job.objects.create(
            title="Lead Backend Engineer",
            company=self.company,
            recruiter=self.recruiter_profile,
            status=Job.Status.ACTIVE,
            job_type="full_time",
            experience_level="senior",
        )

        # Active Staff Job
        self.staff_job = StaffJob.objects.create(
            designation="Principal Accountant",
            organization_name="Zenith Financials",
            status=StaffJob.Status.ACTIVE,
            created_by=self.staff_user,
        )

        # Resume
        self.resume = Resume.objects.create(
            job_seeker=self.candidate,
            title="Pooja_CV.pdf",
            file="resumes/pooja_cv.pdf",
        )

        # Pre-create Application in SHORTLISTED state so selection transition is valid
        self.application = JobApplication.objects.create(
            job=self.job,
            applicant=self.candidate,
            resume=self.resume,
            status=JobApplication.Status.SHORTLISTED,
        )

        self.staff_application = JobApplication.objects.create(
            staff_job=self.staff_job,
            applicant=self.candidate,
            resume=self.resume,
            status=JobApplication.Status.SHORTLISTED,
        )

        self.joining_date = date.today() + timedelta(days=30)

    def test_1_successful_selection_updates_status_and_creates_records(self):
        """TEST 1: Selection updates status to SELECTED and creates CandidateSelection and OfferDetails records."""
        app = self.service.move_status(
            self.application,
            new_status=JobApplication.Status.SELECTED,
            changed_by=self.recruiter_user,
            monthly_salary=100000,
            annual_ctc=1200000,
            joining_date=self.joining_date,
        )
        self.assertEqual(app.status, JobApplication.Status.SELECTED)
        self.assertTrue(CandidateSelection.objects.filter(application=app).exists())
        self.assertTrue(OfferDetails.objects.filter(application=app).exists())

    def test_2_selected_email_scheduled_exactly_once(self):
        """TEST 2: Exactly one 'selected' email is scheduled on selection."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.move_status(
                self.application,
                new_status=JobApplication.Status.SELECTED,
                changed_by=self.recruiter_user,
            )
            calls = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "selected"]
            self.assertEqual(len(calls), 1)

    def test_3_recipient_email_matches_candidate(self):
        """TEST 3: to_email == candidate.email."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.move_status(
                self.application,
                new_status=JobApplication.Status.SELECTED,
                changed_by=self.recruiter_user,
            )
            call = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "selected"][0]
            self.assertEqual(call.kwargs["to_email"], "candidate.selected@example.com")

    def test_4_template_name_is_selected(self):
        """TEST 4: template_name == 'selected'."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.move_status(
                self.application,
                new_status=JobApplication.Status.SELECTED,
                changed_by=self.recruiter_user,
            )
            call = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "selected"][0]
            self.assertEqual(call.kwargs["template_name"], "selected")

    def test_5_subject_line_format(self):
        """TEST 5: Subject line is '[SevaJobs] 🎉 Congratulations! You have been selected'."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.move_status(
                self.application,
                new_status=JobApplication.Status.SELECTED,
                changed_by=self.recruiter_user,
            )
            call = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "selected"][0]
            self.assertEqual(call.kwargs["subject"], "[SevaJobs] 🎉 Congratulations! You have been selected")

    def test_6_7_8_9_context_variables(self):
        """TEST 6, 7, 8, 9: Context contains candidate_name, job_title, company_name, offer_package_summary, joining_date."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.move_status(
                self.application,
                new_status=JobApplication.Status.SELECTED,
                changed_by=self.recruiter_user,
                monthly_salary=100000,
                annual_ctc=1200000,
                joining_date=self.joining_date,
            )
            call = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "selected"][0]
            ctx = call.kwargs["context"]
            self.assertEqual(ctx["candidate_name"], "Pooja")
            self.assertEqual(ctx["job_title"], "Lead Backend Engineer")
            self.assertEqual(ctx["company_name"], "Zenith Soft")
            self.assertIn("1,200,000", ctx["offer_package_summary"])
            self.assertEqual(ctx["joining_date"], self.joining_date.strftime("%d %B %Y"))

    def test_10_html_template_renders_successfully(self):
        """TEST 10: selected.html renders successfully."""
        context = {
            "candidate_name": "Pooja",
            "job_title": "Lead Backend Engineer",
            "company_name": "Zenith Soft",
            "offer_package_summary": "₹1,200,000 CTC / ₹100,000 monthly",
            "joining_date": self.joining_date.strftime("%d %B %Y"),
            "frontend_url": "https://sevajobs.in",
        }
        content = render_to_string("emails/selected.html", context)
        self.assertIn("Pooja", content)
        self.assertIn("Lead Backend Engineer", content)
        self.assertIn("Zenith Soft", content)
        self.assertIn("₹1,200,000 CTC", content)
        self.assertIn("https://sevajobs.in/dashboard/seeker/offers", content)

    def test_11_txt_template_renders_successfully(self):
        """TEST 11: selected.txt renders successfully."""
        context = {
            "candidate_name": "Pooja",
            "job_title": "Lead Backend Engineer",
            "company_name": "Zenith Soft",
            "offer_package_summary": "₹1,200,000 CTC / ₹100,000 monthly",
            "joining_date": self.joining_date.strftime("%d %B %Y"),
            "frontend_url": "https://sevajobs.in",
        }
        content = render_to_string("emails/selected.txt", context)
        self.assertIn("Pooja", content)
        self.assertIn("Lead Backend Engineer", content)
        self.assertIn("Zenith Soft", content)
        self.assertIn("https://sevajobs.in/dashboard/seeker/offers", content)

    def test_12_internal_notification_created_for_candidate(self):
        """TEST 12: Candidate receives internal in-app selection notification."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.SELECTED,
            changed_by=self.recruiter_user,
        )
        notif = Notification.objects.filter(
            recipient=self.candidate,
            notification_type=Notification.Type.APPLICATION_SELECTED,
        ).first()
        self.assertIsNotNone(notif)
        self.assertIn("selected", notif.title.lower())

    def test_13_application_history_recorded(self):
        """TEST 13: Transition to SELECTED recorded in ApplicationStatusHistory."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.SELECTED,
            changed_by=self.recruiter_user,
        )
        history = ApplicationStatusHistory.objects.filter(
            application=self.application,
            to_status=JobApplication.Status.SELECTED,
        ).first()
        self.assertIsNotNone(history)
        self.assertEqual(history.changed_by, self.recruiter_user)

    def test_14_valid_status_transition_succeeds(self):
        """TEST 14: Transitioning from SHORTLISTED to SELECTED is valid and succeeds."""
        self.assertEqual(self.application.status, JobApplication.Status.SHORTLISTED)
        app = self.service.move_status(
            self.application,
            new_status=JobApplication.Status.SELECTED,
            changed_by=self.recruiter_user,
        )
        self.assertEqual(app.status, JobApplication.Status.SELECTED)

    def test_15_invalid_status_transition_fails(self):
        """TEST 15: Direct transition from APPLIED to SELECTED fails with ValidationError."""
        fresh_app = JobApplication.objects.create(
            job=self.job,
            applicant=User.objects.create_user(
                email="fresh.candidate2@example.com",
                password="Password123!",
                role=User.Role.JOB_SEEKER,
            ),
            resume=self.resume,
            status=JobApplication.Status.APPLIED,
        )

        with patch.object(EmailService, "send_template_email") as mock_send:
            with self.assertRaises(ValidationError) as cm:
                self.service.move_status(
                    fresh_app,
                    new_status=JobApplication.Status.SELECTED,
                    changed_by=self.recruiter_user,
                )
            self.assertIn("Cannot move from 'applied' to 'selected'", str(cm.exception))
            mock_send.assert_not_called()

    def test_16_unauthorized_recruiter_blocked(self):
        """TEST 16: Unauthorized recruiter cannot select candidate from another company."""
        self.client.force_login(self.other_recruiter_user, backend="django.contrib.auth.backends.ModelBackend")
        response = self.client.post(
            f"/dashboard/recruiter/applications/{self.application.id}/",
            {
                "action": "selected",
                "monthly_salary": "80000",
                "annual_ctc": "960000",
            },
        )
        self.assertEqual(response.status_code, 404)
        self.application.refresh_from_db()
        self.assertNotEqual(self.application.status, JobApplication.Status.SELECTED)

    def test_17_transaction_rollback_prevents_selected_email(self):
        """TEST 17: Force transaction rollback prevents selected email Celery task execution."""
        from apps.notifications.tasks import send_transactional_email_task
        with patch.object(send_transactional_email_task, "delay") as mock_task:
            try:
                with transaction.atomic():
                    self.service.move_status(
                        self.application,
                        new_status=JobApplication.Status.SELECTED,
                        changed_by=self.recruiter_user,
                    )
                    raise DatabaseError("Simulated DB failure")
            except DatabaseError:
                pass

            mock_task.assert_not_called()

    def test_18_transaction_commit_enqueues_selected_email(self):
        """TEST 18: Successful transaction commit enqueues selected email Celery task."""
        from apps.notifications.tasks import send_transactional_email_task
        with patch.object(send_transactional_email_task, "delay") as mock_task:
            self.service.move_status(
                self.application,
                new_status=JobApplication.Status.SELECTED,
                changed_by=self.recruiter_user,
            )
            self.assertTrue(mock_task.called)

    def test_19_idempotency_key_format(self):
        """TEST 19: Verify idempotency key format app_status:<application.id>:selected."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.move_status(
                self.application,
                new_status=JobApplication.Status.SELECTED,
                changed_by=self.recruiter_user,
            )
            call = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "selected"][0]
            self.assertEqual(call.kwargs["idempotency_key"], f"app_status:{self.application.id}:selected")

    def test_20_duplicate_selection_attempt_fails(self):
        """TEST 20: Repeating selection on already SELECTED application fails with ValidationError, no second email."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.SELECTED,
            changed_by=self.recruiter_user,
        )

        with patch.object(EmailService, "send_template_email") as mock_send:
            with self.assertRaises(ValidationError) as cm:
                self.service.move_status(
                    self.application,
                    new_status=JobApplication.Status.SELECTED,
                    changed_by=self.recruiter_user,
                )
            self.assertIn("already in this status", str(cm.exception))
            mock_send.assert_not_called()

    def test_21_selected_and_joined_statuses_remain_strictly_separated(self):
        """TEST 21: Selecting a candidate schedules selected email but DOES NOT set JOINED or send joining email."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            app = self.service.move_status(
                self.application,
                new_status=JobApplication.Status.SELECTED,
                changed_by=self.recruiter_user,
            )
            self.assertEqual(app.status, JobApplication.Status.SELECTED)
            self.assertNotEqual(app.status, JobApplication.Status.JOINED)

            template_names = [c.kwargs.get("template_name") for c in mock_send.call_args_list]
            self.assertIn("selected", template_names)
            self.assertNotIn("joining", template_names)

    def test_22_normal_job_title_and_company_rendered(self):
        """TEST 22: Normal job title and company name rendered correctly."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.move_status(
                self.application,
                new_status=JobApplication.Status.SELECTED,
                changed_by=self.recruiter_user,
            )
            call = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "selected"][0]
            ctx = call.kwargs["context"]
            self.assertEqual(ctx["job_title"], "Lead Backend Engineer")
            self.assertEqual(ctx["company_name"], "Zenith Soft")

    def test_23_staff_job_designation_and_institution_rendered(self):
        """TEST 23: Staff job designation and organization name rendered correctly."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.move_status(
                self.staff_application,
                new_status=JobApplication.Status.SELECTED,
                changed_by=self.staff_user,
            )
            call = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "selected"][0]
            ctx = call.kwargs["context"]
            self.assertEqual(ctx["job_title"], "Principal Accountant")
            self.assertEqual(ctx["company_name"], "Zenith Financials")

    def test_24_web_ui_select_candidate_reaches_service_and_schedules_email(self):
        """TEST 24: Recruiter Web UI action='selected' reaches service and schedules selected email."""
        self.client.force_login(self.recruiter_user, backend="django.contrib.auth.backends.ModelBackend")
        session = self.client.session
        session["current_role_scope"] = "recruiter"
        session.save()
        self.client.cookies["sessionid"] = session.session_key

        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            response = self.client.post(
                f"/dashboard/recruiter/applications/{self.application.id}/",
                {
                    "action": "selected",
                    "monthly_salary": "120000",
                    "annual_ctc": "1440000",
                    "joining_date": self.joining_date.strftime("%Y-%m-%d"),
                },
            )
            self.assertEqual(response.status_code, 302)
            self.application.refresh_from_db()
            self.assertEqual(self.application.status, JobApplication.Status.SELECTED)

            calls = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "selected"]
            self.assertEqual(len(calls), 1)

    def test_25_api_status_change_reaches_service_and_schedules_email(self):
        """TEST 25: DRF API status change endpoint reaches service and schedules selected email."""
        self.api_client.force_authenticate(user=self.recruiter_user)
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            response = self.api_client.post(
                f"/api/v1/applications/{self.application.id}/status/",
                {
                    "status": "selected",
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.application.refresh_from_db()
            self.assertEqual(self.application.status, JobApplication.Status.SELECTED)

            calls = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "selected"]
            self.assertEqual(len(calls), 1)

    def test_26_cta_url_points_to_valid_candidate_dashboard_route(self):
        """TEST 26: CTA button links to /dashboard/seeker/offers."""
        context = {
            "candidate_name": "Pooja",
            "job_title": "Lead Backend Engineer",
            "company_name": "Zenith Soft",
            "frontend_url": "https://sevajobs.in",
        }
        content = render_to_string("emails/selected.html", context)
        self.assertIn("https://sevajobs.in/dashboard/seeker/offers", content)
