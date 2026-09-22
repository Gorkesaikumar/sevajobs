"""Automated test suite for Interview Scheduled transactional email flow."""

from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase, override_settings, Client
from django.contrib.auth import get_user_model
from django.db import transaction, DatabaseError
from django.template.loader import render_to_string
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework import status

from apps.jobs.models import Job, Company
from apps.recruiters.models import RecruiterProfile
from apps.applications.models import JobApplication, Resume, ApplicationStatusHistory
from apps.applications.services import ApplicationService
from apps.notifications.email_service import EmailService
from apps.notifications.models import Notification

User = get_user_model()


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_STORE_EAGER_RESULT=False,
    FRONTEND_URL="https://sevajobs.in",
    TIME_ZONE="Asia/Kolkata",
    USE_TZ=True,
)
class InterviewScheduledEmailTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.api_client = APIClient()
        self.service = ApplicationService()

        # Job Seeker (Candidate)
        self.candidate = User.objects.create_user(
            email="candidate.interview@example.com",
            password="Password123!",
            first_name="Ananya",
            last_name="Sharma",
            phone="9876543210",
            is_email_verified=True,
            role=User.Role.JOB_SEEKER,
        )

        # Recruiter
        self.recruiter_user = User.objects.create_user(
            email="recruiter.interview@example.com",
            password="Password123!",
            first_name="Rajesh",
            last_name="Verma",
            is_email_verified=True,
            role=User.Role.RECRUITER,
        )

        self.company = Company.objects.create(
            name="Apex Tech",
            website="https://apextech.in",
        )

        self.recruiter_profile, _ = RecruiterProfile.objects.get_or_create(
            user=self.recruiter_user,
            defaults={"company": self.company, "designation": "Talent Lead"}
        )

        # Unauthorized Recruiter
        self.other_recruiter_user = User.objects.create_user(
            email="other.recruiter@example.com",
            password="Password123!",
            first_name="Other",
            last_name="Manager",
            is_email_verified=True,
            role=User.Role.RECRUITER,
        )
        self.other_company = Company.objects.create(name="Other Corp")
        self.other_profile, _ = RecruiterProfile.objects.get_or_create(
            user=self.other_recruiter_user,
            defaults={"company": self.other_company, "designation": "HR"}
        )

        # Active Job
        self.job = Job.objects.create(
            title="Senior React Developer",
            company=self.company,
            recruiter=self.recruiter_profile,
            status=Job.Status.ACTIVE,
            job_type="full_time",
            experience_level="mid",
        )

        # Resume
        self.resume = Resume.objects.create(
            job_seeker=self.candidate,
            title="Ananya_CV.pdf",
            file="resumes/ananya_cv.pdf",
        )

        # Pre-create Application in SHORTLISTED state so interview transition is valid
        self.application = JobApplication.objects.create(
            job=self.job,
            applicant=self.candidate,
            resume=self.resume,
            status=JobApplication.Status.SHORTLISTED,
        )

        # Interview Datetime (2 days from now at 11:00 AM)
        self.interview_dt = timezone.now() + timedelta(days=2)
        self.interview_dt = self.interview_dt.replace(hour=11, minute=0, second=0, microsecond=0)

    def test_1_valid_recruiter_schedules_interview_sets_status(self):
        """TEST 1: Scheduling interview updates status to INTERVIEW_SCHEDULED."""
        app = self.service.move_status(
            self.application,
            new_status=JobApplication.Status.INTERVIEW_SCHEDULED,
            changed_by=self.recruiter_user,
            interview_at=self.interview_dt,
            interview_mode="video",
            interview_type="online",
            interviewer_name="Rajesh Verma",
            meeting_link="https://meet.sevajobs.in/room-123",
        )
        self.assertEqual(app.status, JobApplication.Status.INTERVIEW_SCHEDULED)
        self.assertEqual(app.interview_at, self.interview_dt)

    def test_2_interview_scheduled_email_scheduled_exactly_once(self):
        """TEST 2: Exactly one interview_scheduled email is scheduled."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.move_status(
                self.application,
                new_status=JobApplication.Status.INTERVIEW_SCHEDULED,
                changed_by=self.recruiter_user,
                interview_at=self.interview_dt,
                interview_mode="video",
            )
            calls = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "interview_scheduled"]
            self.assertEqual(len(calls), 1)

    def test_3_recipient_email_matches_candidate(self):
        """TEST 3: to_email == candidate.email."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.move_status(
                self.application,
                new_status=JobApplication.Status.INTERVIEW_SCHEDULED,
                changed_by=self.recruiter_user,
                interview_at=self.interview_dt,
            )
            call = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "interview_scheduled"][0]
            self.assertEqual(call.kwargs["to_email"], "candidate.interview@example.com")

    def test_4_template_name_is_interview_scheduled(self):
        """TEST 4: template_name == 'interview_scheduled'."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.move_status(
                self.application,
                new_status=JobApplication.Status.INTERVIEW_SCHEDULED,
                changed_by=self.recruiter_user,
                interview_at=self.interview_dt,
            )
            call = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "interview_scheduled"][0]
            self.assertEqual(call.kwargs["template_name"], "interview_scheduled")

    def test_5_subject_contains_seva_jobs_tag_and_title(self):
        """TEST 5: Subject line format is '[SevaJobs] Interview Scheduled — <Job Title>'."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.move_status(
                self.application,
                new_status=JobApplication.Status.INTERVIEW_SCHEDULED,
                changed_by=self.recruiter_user,
                interview_at=self.interview_dt,
            )
            call = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "interview_scheduled"][0]
            self.assertEqual(call.kwargs["subject"], "[SevaJobs] Interview Scheduled — Senior React Developer")

    def test_6_7_8_context_candidate_job_company(self):
        """TEST 6, 7, 8: Context contains candidate_name, job_title, company_name."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.move_status(
                self.application,
                new_status=JobApplication.Status.INTERVIEW_SCHEDULED,
                changed_by=self.recruiter_user,
                interview_at=self.interview_dt,
            )
            call = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "interview_scheduled"][0]
            ctx = call.kwargs["context"]
            self.assertEqual(ctx["candidate_name"], "Ananya")
            self.assertEqual(ctx["job_title"], "Senior React Developer")
            self.assertEqual(ctx["company_name"], "Apex Tech")

    def test_9_date_time_context_formatting(self):
        """TEST 9: Email context contains formatted interview date/time with local timezone."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.move_status(
                self.application,
                new_status=JobApplication.Status.INTERVIEW_SCHEDULED,
                changed_by=self.recruiter_user,
                interview_at=self.interview_dt,
            )
            call = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "interview_scheduled"][0]
            ctx = call.kwargs["context"]
            self.assertEqual(ctx["interview_date"], self.interview_dt.strftime("%Y-%m-%d"))
            self.assertEqual(ctx["interview_time_display"], "11:00 AM")

    def test_10_11_12_interview_mode_location_and_link(self):
        """TEST 10, 11, 12: Correct mode display, location, and meeting link appear in context."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.move_status(
                self.application,
                new_status=JobApplication.Status.INTERVIEW_SCHEDULED,
                changed_by=self.recruiter_user,
                interview_at=self.interview_dt,
                interview_mode="video",
                interview_type="online",
                interviewer_name="Rajesh Verma",
                meeting_link="https://meet.sevajobs.in/room-xyz",
                interview_location="Online Room 4",
            )
            call = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "interview_scheduled"][0]
            ctx = call.kwargs["context"]
            self.assertEqual(ctx["interview_mode_display"], "Video Call")
            self.assertEqual(ctx["interviewer_name"], "Rajesh Verma")
            self.assertEqual(ctx["meeting_link"], "https://meet.sevajobs.in/room-xyz")
            self.assertEqual(ctx["interview_location"], "Online Room 4")

    def test_13_html_template_renders_successfully(self):
        """TEST 13: interview_scheduled.html renders successfully."""
        local_when = timezone.localtime(self.interview_dt) if timezone.is_aware(self.interview_dt) else self.interview_dt
        context = {
            "candidate_name": "Ananya",
            "job_title": "Senior React Developer",
            "company_name": "Apex Tech",
            "interview_date_display": local_when.strftime("%A, %d %B %Y"),
            "interview_time_display": local_when.strftime("%I:%M %p"),
            "interview_mode_display": "Video Call",
            "interview_type": "Online",
            "interviewer_name": "Rajesh Verma",
            "meeting_link": "https://meet.sevajobs.in/room-xyz",
            "interview_location": "Online Room 4",
            "frontend_url": "https://sevajobs.in",
        }
        content = render_to_string("emails/interview_scheduled.html", context)
        self.assertIn("Ananya", content)
        self.assertIn("Senior React Developer", content)
        self.assertIn("Apex Tech", content)
        self.assertIn("Video Call", content)
        self.assertIn("Rajesh Verma", content)
        self.assertIn("https://meet.sevajobs.in/room-xyz", content)
        self.assertIn("https://sevajobs.in/dashboard/seeker/interviews", content)

    def test_14_txt_template_renders_successfully(self):
        """TEST 14: interview_scheduled.txt renders successfully."""
        local_when = timezone.localtime(self.interview_dt) if timezone.is_aware(self.interview_dt) else self.interview_dt
        context = {
            "candidate_name": "Ananya",
            "job_title": "Senior React Developer",
            "company_name": "Apex Tech",
            "interview_date_display": local_when.strftime("%A, %d %B %Y"),
            "interview_time_display": local_when.strftime("%I:%M %p"),
            "interview_mode_display": "Video Call",
            "interviewer_name": "Rajesh Verma",
            "meeting_link": "https://meet.sevajobs.in/room-xyz",
            "interview_location": "Online Room 4",
            "frontend_url": "https://sevajobs.in",
        }
        content = render_to_string("emails/interview_scheduled.txt", context)
        self.assertIn("Ananya", content)
        self.assertIn("Senior React Developer", content)
        self.assertIn("Apex Tech", content)
        self.assertIn("Video Call", content)
        self.assertIn("https://sevajobs.in/dashboard/seeker/interviews", content)

    def test_15_internal_notification_created_for_candidate(self):
        """TEST 15: Candidate receives internal in-app notification on interview scheduling."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.INTERVIEW_SCHEDULED,
            changed_by=self.recruiter_user,
            interview_at=self.interview_dt,
        )
        notif = Notification.objects.filter(
            recipient=self.candidate,
            notification_type=Notification.Type.INTERVIEW_SCHEDULED,
        ).first()
        self.assertIsNotNone(notif)
        self.assertIn("Interview Scheduled", notif.title)

    def test_16_history_record_created_for_transition(self):
        """TEST 16: Transition to INTERVIEW_SCHEDULED recorded in ApplicationStatusHistory."""
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.INTERVIEW_SCHEDULED,
            changed_by=self.recruiter_user,
            interview_at=self.interview_dt,
        )
        history = ApplicationStatusHistory.objects.filter(
            application=self.application,
            to_status=JobApplication.Status.INTERVIEW_SCHEDULED,
        ).first()
        self.assertIsNotNone(history)
        self.assertEqual(history.changed_by, self.recruiter_user)

    def test_17_transaction_rollback_prevents_interview_email(self):
        """TEST 17: Force transaction rollback prevents interview email Celery task."""
        from apps.notifications.tasks import send_transactional_email_task
        with patch.object(send_transactional_email_task, "delay") as mock_task:
            try:
                with transaction.atomic():
                    self.service.move_status(
                        self.application,
                        new_status=JobApplication.Status.INTERVIEW_SCHEDULED,
                        changed_by=self.recruiter_user,
                        interview_at=self.interview_dt,
                    )
                    raise DatabaseError("Simulated DB failure")
            except DatabaseError:
                pass

            mock_task.assert_not_called()

    def test_18_transaction_commit_enqueues_interview_email(self):
        """TEST 18: Successful transaction commit enqueues interview email Celery task."""
        from apps.notifications.tasks import send_transactional_email_task
        with patch.object(send_transactional_email_task, "delay") as mock_task:
            self.service.move_status(
                self.application,
                new_status=JobApplication.Status.INTERVIEW_SCHEDULED,
                changed_by=self.recruiter_user,
                interview_at=self.interview_dt,
            )
            self.assertTrue(mock_task.called)

    def test_19_idempotency_key_format(self):
        """TEST 19: Verify idempotency key contains app_status:<id>:interview_scheduled:<timestamp>."""
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            self.service.move_status(
                self.application,
                new_status=JobApplication.Status.INTERVIEW_SCHEDULED,
                changed_by=self.recruiter_user,
                interview_at=self.interview_dt,
            )
            call = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "interview_scheduled"][0]
            expected_key = f"app_status:{self.application.id}:interview_scheduled:{int(self.interview_at.timestamp())}"
            self.assertEqual(call.kwargs["idempotency_key"], expected_key)

    def test_20_invalid_status_transition_rejected(self):
        """TEST 20: Direct transition from APPLIED to INTERVIEW_SCHEDULED without shortlisting fails."""
        fresh_app = JobApplication.objects.create(
            job=self.job,
            applicant=User.objects.create_user(
                email="fresh.candidate@example.com",
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
                    new_status=JobApplication.Status.INTERVIEW_SCHEDULED,
                    changed_by=self.recruiter_user,
                    interview_at=self.interview_dt,
                )
            self.assertIn("Cannot move from 'applied' to 'interview_scheduled'", str(cm.exception))
            mock_send.assert_not_called()

    def test_21_unauthorized_recruiter_cannot_access_other_company_candidate(self):
        """TEST 21: Unauthorized recruiter accessing application from another company is blocked."""
        self.client.force_login(self.other_recruiter_user, backend="django.contrib.auth.backends.ModelBackend")
        response = self.client.post(
            f"/dashboard/recruiter/applications/{self.application.id}/",
            {
                "action": "schedule_interview",
                "interview_date": self.interview_dt.strftime("%Y-%m-%d"),
                "interview_time": "11:00",
            },
        )
        self.assertEqual(response.status_code, 404)

    def test_22_missing_interview_datetime_rejected(self):
        """TEST 22: Scheduling INTERVIEW_SCHEDULED status without interview_at datetime fails with ValidationError."""
        with patch.object(EmailService, "send_template_email") as mock_send:
            with self.assertRaises(ValidationError) as cm:
                self.service.move_status(
                    self.application,
                    new_status=JobApplication.Status.INTERVIEW_SCHEDULED,
                    changed_by=self.recruiter_user,
                    interview_at=None,
                )
            self.assertIn("interview_at", str(cm.exception))
            mock_send.assert_not_called()

    def test_23_rescheduling_generates_fresh_candidate_email_with_updated_timestamp_key(self):
        """TEST 23: Rescheduling an existing interview updates details and sends candidate email with fresh idempotency key."""
        # Initial schedule
        self.service.move_status(
            self.application,
            new_status=JobApplication.Status.INTERVIEW_SCHEDULED,
            changed_by=self.recruiter_user,
            interview_at=self.interview_dt,
        )

        # New rescheduled datetime (3 days from now)
        rescheduled_dt = self.interview_dt + timedelta(days=1)

        self.client.force_login(self.recruiter_user, backend="django.contrib.auth.backends.ModelBackend")
        session = self.client.session
        session["current_role_scope"] = "recruiter"
        session.save()
        self.client.cookies["sessionid"] = session.session_key

        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            response = self.client.post(
                f"/dashboard/recruiter/applications/{self.application.id}/",
                {
                    "action": "schedule_interview",
                    "interview_date": rescheduled_dt.strftime("%Y-%m-%d"),
                    "interview_time": "14:00",
                    "interview_mode": "video",
                    "interview_location": "Rescheduled Room 9",
                },
            )
            self.assertEqual(response.status_code, 302)

            self.application.refresh_from_db()
            self.assertEqual(self.application.interview_at.strftime("%H:%M"), "14:00")

            rec_calls = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "interview_scheduled"]
            self.assertEqual(len(rec_calls), 1)
            expected_key = f"app_status:{self.application.id}:interview_scheduled:{int(self.application.interview_at.timestamp())}"
            self.assertEqual(rec_calls[0].kwargs["idempotency_key"], expected_key)

    def test_24_web_ui_schedule_interview_reaches_service_and_schedules_email(self):
        """TEST 24: Recruiter Web UI schedule_interview action reaches service and schedules email."""
        self.client.force_login(self.recruiter_user, backend="django.contrib.auth.backends.ModelBackend")
        session = self.client.session
        session["current_role_scope"] = "recruiter"
        session.save()
        self.client.cookies["sessionid"] = session.session_key

        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            response = self.client.post(
                f"/dashboard/recruiter/applications/{self.application.id}/",
                {
                    "action": "schedule_interview",
                    "interview_date": self.interview_dt.strftime("%Y-%m-%d"),
                    "interview_time": "11:00",
                    "interview_mode": "video",
                    "interview_location": "HQ Conference Room A",
                },
            )
            self.assertEqual(response.status_code, 302)
            self.application.refresh_from_db()
            self.assertEqual(self.application.status, JobApplication.Status.INTERVIEW_SCHEDULED)

            calls = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "interview_scheduled"]
            self.assertEqual(len(calls), 1)

    def test_25_api_status_change_reaches_service_and_schedules_email(self):
        """TEST 25: DRF API StatusChangeView reaches service and schedules email."""
        self.api_client.force_authenticate(user=self.recruiter_user)
        with patch.object(EmailService, "send_template_email", wraps=EmailService.send_template_email) as mock_send:
            response = self.api_client.post(
                f"/api/v1/applications/{self.application.id}/status/",
                {
                    "status": "interview_scheduled",
                    "interview_at": self.interview_dt.isoformat(),
                    "interview_mode": "video",
                    "interview_location": "API Video Room",
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.application.refresh_from_db()
            self.assertEqual(self.application.status, JobApplication.Status.INTERVIEW_SCHEDULED)

            calls = [c for c in mock_send.call_args_list if c.kwargs.get("template_name") == "interview_scheduled"]
            self.assertEqual(len(calls), 1)
