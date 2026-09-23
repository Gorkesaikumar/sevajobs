"""
Tests for Welcome Role Selection Popup display rules and context rendering.
"""

from django.test import TestCase, Client
from django.urls import reverse
from apps.accounts.models import User


class WelcomeModalTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.job_seeker_user = User.objects.create_user(
            email="seeker_test@example.com",
            password="TestPassword123!",
            first_name="Jane",
            last_name="Seeker",
            role=User.Role.JOB_SEEKER,
            is_email_verified=True,
        )
        self.recruiter_user = User.objects.create_user(
            email="recruiter_test@example.com",
            password="TestPassword123!",
            first_name="Bob",
            last_name="Employer",
            role=User.Role.RECRUITER,
            is_email_verified=True,
        )

    def test_anonymous_visitor_sees_welcome_modal_and_script(self):
        """Anonymous first-time visitors should have the welcome modal markup and script rendered."""
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="welcomeRoleModal"')
        self.assertContains(response, "welcome-modal.js")
        self.assertContains(response, "Welcome to")
        self.assertContains(response, "Looking for a Job?")
        self.assertContains(response, "Hiring Talent?")
        self.assertContains(response, 'href="/jobs/"')
        self.assertContains(response, 'href="/accounts/register/?role=job_seeker"')
        self.assertContains(response, 'href="/accounts/register/?role=recruiter"')

    def test_authenticated_job_seeker_does_not_see_welcome_modal(self):
        """Logged in Job Seekers should NOT have the welcome modal or component script rendered."""
        self.client.force_login(self.job_seeker_user)
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="welcomeRoleModal"')
        self.assertNotContains(response, "welcome-modal.js")

    def test_authenticated_recruiter_does_not_see_welcome_modal(self):
        """Logged in Recruiters should NOT have the welcome modal or component script rendered."""
        self.client.force_login(self.recruiter_user)
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="welcomeRoleModal"')
        self.assertNotContains(response, "welcome-modal.js")
