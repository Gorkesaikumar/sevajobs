from __future__ import annotations

import uuid
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import User, StaffProfile, AuditLog, Resume
from apps.jobs.models import StaffJob
from apps.applications.models import JobApplication

User = get_user_model()

class StaffManagementTests(APITestCase):
    def setUp(self):
        # Create Admin
        self.admin_user = User.objects.create_superuser(
            email="admin@example.com",
            password="adminpassword123",
            first_name="System",
            last_name="Admin"
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
        # Create a Resume for Seeker
        self.resume = Resume.objects.create(
            job_seeker=self.seeker_user,
            title="My Resume",
            file=SimpleUploadedFile("resume.pdf", b"pdf content", content_type="application/pdf"),
            file_type="pdf",
            file_size=1024,
            is_primary=True
        )

    def test_admin_create_staff_form_and_views(self):
        """Test standard admin views for staff creation, details, and deactivation."""
        self.client.login(username="admin@example.com", password="adminpassword123")
        session = self.client.session
        session['current_role_scope'] = 'admin'
        session.save()
        self.client.cookies['sessionid_admin'] = self.client.cookies['sessionid'].value

        # Access list page
        url = reverse("admin-panel:staff-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Create Staff — no username, no status (auto-Active)
        create_url = reverse("admin-panel:staff-create")
        data = {
            "full_name": "Staff Member One",
            "email": "staff1@example.com",
            "phone_number": "1234567890",
            "password": "staffpassword123",
            "confirm_password": "staffpassword123",
        }

        # Valid creation — expect 200 with success screen (created_profile in context)
        response = self.client.post(create_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("created_profile", response.context)
        self.assertIn("temporary_password", response.context)

        # Verify StaffProfile created
        staff_profile = StaffProfile.objects.get(email="staff1@example.com")
        self.assertEqual(staff_profile.full_name, "Staff Member One")
        # New accounts must always default to Active
        self.assertEqual(staff_profile.status, "Active")
        # No username stored for staff users
        self.assertIsNone(staff_profile.user.username)
        self.assertEqual(staff_profile.user.role, User.Role.STAFF)
        self.assertTrue(staff_profile.user.is_active)

        # Verify NO Email was sent (we now use WhatsApp for credentials)
        self.assertEqual(len(mail.outbox), 0)

        # Verify Audit Log
        self.assertTrue(AuditLog.objects.filter(action="Staff Created", user=self.admin_user).exists())

        # Test duplicate creation validations (e.g. Email unique)
        response = self.client.post(create_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context['form'], 'email', 'A user with this email already exists.')

        # Test staff login — email only (no username login)
        self.client.logout()
        login_url = reverse("staff:staff-login")

        # Login using email
        login_response = self.client.post(login_url, {
            "username": "staff1@example.com",   # Django AuthForm still uses "username" field name
            "password": "staffpassword123"
        })
        self.assertRedirects(login_response, "/staff/dashboard/")

        # Attempt login with non-existent username — must FAIL (email-only auth)
        self.client.logout()
        login_response = self.client.post(login_url, {
            "username": "staff1",               # plain username should NOT work
            "password": "staffpassword123"
        })
        # Should NOT redirect to dashboard — stays on login page (200) or shows error
        self.assertNotEqual(login_response.status_code, 302)

        # Test deactivation
        self.client.logout()
        self.client.login(username="admin@example.com", password="adminpassword123")
        session = self.client.session
        session['current_role_scope'] = 'admin'
        session.save()
        self.client.cookies['sessionid_admin'] = self.client.cookies['sessionid'].value

        toggle_url = reverse("admin-panel:staff-toggle", kwargs={"pk": staff_profile.id})
        response = self.client.post(toggle_url, {"action": "deactivate"})
        self.assertRedirects(response, url)

        staff_profile.refresh_from_db()
        self.assertEqual(staff_profile.status, "Inactive")
        self.assertFalse(staff_profile.user.is_active)

        # Reset Password test
        reset_url = reverse("admin-panel:staff-reset-password", kwargs={"pk": staff_profile.id})
        response = self.client.post(reset_url)
        # Now returns 200 with the success screen instead of redirecting
        self.assertEqual(response.status_code, 200)
        self.assertIn("temporary_password", response.context)
        self.assertTrue(response.context.get("is_reset"))
        # Verify no emails were sent
        self.assertEqual(len(mail.outbox), 0)

    def test_staff_job_posting_and_seeker_application(self):
        """Test Staff user posting a job and Seeker applying to it."""
        # Setup active staff user — no username
        staff_user = User.objects.create_user(
            email="staff_post@example.com",
            password="staffpassword123",
            first_name="Staff",
            last_name="Poster",
            role=User.Role.STAFF,
            is_active=True
        )
        staff_profile = StaffProfile.objects.create(
            user=staff_user,
            employee_id="EMP-999999",
            full_name="Staff Poster",
            email="staff_post@example.com",
            phone_number="9876543210",
            status="Active"
        )

        self.client.login(username="staff_post@example.com", password="staffpassword123")
        # Set session role scope for LoginRequiredMixin & middleware checks
        session = self.client.session
        session['current_role_scope'] = 'staff'
        session.save()
        self.client.cookies['sessionid_staff'] = self.client.cookies['sessionid'].value

        # Access Dashboard & Jobs List
        dashboard_url = reverse("staff:dashboard")
        response = self.client.get(dashboard_url)
        self.assertEqual(response.status_code, 200)

        # Post a Job
        add_job_url = reverse("staff:add-job")
        job_data = {
            "designation": "Staff Assistant Teacher",
            "organization_name": "International School",
            "qualification": "B.Ed",
            "vacancies": 2,
            "offered_salary": 350000,
            "job_location": "Bangalore",
            "phone_number": "1234567890",
            "email": "hr@internationalschool.com"
        }

        response = self.client.post(add_job_url, job_data)
        self.assertRedirects(response, reverse("staff:my-jobs"))

        # Verify Job is active and live
        job = StaffJob.objects.get(designation="Staff Assistant Teacher")
        self.assertEqual(job.status, StaffJob.Status.ACTIVE)
        self.assertTrue(job.is_active)
        self.assertEqual(job.created_by, staff_user)

        # Test duplicate spam prevention (clean method in StaffJobForm)
        response = self.client.post(add_job_url, job_data)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context['form'], None, "A duplicate job posting was detected recently. Please wait a few minutes before posting again.")

        # Test Seeker applying to the Staff job
        self.client.logout()
        self.client.login(username="seeker@example.com", password="seekerpassword123")
        session = self.client.session
        session['current_role_scope'] = 'job_seeker'
        session.save()
        self.client.cookies['sessionid_seeker'] = self.client.cookies['sessionid'].value

        apply_url = reverse("core:job-apply")
        apply_data = {
            "job_id": str(job.id),
            "resume_id": str(self.resume.id),
            "cover_letter": "I would love to apply for this staff job.",
            "expected_salary": 400000
        }
        response = self.client.post(apply_url, apply_data)
        self.assertRedirects(response, reverse("core:staff-job-detail", kwargs={"pk": job.id}))

        # Verify JobApplication created and linked to StaffJob
        application = JobApplication.objects.get(staff_job=job, applicant=self.seeker_user)
        self.assertEqual(application.status, JobApplication.Status.APPLIED)
        self.assertEqual(application.expected_salary, 400000)

        # Verify duplicate application prevention
        response = self.client.post(apply_url, apply_data)
        self.assertEqual(response.status_code, 302) # Redirects to detail page with error message

    def test_drf_api_endpoints(self):
        """Test API endpoints for staff jobs/applications and admin staff management."""
        # 1. Setup Staff User — no username
        staff_user = User.objects.create_user(
            email="staff_api@example.com",
            password="staffpassword123",
            role=User.Role.STAFF,
            is_active=True
        )
        staff_profile = StaffProfile.objects.create(
            user=staff_user,
            employee_id="EMP-888888",
            full_name="Staff API User",
            email="staff_api@example.com",
            phone_number="8888888888",
            status="Active"
        )

        # 2. Staff APIs: POST job/create/
        self.client.force_authenticate(user=staff_user)
        create_url = reverse("api-staff:staff-job-create")
        job_data = {
            "designation": "API Test Designation",
            "organization_name": "API School",
            "qualification": "M.Ed",
            "vacancies": 1,
            "offered_salary": 400000,
            "job_location": "Delhi",
            "phone_number": "1234567890",
            "email": "hr@apischool.com"
        }

        response = self.client.post(create_url, job_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["designation"], "API Test Designation")

        job_id = response.data["id"]

        # Staff APIs: GET jobs/
        list_url = reverse("api-staff:staff-jobs")
        response = self.client.get(list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["designation"], "API Test Designation")

        # Staff APIs: PUT jobs/update/
        update_url = reverse("api-staff:staff-job-update", kwargs={"id": job_id})
        update_data = job_data.copy()
        update_data["designation"] = "API Updated Designation"
        response = self.client.put(update_url, update_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["designation"], "API Updated Designation")

        # 3. Admin APIs: GET staff/
        self.client.force_authenticate(user=self.admin_user)
        admin_list_url = reverse("api-staff:admin-staff-list")
        response = self.client.get(admin_list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should have 1 profile (staff_api) — username field must NOT be in response
        self.assertEqual(len(response.data["results"]), 1)
        self.assertNotIn("username", response.data["results"][0])

        # Admin APIs: POST create/ — no username in payload
        admin_create_url = reverse("api-staff:admin-staff-create")
        new_staff_data = {
            "full_name": "API New Staff",
            "email": "api_new_staff@example.com",
            "phone_number": "9999999999",
            "password": "staffpassword123",
            "status": "Active"
        }
        response = self.client.post(admin_create_url, new_staff_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["full_name"], "API New Staff")
        # No username in response
        self.assertNotIn("username", response.data)

        new_staff_id = response.data["id"]

        # Admin APIs: POST deactivate/
        admin_deactivate_url = reverse("api-staff:admin-staff-deactivate")
        response = self.client.post(admin_deactivate_url, {"id": new_staff_id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify deactivated
        profile = StaffProfile.objects.get(id=new_staff_id)
        self.assertEqual(profile.status, "Inactive")
        self.assertFalse(profile.user.is_active)
        # Verify created staff has no username
        self.assertIsNone(profile.user.username)
