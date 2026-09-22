"""Automated test suite for Recruiter New Application transactional email flow."""

from unittest.mock import patch
from django.test import TestCase, override_settings, Client
from django.contrib.auth import get_user_model
from django.db import transaction, DatabaseError
from django.template.loader import render_to_string
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework import status

from apps.jobs.models import Job, Company, StaffJob
from apps.recruiters.models import RecruiterProfile
from apps.applications.models import JobApplication, Resume
from apps.applications.services import ApplicationService
from apps.notifications.email_service import EmailService
from apps.notifications.models import Notification

User = get_user_model()


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_STORE_EAGER_RESULT=False,
    FRONTEND_URL="https://sevajobs.in",
)
class RecruiterNewApplicationEmailTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.api_client = APIClient()
        self.service = ApplicationService()

        # Job Seeker User (email verified)
        self.seeker_user = User.objects.create_user(
            email="sai.seeker@example.com",
            password="Password123!",
            first_name="Sai",
            last_name="Kumar",
            phone="9876543210",
            is_email_verified=True,
            role=User.Role.JOB_SEEKER,
        )

        # Recruiter User & Profile
        self.recruiter_user = User.objects.create_user(
            email="recruiter.owner@example.com",
            password="Password123!",
            first_name="Vikram",
            last_name="Rathore",
            is_email_verified=True,
            role=User.Role.RECRUITER,
        )

        self.company = Company.objects.create(
            name="TechCorp India",
            website="https://techcorp.in",
        )

        self.recruiter_profile, _ = RecruiterProfile.objects.get_or_create(
            user=self.recruiter_user,
            defaults={"company": self.company, "designation": "Hiring Manager"}
        )

        # Staff User
        self.staff_user = User.objects.create_user(
            email="staff.owner@example.com",
            password="Password123!",
            first_name="Suresh",
            last_name="Patel",
            is_email_verified=True,
            role=User.Role.STAFF,
            is_staff=True,
        )

        # Active Normal Job
        self.job = Job.objects.create(
            title="Python Developer",
            company=self.company,
            recruiter=self.recruiter_profile,
            status=Job.Status.ACTIVE,
            job_type="full_time",
            experience_level="mid",
            applications_count=0,
        )

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
            title="Sai_Kumar_Resume.pdf",
            file="resumes/sai_cv.pdf",
        )

        # Other Seeker and Resume (for wrong resume test)
        self.other_seeker = User.objects.create_user(
            email="other.seeker2@example.com",
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

    def test_1_normal_job_application_creates_single_job_application(self):
        """TEST 1: Successful application creates exactly one JobApplication."""
        application = self.service.submit(
            job=self.job,
            applicant=self.seeker_user,
            resume=self.seeker_resume,
            cover_letter="Cover letter text",
            expected_salary=600000,
        )
        self.assertIsNotNone(application.id)
        self.assertEqual(JobApplication.objects.filter(job=self.job, applicant=self.seeker_user).count(), 1)

    def test_2_recruiter_email_scheduled_exactly_once(self):
        """TEST 2: Verify exactly one recruiter_new_application email is scheduled."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.submit(
                job=self.job,
                applicant=self.seeker_user,
                resume=self.seeker_resume,
            )
            rec_calls = [
                c for c in mock_send.call_args_list
                if c.kwargs.get("template_name") == "recruiter_new_application"
            ]
            self.assertEqual(len(rec_calls), 1)

    def test_3_correct_recruiter_recipient_email(self):
        """TEST 3: Verify recipient matches recruiter_user.email."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.submit(
                job=self.job,
                applicant=self.seeker_user,
                resume=self.seeker_resume,
            )
            rec_call = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "recruiter_new_application"][0]
            self.assertEqual(rec_call.kwargs["to_email"], "recruiter.owner@example.com")

    def test_4_correct_recruiter_email_subject(self):
        """TEST 4: Verify subject is 'New Application: <Candidate Full Name> for <Job Title>'."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.submit(
                job=self.job,
                applicant=self.seeker_user,
                resume=self.seeker_resume,
            )
            rec_call = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "recruiter_new_application"][0]
            self.assertEqual(rec_call.kwargs["subject"], "New Application: Sai Kumar for Python Developer")

    def test_5_correct_recruiter_email_template_name(self):
        """TEST 5: Verify template_name == 'recruiter_new_application'."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.submit(
                job=self.job,
                applicant=self.seeker_user,
                resume=self.seeker_resume,
            )
            rec_call = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "recruiter_new_application"][0]
            self.assertEqual(rec_call.kwargs["template_name"], "recruiter_new_application")

    def test_6_recruiter_email_context_fields(self):
        """TEST 6: Verify context contains recruiter_name, job_title, applicant_name, applicant_email, applicant_phone, expected_salary, application_url."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.submit(
                job=self.job,
                applicant=self.seeker_user,
                resume=self.seeker_resume,
                expected_salary=750000,
            )
            rec_call = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "recruiter_new_application"][0]
            ctx = rec_call.kwargs["context"]
            self.assertEqual(ctx["recruiter_name"], "Vikram")
            self.assertEqual(ctx["job_title"], "Python Developer")
            self.assertEqual(ctx["applicant_name"], "Sai Kumar")
            self.assertEqual(ctx["applicant_email"], "sai.seeker@example.com")
            self.assertEqual(ctx["applicant_phone"], "9876543210")
            self.assertEqual(ctx["expected_salary"], 750000)
            self.assertTrue(ctx["application_url"].endswith("/dashboard/recruiter/applications"))

    def test_7_html_template_renders_successfully(self):
        """TEST 7: recruiter_new_application.html renders successfully."""
        context = {
            "recruiter_name": "Vikram",
            "job_title": "Python Developer",
            "applicant_name": "Sai Kumar",
            "applicant_email": "sai.seeker@example.com",
            "applicant_phone": "9876543210",
            "expected_salary": 750000,
            "application_url": "https://sevajobs.in/dashboard/recruiter/applications",
            "frontend_url": "https://sevajobs.in",
        }
        content = render_to_string("emails/recruiter_new_application.html", context)
        self.assertIn("Vikram", content)
        self.assertIn("Python Developer", content)
        self.assertIn("Sai Kumar", content)
        self.assertIn("sai.seeker@example.com", content)
        self.assertIn("9876543210", content)
        self.assertIn("750000", content)
        self.assertIn("https://sevajobs.in/dashboard/recruiter/applications", content)

    def test_8_txt_template_renders_successfully(self):
        """TEST 8: recruiter_new_application.txt renders successfully."""
        context = {
            "recruiter_name": "Vikram",
            "job_title": "Python Developer",
            "applicant_name": "Sai Kumar",
            "applicant_email": "sai.seeker@example.com",
            "applicant_phone": "9876543210",
            "expected_salary": 750000,
            "application_url": "https://sevajobs.in/dashboard/recruiter/applications",
            "frontend_url": "https://sevajobs.in",
        }
        content = render_to_string("emails/recruiter_new_application.txt", context)
        self.assertIn("Vikram", content)
        self.assertIn("Python Developer", content)
        self.assertIn("Sai Kumar", content)
        self.assertIn("sai.seeker@example.com", content)
        self.assertIn("750000", content)
        self.assertIn("https://sevajobs.in/dashboard/recruiter/applications", content)

    def test_9_recruiter_resolution_from_job_recruiter_user(self):
        """TEST 9: Job -> RecruiterProfile -> User resolves recipient correctly."""
        resolved_user = getattr(self.job.recruiter, "user", None)
        self.assertEqual(resolved_user, self.recruiter_user)
        self.assertEqual(resolved_user.email, "recruiter.owner@example.com")

    def test_10_candidate_email_scheduled_alongside_recruiter_email(self):
        """TEST 10: Successful application schedules candidate email alongside recruiter email."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.submit(
                job=self.job,
                applicant=self.seeker_user,
                resume=self.seeker_resume,
            )
            templates = [c.kwargs.get("template_name") for c in mock_send.call_args_list]
            self.assertIn("application_submitted", templates)
            self.assertIn("recruiter_new_application", templates)

    def test_11_internal_notification_created_for_recruiter(self):
        """TEST 11: Recruiter receives internal Notification.Type.APPLICATION_RECEIVED."""
        self.service.submit(
            job=self.job,
            applicant=self.seeker_user,
            resume=self.seeker_resume,
        )
        notif = Notification.objects.filter(
            recipient=self.recruiter_user,
            notification_type=Notification.Type.APPLICATION_RECEIVED,
        ).first()
        self.assertIsNotNone(notif)
        self.assertIn("Sai Kumar applied for Python Developer", notif.message)

    def test_12_applications_count_incremented_by_one(self):
        """TEST 12: Normal job applications_count increases by exactly 1."""
        initial_count = self.job.applications_count
        self.service.submit(
            job=self.job,
            applicant=self.seeker_user,
            resume=self.seeker_resume,
        )
        self.job.refresh_from_db()
        self.assertEqual(self.job.applications_count, initial_count + 1)

    def test_13_duplicate_application_attempt_fails_and_schedules_no_extra_emails(self):
        """TEST 13: Duplicate application attempt fails, applications_count unchanged, no duplicate emails."""
        self.service.submit(
            job=self.job,
            applicant=self.seeker_user,
            resume=self.seeker_resume,
        )
        self.job.refresh_from_db()
        count_after_first = self.job.applications_count

        with patch.object(EmailService, "send_template_email") as mock_send:
            with self.assertRaises(ValidationError):
                self.service.submit(
                    job=self.job,
                    applicant=self.seeker_user,
                    resume=self.seeker_resume,
                )
            mock_send.assert_not_called()
            self.job.refresh_from_db()
            self.assertEqual(self.job.applications_count, count_after_first)

    def test_14_inactive_job_application_rejected_no_recruiter_email(self):
        """TEST 14: Applying to non-ACTIVE job is rejected, no recruiter email scheduled."""
        self.job.status = Job.Status.CLOSED
        self.job.save()

        with patch.object(EmailService, "send_template_email") as mock_send:
            with self.assertRaises(ValidationError):
                self.service.submit(
                    job=self.job,
                    applicant=self.seeker_user,
                    resume=self.seeker_resume,
                )
            mock_send.assert_not_called()

    def test_15_wrong_resume_permission_denied_no_recruiter_email(self):
        """TEST 15: Using another user's resume raises PermissionDenied, no recruiter email scheduled."""
        with patch.object(EmailService, "send_template_email") as mock_send:
            with self.assertRaises(PermissionDenied):
                self.service.submit(
                    job=self.job,
                    applicant=self.seeker_user,
                    resume=self.other_resume,
                )
            mock_send.assert_not_called()

    def test_16_transaction_rollback_prevents_recruiter_email(self):
        """TEST 16: Force transaction rollback prevents Celery task execution for recruiter email."""
        from apps.notifications.tasks import send_transactional_email_task
        with patch.object(send_transactional_email_task, "delay") as mock_task:
            try:
                with transaction.atomic():
                    self.service.submit(
                        job=self.job,
                        applicant=self.seeker_user,
                        resume=self.seeker_resume,
                    )
                    raise DatabaseError("Simulated failure")
            except DatabaseError:
                pass

            mock_task.assert_not_called()

    def test_17_successful_transaction_commit_queues_recruiter_email(self):
        """TEST 17: Successful transaction commit enqueues Celery task."""
        from apps.notifications.tasks import send_transactional_email_task
        with patch.object(send_transactional_email_task, "delay") as mock_task:
            self.service.submit(
                job=self.job,
                applicant=self.seeker_user,
                resume=self.seeker_resume,
            )
            # Task delay called after atomic block exits
            self.assertTrue(mock_task.called)

    def test_18_recruiter_email_idempotency_key_format(self):
        """TEST 18: Normal recruiter email uses idempotency_key=f'app_rec:{application.id}'."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            app = self.service.submit(
                job=self.job,
                applicant=self.seeker_user,
                resume=self.seeker_resume,
            )
            rec_call = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "recruiter_new_application"][0]
            self.assertEqual(rec_call.kwargs["idempotency_key"], f"app_rec:{app.id}")

    def test_19_staff_job_application_schedules_recruiter_email_to_staff_owner(self):
        """TEST 19: Staff Job application emails staff owner with app_staff:<id> idempotency key."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            app = self.service.submit(
                staff_job=self.staff_job,
                applicant=self.seeker_user,
                resume=self.seeker_resume,
            )
            rec_call = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "recruiter_new_application"][0]
            self.assertEqual(rec_call.kwargs["to_email"], "staff.owner@example.com")
            self.assertEqual(rec_call.kwargs["subject"], "New Application: Sai Kumar for Senior Accountant")
            self.assertEqual(rec_call.kwargs["idempotency_key"], f"app_staff:{app.id}")
            self.assertTrue(rec_call.kwargs["context"]["application_url"].endswith("/staff/dashboard/applications"))

    def test_20_missing_optional_candidate_info_renders_cleanly(self):
        """TEST 20: Missing candidate phone/expected_salary renders without exceptions or ugly None text."""
        self.seeker_user.phone = ""
        self.seeker_user.save()

        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.submit(
                job=self.job,
                applicant=self.seeker_user,
                resume=self.seeker_resume,
                expected_salary=None,
            )
            rec_call = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "recruiter_new_application"][0]
            ctx = rec_call.kwargs["context"]

            html_rendered = render_to_string("emails/recruiter_new_application.html", ctx)
            txt_rendered = render_to_string("emails/recruiter_new_application.txt", ctx)

            self.assertNotIn("None", html_rendered)
            self.assertNotIn("None", txt_rendered)

    def test_21_web_ui_apply_schedules_recruiter_email(self):
        """TEST 21: Real Web UI Apply flow invokes central service and schedules recruiter email."""
        self.client.force_login(self.seeker_user, backend="django.contrib.auth.backends.ModelBackend")
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            response = self.client.post(
                f"/jobs/{self.job.id}/apply/",
                {
                    "resume_id": self.seeker_resume.id,
                    "cover_letter": "Web UI apply recruiter email test",
                },
            )
            self.assertEqual(response.status_code, 302)
            rec_calls = [
                c for c in mock_send.call_args_list
                if c.kwargs.get("template_name") == "recruiter_new_application"
            ]
            self.assertEqual(len(rec_calls), 1)

    def test_22_api_apply_schedules_recruiter_email(self):
        """TEST 22: Real DRF API Apply flow invokes central service and schedules recruiter email."""
        self.api_client.force_authenticate(user=self.seeker_user)
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            response = self.api_client.post(
                f"/api/v1/jobs/{self.job.id}/apply/",
                {
                    "resume_id": self.seeker_resume.id,
                    "cover_letter": "API apply recruiter email test",
                },
                format="json",
            )
            self.assertIn(response.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])
            rec_calls = [
                c for c in mock_send.call_args_list
                if c.kwargs.get("template_name") == "recruiter_new_application"
            ]
            self.assertEqual(len(rec_calls), 1)
