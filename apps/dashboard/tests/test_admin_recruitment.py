from __future__ import annotations

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import User, StaffProfile, AuditLog, Resume
from apps.jobs.models import StaffJob, JobAssignment
from apps.applications.models import JobApplication, ApplicationStatusHistory, CandidateSelection
from apps.notifications.models import Notification

User = get_user_model()

class AdminRecruitmentTests(TestCase):
    def setUp(self):
        # Create Admin
        self.admin_user = User.objects.create_superuser(
            email="admin@example.com",
            password="adminpassword123",
            first_name="System",
            last_name="Admin"
        )
        
        # Create Staff A
        self.staff_a = User.objects.create_user(
            email="staffa@example.com",
            password="staffpassword123",
            first_name="Staff",
            last_name="A",
            role=User.Role.STAFF,
            is_active=True
        )
        self.profile_a = StaffProfile.objects.create(
            user=self.staff_a,
            employee_id="EMP001",
            full_name="Staff A",
            email="staffa@example.com",
            phone_number="9876543210",
            state="Telangana",
            district="Hyderabad",
            city="Hyderabad"
        )

        # Create Staff B
        self.staff_b = User.objects.create_user(
            email="staffb@example.com",
            password="staffpassword123",
            first_name="Staff",
            last_name="B",
            role=User.Role.STAFF,
            is_active=True
        )
        self.profile_b = StaffProfile.objects.create(
            user=self.staff_b,
            employee_id="EMP002",
            full_name="Staff B",
            email="staffb@example.com",
            phone_number="9876543211",
            state="Telangana",
            district="Nizamabad",
            city="Nizamabad"
        )

        # Create Seeker
        self.seeker_user = User.objects.create_user(
            email="seeker@example.com",
            password="seekerpassword123",
            first_name="John",
            last_name="Doe",
            role=User.Role.JOB_SEEKER,
            is_active=True
        )
        self.resume = Resume.objects.create(
            job_seeker=self.seeker_user,
            title="My Resume",
            file=SimpleUploadedFile("resume.pdf", b"pdf content", content_type="application/pdf"),
            file_type="pdf",
            file_size=1024,
            is_primary=True
        )

    def login_admin(self):
        self.client.login(username="admin@example.com", password="adminpassword123")
        session = self.client.session
        session['current_role_scope'] = 'admin'
        session.save()
        self.client.cookies['sessionid_admin'] = self.client.cookies['sessionid'].value

    def login_staff(self, staff_user):
        self.client.login(username=staff_user.email, password="staffpassword123")
        session = self.client.session
        session['current_role_scope'] = 'staff'
        session.save()
        self.client.cookies['sessionid_staff'] = self.client.cookies['sessionid'].value

    def test_admin_job_posting(self):
        """Test Admin can create and publish jobs from dashboard."""
        self.login_admin()

        url = reverse("admin-panel:create-job")
        data = {
            "designation": "Primary Teacher",
            "organization_name": "Seva School",
            "qualification": "B.Ed",
            "description": "Teach primary class students English language.",
            "vacancies": 5,
            "offered_salary": 250000,
            "state": "Telangana",
            "district": "Hyderabad",
            "city": "Hyderabad",
            "job_location": "Secunderabad",
            "phone_number": "1234567890",
            "email": "contact@sevaschool.com",
        }

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302) # Redirect to all jobs

        # Verify job is created and owns by admin
        job = StaffJob.objects.get(designation="Primary Teacher")
        self.assertEqual(job.created_by, self.admin_user)
        self.assertEqual(job.created_by_type, "Admin")
        self.assertEqual(job.description, "Teach primary class students English language.")
        self.assertEqual(job.status, StaffJob.Status.ACTIVE)
        self.assertTrue(job.is_published)

        # Audit Logs verification
        self.assertTrue(AuditLog.objects.filter(action="Job Created", user=self.admin_user).exists())
        self.assertTrue(AuditLog.objects.filter(action="Job Published", user=self.admin_user).exists())

    def test_recruitment_assignment_and_reassignment(self):
        """Test Admin can assign and reassign recruitment workflow to Staff."""
        # Create an Admin-owned job
        job = StaffJob.objects.create(
            job_id="SJOB-999999",
            designation="Teacher",
            organization_name="Admin Org",
            qualification="B.Ed",
            vacancies=1,
            offered_salary=200000,
            job_location="Hyderabad",
            state="Telangana",
            district="Hyderabad",
            city="Hyderabad",
            phone_number="1234567890",
            email="admin@example.com",
            created_by=self.admin_user,
            status=StaffJob.Status.ACTIVE,
            published_at=timezone.now()
        )

        self.login_admin()

        # Step 1: Assign to Staff A
        assign_url = reverse("admin-panel:assign-staff", kwargs={"pk": job.pk})
        data = {
            "staff_members": [str(self.staff_a.id)],
            "notes": "Please process applications urgently."
        }
        response = self.client.post(assign_url, data)
        self.assertEqual(response.status_code, 302)

        # Verify assignment
        assignment = JobAssignment.objects.get(job=job, assigned_staff=self.staff_a)
        self.assertEqual(assignment.status, JobAssignment.Status.ASSIGNED)
        self.assertEqual(assignment.notes, "Please process applications urgently.")

        # Verify notification triggered for Staff A
        self.assertTrue(Notification.objects.filter(
            recipient=self.staff_a,
            notification_type="job_assigned"
        ).exists())

        # Step 2: Reassign (Transfer recruitment ownership from Staff A to Staff B)
        data = {
            "staff_members": [str(self.staff_b.id)],
            "notes": "Staff A is unavailable. Transferring to Staff B."
        }
        response = self.client.post(assign_url, data)
        self.assertEqual(response.status_code, 302)

        # Verify old assignment reassigned
        assignment_a = JobAssignment.objects.get(job=job, assigned_staff=self.staff_a)
        self.assertEqual(assignment_a.status, JobAssignment.Status.REASSIGNED)

        # Verify new assignment assigned
        assignment_b = JobAssignment.objects.get(job=job, assigned_staff=self.staff_b)
        self.assertEqual(assignment_b.status, JobAssignment.Status.ASSIGNED)

        # Verify notification triggered for Staff B (assigned) and Staff A (reassigned)
        self.assertTrue(Notification.objects.filter(
            recipient=self.staff_b,
            notification_type="job_assigned"
        ).exists())
        self.assertTrue(Notification.objects.filter(
            recipient=self.staff_a,
            notification_type="job_reassigned"
        ).exists())

    def test_staff_dashboard_and_views_integration(self):
        """Test Staff dashboard shows assigned jobs and applications correctly."""
        # Create an Admin job assigned to Staff A
        job = StaffJob.objects.create(
            job_id="SJOB-111111",
            designation="Maths Teacher",
            organization_name="Seva Academy",
            qualification="M.Sc",
            vacancies=2,
            offered_salary=300000,
            job_location="Hyderabad",
            state="Telangana",
            district="Hyderabad",
            city="Hyderabad",
            phone_number="1234567890",
            email="admin@example.com",
            created_by=self.admin_user,
            status=StaffJob.Status.ACTIVE,
            published_at=timezone.now()
        )
        JobAssignment.objects.create(
            job=job,
            assigned_staff=self.staff_a,
            assigned_by=self.admin_user,
            status=JobAssignment.Status.ASSIGNED
        )

        # Create application for this job
        application = JobApplication.objects.create(
            staff_job=job,
            applicant=self.seeker_user,
            resume=self.resume,
            status=JobApplication.Status.APPLIED
        )

        # Log in as Staff A
        self.login_staff(self.staff_a)

        # Dashboard View Stats
        dashboard_url = reverse("staff:dashboard")
        response = self.client.get(dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["assigned_jobs_count"], 1)
        self.assertEqual(response.context["new_applications_count"], 1)

        # Manage Jobs View
        manage_jobs_url = reverse("staff:my-jobs")
        response = self.client.get(manage_jobs_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Maths Teacher")

        # Applications View
        apps_url = reverse("staff:applications")
        response = self.client.get(apps_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "John Doe")

    def test_admin_central_applications_management(self):
        """Test Admin central applications actions: status updates and resume logging."""
        job = StaffJob.objects.create(
            job_id="SJOB-222222",
            designation="Teacher",
            organization_name="Central Org",
            qualification="B.Ed",
            vacancies=1,
            offered_salary=200000,
            job_location="Hyderabad",
            phone_number="1234567890",
            email="admin@example.com",
            created_by=self.admin_user,
            status=StaffJob.Status.ACTIVE,
            published_at=timezone.now()
        )
        application = JobApplication.objects.create(
            staff_job=job,
            applicant=self.seeker_user,
            resume=self.resume,
            status=JobApplication.Status.APPLIED
        )

        self.login_admin()

        central_url = reverse("admin-panel:applications")
        
        # 1. Test status update to Shortlisted
        data = {
            "action": "update_status",
            "application_id": str(application.id),
            "status": JobApplication.Status.SHORTLISTED
        }
        response = self.client.post(central_url, data)
        self.assertEqual(response.status_code, 302)

        application.refresh_from_db()
        self.assertEqual(application.status, JobApplication.Status.SHORTLISTED)
        
        # Verify status history & audit log
        self.assertTrue(ApplicationStatusHistory.objects.filter(
            application=application,
            to_status=JobApplication.Status.SHORTLISTED
        ).exists())
        self.assertTrue(AuditLog.objects.filter(
            action="Candidate Status Updated",
            user=self.admin_user
        ).exists())

        # 2. Test view resume triggers audit logging
        data = {
            "action": "log_view_resume",
            "application_id": str(application.id)
        }
        response = self.client.post(central_url, data)
        self.assertEqual(response.status_code, 302) # Redirect to resume file url
        self.assertTrue(AuditLog.objects.filter(
            action="Resume Viewed",
            user=self.admin_user
        ).exists())

        # 3. Test download resume triggers audit logging
        data = {
            "action": "log_download_resume",
            "application_id": str(application.id)
        }
        response = self.client.post(central_url, data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(AuditLog.objects.filter(
            action="Resume Downloaded",
            user=self.admin_user
        ).exists())
