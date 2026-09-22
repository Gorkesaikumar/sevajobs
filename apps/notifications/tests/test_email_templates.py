"""Automated tests for transactional email template header logo rendering."""

from django.test import TestCase, override_settings
from django.template.loader import render_to_string
from django.conf import settings


@override_settings(FRONTEND_URL="https://sevajobs.in")
class EmailTemplateLogoTestCase(TestCase):
    def test_password_changed_template_renders_logo_image(self):
        ctx = {
            "frontend_url": getattr(settings, "FRONTEND_URL", "https://sevajobs.in"),
            "first_name": "Gorke",
            "date_time": "September 22, 2026, 9:34 p.m.",
            "support_email": "support@sevajobs.in",
            "subject": "Security Alert: Password Changed",
        }
        html_content = render_to_string("emails/password_changed.html", ctx)

        # Verify logo img tag with absolute URL
        self.assertIn('src="https://sevajobs.in/static/images/logo.jpg"', html_content)
        self.assertIn('alt="SevaJobs"', html_content)
        self.assertIn('width="140"', html_content)

        # Verify plain text logo header branding is removed
        self.assertNotIn('class="logo-text"', html_content)
        self.assertNotIn('class="logo-accent"', html_content)
        self.assertNotIn('Seva<span class="logo-accent">Jobs</span>', html_content)

        # Verify meaningful body text is preserved
        self.assertIn("your SevaJobs account", html_content)
        self.assertIn("Security Alert: Password Changed", html_content)

    def test_password_reset_template_renders_logo_image(self):
        ctx = {
            "frontend_url": getattr(settings, "FRONTEND_URL", "https://sevajobs.in"),
            "first_name": "John",
            "reset_url": "https://sevajobs.in/accounts/reset-password/token123/",
            "ttl_hours": 24,
            "support_email": "support@sevajobs.in",
            "subject": "Reset your SevaJobs password",
        }
        html_content = render_to_string("emails/password_reset.html", ctx)

        # Verify logo img tag with absolute URL
        self.assertIn('src="https://sevajobs.in/static/images/logo.jpg"', html_content)
        self.assertIn('alt="SevaJobs"', html_content)

        # Verify old text header branding is absent
        self.assertNotIn('class="logo-text"', html_content)
        self.assertNotIn('class="logo-accent"', html_content)

        # Verify body text is preserved
        self.assertIn("Reset your SevaJobs password", html_content)
