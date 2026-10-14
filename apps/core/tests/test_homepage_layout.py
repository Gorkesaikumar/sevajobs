"""
Tests for Homepage Section Ordering, Job Visibility Optimization, and Floating Employer CTA.
"""

from datetime import timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import User
from apps.jobs.models import Job, StaffJob
from apps.recruiters.models import Company


class HomepageLayoutTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.recruiter_user = User.objects.create_user(
            email="recruiter_hp@example.com",
            password="TestPassword123!",
            first_name="Alice",
            last_name="Recruiter",
            role=User.Role.RECRUITER,
            is_email_verified=True,
        )
        self.job_seeker_user = User.objects.create_user(
            email="seeker_hp@example.com",
            password="TestPassword123!",
            first_name="Bob",
            last_name="Teacher",
            role=User.Role.JOB_SEEKER,
            is_email_verified=True,
        )
        self.company = Company.objects.create(
            name="Delhi World School",
            slug="delhi-world-school",
            is_verified=True,
        )
        from apps.recruiters.models import RecruiterProfile
        self.recruiter_profile = RecruiterProfile.objects.create(
            user=self.recruiter_user,
            company=self.company,
            designation="HR Manager",
            phone="9876543210",
        )

        now = timezone.now()
        # Older job
        self.old_job = Job.objects.create(
            recruiter=self.recruiter_profile,
            company=self.company,
            title="Senior Physics Teacher",
            slug="senior-physics-teacher-delhi",
            status=Job.Status.ACTIVE,
            approval_status=Job.ApprovalStatus.APPROVED,
            is_active=True,
            vacancies=2,
            published_at=now - timedelta(days=10),
        )
        # Newer job
        self.new_job = Job.objects.create(
            recruiter=self.recruiter_profile,
            company=self.company,
            title="Head of Mathematics",
            slug="head-of-mathematics-delhi",
            status=Job.Status.ACTIVE,
            approval_status=Job.ApprovalStatus.APPROVED,
            is_active=True,
            vacancies=1,
            published_at=now - timedelta(hours=2),
        )
        # Draft job (should be excluded)
        self.draft_job = Job.objects.create(
            recruiter=self.recruiter_profile,
            company=self.company,
            title="Draft Chemistry Faculty",
            slug="draft-chem-faculty",
            status=Job.Status.DRAFT,
            approval_status=Job.ApprovalStatus.PENDING,
            is_active=True,
            published_at=now,
        )
        # Expired job (should be excluded)
        self.expired_job = Job.objects.create(
            recruiter=self.recruiter_profile,
            company=self.company,
            title="Expired Biology Teacher",
            slug="expired-biology-teacher",
            status=Job.Status.ACTIVE,
            approval_status=Job.ApprovalStatus.APPROVED,
            is_active=True,
            deadline=now.date() - timedelta(days=2),
            published_at=now - timedelta(days=5),
        )
        # Staff job
        self.staff_job = StaffJob.objects.create(
            job_id="STAFF-HP-001",
            created_by=self.recruiter_user,
            designation="Primary English Faculty",
            organization_name="Greenwood School",
            qualification="B.Ed",
            offered_salary=35000,
            job_location="Hyderabad",
            phone_number="9876543210",
            email="info@greenwood.com",
            status=StaffJob.Status.ACTIVE,
            is_active=True,
            vacancies=1,
            published_at=now - timedelta(hours=1),
        )

    def test_homepage_section_order(self):
        """Latest Educational Jobs must appear immediately after Hero and before About Us."""
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        hero_idx = content.find("sj-hero")
        jobs_idx = content.find('id="featured-jobs"')
        stats_idx = content.find("Active Jobs")
        about_idx = content.find('id="why-sevajobs"')

        self.assertNotEqual(hero_idx, -1, "Hero section not found")
        self.assertNotEqual(jobs_idx, -1, "Latest Educational Jobs section not found")
        self.assertNotEqual(stats_idx, -1, "KPI Stats section not found")
        self.assertNotEqual(about_idx, -1, "About Us section not found")

        self.assertTrue(hero_idx < jobs_idx, "Latest Jobs must appear after Hero")
        self.assertTrue(jobs_idx < stats_idx, "Stats must appear after Latest Jobs")
        self.assertTrue(stats_idx < about_idx, "About Us must appear after Stats")

    def test_latest_jobs_section_rendered_only_once(self):
        """Latest Educational Jobs section must appear exactly once on homepage."""
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertEqual(content.count('id="featured-jobs"'), 1)

    def test_old_wide_cta_card_removed_from_hero(self):
        """The old wide employer card must be absent from the hero section."""
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertNotIn("Are you a School, College or Institute hiring teachers?", content)

    def test_floating_cta_rendered_only_once(self):
        """The floating action button must appear exactly once on the homepage."""
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertEqual(content.count('id="floatingEmployerCtaWrap"'), 1)
        self.assertEqual(content.count('id="floatingEmployerCtaBtn"'), 1)

    def test_job_query_ordering_and_filtering(self):
        """Query must order results by most recent publication date and filter out draft/expired."""
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        featured_jobs = response.context["featured_jobs"]

        # Check exclusion of draft and expired jobs
        titles = [getattr(j, "title", getattr(j, "designation", "")) for j in featured_jobs]
        self.assertIn("Head of Mathematics", titles)
        self.assertIn("Primary English Faculty", titles)
        self.assertIn("Senior Physics Teacher", titles)
        self.assertNotIn("Draft Chemistry Faculty", titles)
        self.assertNotIn("Expired Biology Teacher", titles)

        # Check that newest job appears before older job
        head_math_idx = titles.index("Head of Mathematics")
        sr_physics_idx = titles.index("Senior Physics Teacher")
        self.assertLess(head_math_idx, sr_physics_idx, "Newer job must appear before older job")

    def test_job_seeker_authorization_on_submit_requirement(self):
        """Job seekers must be blocked from posting employer requirements."""
        self.client.force_login(self.job_seeker_user)
        response = self.client.post(reverse("jobs:submit-requirement"), {
            "institution_name": "Unauthorized School",
            "phone_number": "9876543210",
            "subject": "Physics",
            "qualification": "B.Ed",
            "location": "Mumbai",
        })
        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertEqual(data["status"], "error")
        self.assertIn("job seeker", data["message"].lower())

    def test_anonymous_and_recruiter_can_submit_requirement(self):
        """Anonymous or recruiter users can submit quick requirement."""
        response = self.client.post(reverse("jobs:submit-requirement"), {
            "institution_name": "Cambridge Academy",
            "phone_number": "9876543210",
            "subject": "Social Studies",
            "qualification": "M.A. B.Ed",
            "location": "Bengaluru",
            "teaching_grade": "TGT",
            "positions_count": "2",
        })
        self.assertIn(response.status_code, [200, 201])
        data = response.json()
        self.assertEqual(data["status"], "success")

    def test_job_card_has_apply_now_link(self):
        """Job cards must have an Apply Now action leading to the job detail page."""
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn(f"/jobs/{self.new_job.slug}/", content)
        self.assertIn("Apply Now", content)
