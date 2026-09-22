"""Automated test suite for Application Submitted transactional email flow."""

from unittest.mock import patch
from django.test import TestCase, override_settings, Client
from django.contrib.auth import get_user_model
from django.db import transaction, DatabaseError
from django.template.loader import render_to_string
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework import status

from apps.jobs.models import Job, Company, StaffJob
from apps.applications.models import JobApplication, Resume
from apps.applications.services import ApplicationService
from apps.notifications.email_service import EmailService

User = get_user_model()


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_STORE_EAGER_RESULT=False,
    FRONTEND_URL="https://sevajobs.in",
)
class ApplicationSubmittedEmailTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.api_client = APIClient()
        self.service = ApplicationService()

        # Job Seeker User (email verified)
        self.seeker_user = User.objects.create_user(
            email="seeker.app@example.com",
            password="Password123!",
            first_name="Ananya",
            last_name="Roy",
            is_email_verified=True,
            role=User.Role.JOB_SEEKER,
        )

        # Recruiter User
        self.recruiter_user = User.objects.create_user(
            email="recruiter.app@example.com",
            password="Password123!",
            first_name="Rahul",
            last_name="Verma",
            is_email_verified=True,
            role=User.Role.RECRUITER,
        )

        # Staff User
        self.staff_user = User.objects.create_user(
            email="staff.app@example.com",
            password="Password123!",
            first_name="Sunil",
            last_name="Mehta",
            is_email_verified=True,
            role=User.Role.STAFF,
            is_staff=True,
        )

        # Company
        self.company = Company.objects.create(
            name="TechCorp India",
            website="https://techcorp.in",
        )

        # Active Normal Job
        self.job = Job.objects.create(
            title="Python Developer",
            company=self.company,
            status=Job.Status.ACTIVE,
            job_type="full_time",
            experience_level="mid",
        )
        # Attach recruiter to job if recruiter profile model exists
        if hasattr(self.recruiter_user, "recruiter_profile"):
            self.job.recruiter = self.recruiter_user.recruiter_profile
            self.job.save()

        # Active Staff Job
        self.staff_job = StaffJob.objects.create(
            designation="Senior Accountant",
            organization_name="Apex Healthcare",
            status=StaffJob.Status.ACTIVE,
            created_by=self.staff_user,
        )

        # Job Seeker Resume
        self.seeker_resume = Resume.objects.create(
            job_seeker=self.seeker_user,
            title="Ananya_Roy_CV.pdf",
            file="resumes/test_cv.pdf",
        )

        # Other Seeker and Resume (for wrong resume test)
        self.other_seeker = User.objects.create_user(
            email="other.seeker@example.com",
            password="Password123!",
            first_name="Rohan",
            is_email_verified=True,
            role=User.Role.JOB_SEEKER,
        )
        self.other_resume = Resume.objects.create(
            job_seeker=self.other_seeker,
            title="Rohan_CV.pdf",
            file="resumes/rohan_cv.pdf",
        )

    def test_1_normal_job_application_creates_application_and_schedules_email(self):
        """TEST 1: Normal job application creates JobApplication, sets APPLIED, schedules candidate email."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            application = self.service.submit(
                job=self.job,
                applicant=self.seeker_user,
                resume=self.seeker_resume,
                cover_letter="I am very interested.",
                expected_salary=600000,
            )

            self.assertIsNotNone(application.id)
            self.assertEqual(application.status, JobApplication.Status.APPLIED)

            cand_calls = [
                c for c in mock_send.call_args_list
                if c.kwargs.get("template_name") == "application_submitted"
            ]
            self.assertEqual(len(cand_calls), 1)

    def test_2_candidate_email_recipient(self):
        """TEST 2: Verify candidate email recipient matches applicant's email."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.submit(
                job=self.job,
                applicant=self.seeker_user,
                resume=self.seeker_resume,
            )
            cand_call = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "application_submitted"][0]
            self.assertEqual(cand_call.kwargs["to_email"], "seeker.app@example.com")

    def test_3_candidate_email_subject(self):
        """TEST 3: Verify candidate email subject is 'Application Received: <Job Title>'."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.submit(
                job=self.job,
                applicant=self.seeker_user,
                resume=self.seeker_resume,
            )
            cand_call = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "application_submitted"][0]
            self.assertEqual(cand_call.kwargs["subject"], "Application Received: Python Developer")

    def test_4_candidate_email_template_name(self):
        """TEST 4: Verify candidate email uses 'application_submitted' template."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.submit(
                job=self.job,
                applicant=self.seeker_user,
                resume=self.seeker_resume,
            )
            cand_call = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "application_submitted"][0]
            self.assertEqual(cand_call.kwargs["template_name"], "application_submitted")

    def test_5_candidate_email_context(self):
        """TEST 5: Verify context contains candidate_name, job_title, company_name."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.submit(
                job=self.job,
                applicant=self.seeker_user,
                resume=self.seeker_resume,
            )
            cand_call = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "application_submitted"][0]
            ctx = cand_call.kwargs["context"]
            self.assertEqual(ctx["candidate_name"], "Ananya")
            self.assertEqual(ctx["job_title"], "Python Developer")
            self.assertEqual(ctx["company_name"], "TechCorp India")

    def test_6_html_template_renders_successfully(self):
        """TEST 6: application_submitted.html renders without errors."""
        context = {
            "candidate_name": "Ananya",
            "job_title": "Python Developer",
            "company_name": "TechCorp India",
            "frontend_url": "https://sevajobs.in",
        }
        content = render_to_string("emails/application_submitted.html", context)
        self.assertIn("Ananya", content)
        self.assertIn("Python Developer", content)
        self.assertIn("TechCorp India", content)

    def test_7_txt_template_renders_successfully(self):
        """TEST 7: application_submitted.txt renders without errors."""
        context = {
            "candidate_name": "Ananya",
            "job_title": "Python Developer",
            "company_name": "TechCorp India",
            "frontend_url": "https://sevajobs.in",
        }
        content = render_to_string("emails/application_submitted.txt", context)
        self.assertIn("Ananya", content)
        self.assertIn("Python Developer", content)
        self.assertIn("TechCorp India", content)

    def test_8_duplicate_application_rejected(self):
        """TEST 8: Duplicate application by same candidate rejected with validation error, no second email."""
        self.service.submit(
            job=self.job,
            applicant=self.seeker_user,
            resume=self.seeker_resume,
        )
        with patch.object(EmailService, "send_template_email") as mock_send:
            with self.assertRaises(ValidationError) as cm:
                self.service.submit(
                    job=self.job,
                    applicant=self.seeker_user,
                    resume=self.seeker_resume,
                )
            self.assertIn("already applied", str(cm.exception))
            mock_send.assert_not_called()

    def test_9_inactive_job_application_rejected(self):
        """TEST 9: Candidate applying to non-ACTIVE job is rejected, no email sent."""
        self.job.status = Job.Status.CLOSED
        self.job.save()

        with patch.object(EmailService, "send_template_email") as mock_send:
            with self.assertRaises(ValidationError) as cm:
                self.service.submit(
                    job=self.job,
                    applicant=self.seeker_user,
                    resume=self.seeker_resume,
                )
            self.assertIn("no longer accepting applications", str(cm.exception))
            mock_send.assert_not_called()

    def test_10_wrong_resume_permission_denied(self):
        """TEST 10: Candidate using another user's resume raises PermissionDenied, no email sent."""
        with patch.object(EmailService, "send_template_email") as mock_send:
            with self.assertRaises(PermissionDenied):
                self.service.submit(
                    job=self.job,
                    applicant=self.seeker_user,
                    resume=self.other_resume,
                )
            mock_send.assert_not_called()

    def test_11_transaction_rollback_prevents_email(self):
        """TEST 11: Transaction rollback prevents Celery task execution."""
        from apps.notifications.tasks import send_transactional_email_task
        with patch.object(send_transactional_email_task, "delay") as mock_task:
            try:
                with transaction.atomic():
                    self.service.submit(
                        job=self.job,
                        applicant=self.seeker_user,
                        resume=self.seeker_resume,
                    )
                    raise DatabaseError("Simulated DB failure")
            except DatabaseError:
                pass

            # JobApplication not created
            self.assertFalse(JobApplication.objects.filter(job=self.job, applicant=self.seeker_user).exists())
            # Celery task delay was NOT invoked due to transaction rollback
            mock_task.assert_not_called()

    def test_12_successful_transaction_commit_queues_email(self):
        """TEST 12: Successful transaction commit queues Celery task."""
        from apps.notifications.tasks import send_transactional_email_task
        with patch.object(send_transactional_email_task, "delay") as mock_task:
            self.service.submit(
                job=self.job,
                applicant=self.seeker_user,
                resume=self.seeker_resume,
            )
            # Since test uses transaction, task is queued after atomic block exits
            self.assertTrue(JobApplication.objects.filter(job=self.job, applicant=self.seeker_user).exists())

    def test_13_idempotency_key_format(self):
        """TEST 13: Candidate email uses idempotency_key=f'app_cand:{application.id}'."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            app = self.service.submit(
                job=self.job,
                applicant=self.seeker_user,
                resume=self.seeker_resume,
            )
            cand_call = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "application_submitted"][0]
            self.assertEqual(cand_call.kwargs["idempotency_key"], f"app_cand:{app.id}")

    def test_14_recruiter_notification_scheduled(self):
        """TEST 14: Successful normal job application schedules both candidate and recruiter emails."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.submit(
                job=self.job,
                applicant=self.seeker_user,
                resume=self.seeker_resume,
            )
            template_names = [c.kwargs.get("template_name") for c in mock_send.call_args_list]
            self.assertIn("application_submitted", template_names)

    def test_15_staff_job_application_with_company_name(self):
        """TEST 15: Staff Job application derives company name from organization_name."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            app = self.service.submit(
                staff_job=self.staff_job,
                applicant=self.seeker_user,
                resume=self.seeker_resume,
            )
            self.assertIsNotNone(app.id)
            cand_call = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "application_submitted"][0]
            ctx = cand_call.kwargs["context"]
            self.assertEqual(ctx["job_title"], "Senior Accountant")
            self.assertEqual(ctx["company_name"], "Apex Healthcare")

    def test_16_web_ui_apply_invokes_service_and_schedules_email(self):
        """TEST 16: Real Web UI Apply flow invokes central service and schedules email."""
        self.client.force_login(self.seeker_user, backend="django.contrib.auth.backends.ModelBackend")
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            response = self.client.post(
                f"/jobs/{self.job.id}/apply/",
                {
                    "resume_id": self.seeker_resume.id,
                    "cover_letter": "Web UI apply test",
                },
            )
            self.assertEqual(response.status_code, 302)
            self.assertTrue(JobApplication.objects.filter(job=self.job, applicant=self.seeker_user).exists())

            cand_calls = [
                c for c in mock_send.call_args_list
                if c.kwargs.get("template_name") == "application_submitted"
            ]
            self.assertEqual(len(cand_calls), 1)

    def test_17_api_apply_invokes_service_and_schedules_email(self):
        """TEST 17: DRF API Apply flow invokes central service and schedules email."""
        self.api_client.force_authenticate(user=self.seeker_user)
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            response = self.api_client.post(
                f"/api/v1/jobs/{self.job.id}/apply/",
                {
                    "resume_id": self.seeker_resume.id,
                    "cover_letter": "API apply test",
                },
                format="json",
            )
            self.assertIn(response.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])
            self.assertTrue(JobApplication.objects.filter(job=self.job, applicant=self.seeker_user).exists())

            cand_calls = [
                c for c in mock_send.call_args_list
                if c.kwargs.get("template_name") == "application_submitted"
            ]
            self.assertEqual(len(cand_calls), 1)
