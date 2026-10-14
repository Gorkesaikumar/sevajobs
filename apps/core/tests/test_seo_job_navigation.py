"""
Comprehensive Automated Tests for SevaJobs Dynamic SEO Job Navigation Integration.

Covers:
  1. Header mega-menu and global footer presence & link resolution
  2. Database filtering across Subject, City, State, and Level
  3. Exclusions of draft, pending, inactive jobs
  4. Multiple job model unification (`Job` + `StaffJob`)
  5. Empty state rendering vs 404 on invalid slugs
  6. SEO metadata, canonical URLs, breadcrumbs, and sitemap.xml
  7. Regression testing for existing job search, detail, and schools pages
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
import xml.etree.ElementTree as ET

from apps.accounts.models import User
from apps.recruiters.models import RecruiterProfile, Company
from apps.jobs.models import Job, JobCategory, StaffJob
from apps.jobs.navigation import (
    SUBJECT_CATALOG,
    CITY_CATALOG,
    STATE_CATALOG,
    LEVEL_CATALOG,
    get_seo_navigation,
)


class BaseSEOTestSetup(TestCase):
    """Isolated test fixtures for job discovery and SEO navigation."""

    def setUp(self):
        self.client = Client()
        self.today = timezone.now().date()
        self.future_date = self.today + timedelta(days=60)

        # Create category
        self.category_teaching = JobCategory.objects.create(
            name="Teaching",
            slug="teaching",
            is_active=True,
        )

        # Create recruiter & company
        self.recruiter_user = User.objects.create_user(
            email="recruiter_seo@example.com",
            password="StrongPassword123!",
            first_name="Anita",
            last_name="Sharma",
            role=User.Role.RECRUITER,
            is_email_verified=True,
        )
        self.company_tg = Company.objects.create(
            name="Telangana Model School",
            slug="telangana-model-school",
            city="Warangal",
            state="Telangana",
            is_verified=True,
        )
        self.recruiter_profile = RecruiterProfile.objects.create(
            user=self.recruiter_user,
            company=self.company_tg,
        )

        self.company_ka = Company.objects.create(
            name="Bangalore International Academy",
            slug="bangalore-international-academy",
            city="Bangalore",
            state="Karnataka",
            is_verified=True,
        )
        self.recruiter_ka = RecruiterProfile.objects.create(
            user=User.objects.create_user(
                email="recruiter_ka@example.com",
                password="StrongPassword123!",
                role=User.Role.RECRUITER,
            ),
            company=self.company_ka,
        )

        # Create staff user
        self.staff_user = User.objects.create_user(
            email="staff_member@sevajobs.com",
            password="StrongPassword123!",
            first_name="Staff",
            last_name="Admin",
            role=User.Role.STAFF,
            is_email_verified=True,
        )

        # --- 1. Active Approved Recruiter Job in Telangana (Warangal) ---
        self.job_tg_physics = Job.objects.create(
            recruiter=self.recruiter_profile,
            company=self.company_tg,
            category=self.category_teaching,
            segment=Job.Segment.TEACHING,
            title="Secondary Physics Teacher",
            slug="secondary-physics-teacher-tg",
            description="Teaching high school physics in Warangal, Telangana.",
            location="Warangal, Telangana",
            city="Warangal",
            state="Telangana",
            country="India",
            status=Job.Status.ACTIVE,
            approval_status=Job.ApprovalStatus.APPROVED,
            is_active=True,
            deadline=self.future_date,
            published_at=timezone.now(),
            metadata={"subject": "Physics", "grade_class": "Secondary"},
        )

        # --- 2. Active Staff Job in Telangana (Nizamabad) ---
        self.staff_job_tg_math = StaffJob.objects.create(
            job_id="STF-TG-001",
            created_by=self.staff_user,
            designation="Primary Mathematics Teacher",
            organization_name="Nizamabad Public School",
            qualification="B.Sc, B.Ed Mathematics",
            job_location="Nizamabad, Telangana",
            city="Nizamabad",
            state="Telangana",
            offered_salary=350000,
            status=StaffJob.Status.ACTIVE,
            is_active=True,
            phone_number="9876543210",
            email="principal@nps.edu",
            published_at=timezone.now(),
        )

        # --- 3. Active Approved Recruiter Job in Karnataka (Bangalore) ---
        self.job_ka_english = Job.objects.create(
            recruiter=self.recruiter_ka,
            company=self.company_ka,
            category=self.category_teaching,
            segment=Job.Segment.TEACHING,
            title="Primary English Teacher",
            slug="primary-english-teacher-ka",
            description="Teaching primary english in Bangalore.",
            location="Bangalore, Karnataka",
            city="Bangalore",
            state="Karnataka",
            country="India",
            status=Job.Status.ACTIVE,
            approval_status=Job.ApprovalStatus.APPROVED,
            is_active=True,
            deadline=self.future_date,
            published_at=timezone.now(),
            metadata={"subject": "English", "grade_class": "Primary"},
        )

        # --- 4. Active Approved Recruiter Job in Maharashtra (Mumbai) ---
        self.job_mh_math = Job.objects.create(
            recruiter=self.recruiter_profile,
            company=self.company_tg,
            category=self.category_teaching,
            segment=Job.Segment.TEACHING,
            title="Senior Mathematics Teacher",
            slug="senior-mathematics-teacher-mumbai",
            description="Teaching senior mathematics in Mumbai.",
            location="Mumbai, Maharashtra",
            city="Mumbai",
            state="Maharashtra",
            country="India",
            status=Job.Status.ACTIVE,
            approval_status=Job.ApprovalStatus.APPROVED,
            is_active=True,
            deadline=self.future_date,
            published_at=timezone.now(),
            metadata={"subject": "Mathematics", "grade_class": "Senior Secondary"},
        )

        # --- 5. Draft / Pending Job (Must NEVER appear in public results) ---
        self.job_draft = Job.objects.create(
            recruiter=self.recruiter_profile,
            company=self.company_tg,
            category=self.category_teaching,
            title="Draft Mathematics Job",
            slug="draft-math-job",
            description="Draft job pending admin review.",
            location="Hyderabad, Telangana",
            city="Hyderabad",
            state="Telangana",
            status=Job.Status.DRAFT,
            approval_status=Job.ApprovalStatus.PENDING,
            is_active=True,
        )

        # --- 6. Inactive Staff Job (Must NEVER appear in public results) ---
        self.staff_job_inactive = StaffJob.objects.create(
            job_id="STF-CLOSED-002",
            created_by=self.staff_user,
            designation="Closed Chemistry Teacher",
            organization_name="Closed School",
            qualification="M.Sc Chemistry",
            job_location="Hyderabad, Telangana",
            city="Hyderabad",
            state="Telangana",
            offered_salary=400000,
            status=StaffJob.Status.CLOSED,
            is_active=False,
            phone_number="9876543211",
            email="closed@school.edu",
        )


class HeaderAndFooterNavigationTests(BaseSEOTestSetup):
    """Validates mega-menu in header and 4-column SEO block in footer across public pages."""

    def test_navigation_presence_on_home_page(self):
        """Header and footer SEO navigation must render on the home page."""
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)

        # Header Mega-Menu
        self.assertContains(response, 'id="findJobsDropdown"')
        self.assertContains(response, "Jobs by Subject")
        self.assertContains(response, "Jobs by City")
        self.assertContains(response, "Jobs by Level")
        self.assertContains(response, "Jobs by State")

        # Footer SEO Section
        self.assertContains(response, "sj-footer-seo")
        self.assertContains(response, "/jobs/india/english-teacher/")
        self.assertContains(response, "/jobs/hyderabad/")
        self.assertContains(response, "/jobs/telangana/")
        self.assertContains(response, "/current-vacancies")

    def test_navigation_presence_on_job_search_page(self):
        """Header and footer SEO navigation must render on the job search page."""
        response = self.client.get(reverse("core:job-search"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="findJobsDropdown"')
        self.assertContains(response, "sj-footer-seo")

    def test_navigation_presence_on_schools_page(self):
        """Header and footer SEO navigation must render on the schools page."""
        response = self.client.get(reverse("core:company-list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="findJobsDropdown"')
        self.assertContains(response, "sj-footer-seo")

    def test_all_catalog_links_resolve(self):
        """Every link in SUBJECT_CATALOG, CITY_CATALOG, STATE_CATALOG, LEVEL_CATALOG must resolve."""
        nav = get_seo_navigation()
        for category, items in nav.items():
            for item in items:
                url = item["url"]
                resp = self.client.get(url)
                self.assertEqual(
                    resp.status_code, 200,
                    f"Navigation link for {item['name']} ({url}) failed with status {resp.status_code}"
                )

    def test_existing_header_and_footer_links_intact(self):
        """Ensure standard brand and legal links remain functional."""
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, reverse("core:about"))
        self.assertContains(response, reverse("core:contact"))
        self.assertContains(response, reverse("core:privacy"))
        self.assertContains(response, reverse("core:terms"))
        self.assertContains(response, reverse("core:company-list"))


class DatabaseFilteringTests(BaseSEOTestSetup):
    """Validates real database queries, accurate counts, and zero mock data."""

    def test_state_filter_returns_multiple_cities_within_state(self):
        """Telangana must return jobs from Warangal and Nizamabad, and NOT Karnataka."""
        response = self.client.get(reverse("core:job-location", kwargs={"location_slug": "telangana"}))
        self.assertEqual(response.status_code, 200)
        jobs = list(response.context["jobs"])
        job_titles = [j.title if hasattr(j, "title") else j.designation for j in jobs]

        # Must include both Telangana jobs from different cities
        self.assertIn("Secondary Physics Teacher", job_titles)      # Warangal
        self.assertIn("Primary Mathematics Teacher", job_titles)    # Nizamabad
        # Must NOT include Karnataka or Maharashtra jobs
        self.assertNotIn("Primary English Teacher", job_titles)     # Bangalore
        self.assertNotIn("Senior Mathematics Teacher", job_titles)  # Mumbai
        self.assertEqual(len(jobs), 2)

    def test_city_filter_bangalore_returns_bangalore_only(self):
        """Bangalore city filter must only return Bangalore jobs."""
        response = self.client.get(reverse("core:job-location", kwargs={"location_slug": "bangalore"}))
        self.assertEqual(response.status_code, 200)
        jobs = list(response.context["jobs"])
        job_titles = [j.title if hasattr(j, "title") else j.designation for j in jobs]

        self.assertIn("Primary English Teacher", job_titles)
        self.assertNotIn("Secondary Physics Teacher", job_titles)
        self.assertEqual(len(jobs), 1)

    def test_subject_filter_mathematics(self):
        """Mathematics filter must return both recruiter and staff Mathematics jobs."""
        response = self.client.get(reverse("core:job-subject", kwargs={"subject_slug": "mathematics-teacher"}))
        self.assertEqual(response.status_code, 200)
        jobs = list(response.context["jobs"])
        job_titles = [j.title if hasattr(j, "title") else j.designation for j in jobs]

        self.assertIn("Primary Mathematics Teacher", job_titles)   # Staff job
        self.assertIn("Senior Mathematics Teacher", job_titles)    # Recruiter job
        self.assertNotIn("Secondary Physics Teacher", job_titles)  # Physics
        self.assertNotIn("Primary English Teacher", job_titles)    # English
        self.assertEqual(len(jobs), 2)

    def test_subject_filter_physics(self):
        """Physics filter must return only Physics jobs."""
        response = self.client.get(reverse("core:job-subject", kwargs={"subject_slug": "physics-teacher"}))
        self.assertEqual(response.status_code, 200)
        jobs = list(response.context["jobs"])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].title, "Secondary Physics Teacher")

    def test_level_filter_primary(self):
        """Primary level filter must return Primary jobs across models."""
        response = self.client.get(reverse("core:job-level", kwargs={"level_slug": "primary"}))
        self.assertEqual(response.status_code, 200)
        jobs = list(response.context["jobs"])
        job_titles = [j.title if hasattr(j, "title") else j.designation for j in jobs]

        self.assertIn("Primary English Teacher", job_titles)
        self.assertIn("Primary Mathematics Teacher", job_titles)
        self.assertNotIn("Secondary Physics Teacher", job_titles)
        self.assertEqual(len(jobs), 2)

    def test_unpublished_and_inactive_jobs_are_excluded(self):
        """Draft, pending, and closed jobs must never appear in search results."""
        response = self.client.get(reverse("core:current-vacancies"))
        self.assertEqual(response.status_code, 200)
        jobs = list(response.context["jobs"])
        job_ids = [j.id for j in jobs]

        self.assertNotIn(self.job_draft.id, job_ids)
        self.assertNotIn(self.staff_job_inactive.id, job_ids)

    def test_valid_filter_with_no_matches_shows_empty_state_and_recovery(self):
        """Valid category with 0 vacancies must return 200, clean empty state, and suggestions."""
        response = self.client.get(reverse("core:job-subject", kwargs={"subject_slug": "hindi-teacher"}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_results"], 0)
        self.assertContains(response, "No jobs found matching your criteria")
        self.assertContains(response, "Clear all filters")
        self.assertContains(response, "Browse All Current Vacancies")

    def test_invalid_slug_returns_404(self):
        """Unknown subject or location slug must return HTTP 404."""
        resp_subj = self.client.get("/jobs/india/astronaut-teacher/")
        self.assertEqual(resp_subj.status_code, 404)

        resp_loc = self.client.get("/jobs/non-existent-city-xyz/")
        self.assertEqual(resp_loc.status_code, 404)

    def test_manipal_locality_queries_correctly(self):
        """Manipal is classified as a city/locality and queries cleanly without 500 error."""
        response = self.client.get(reverse("core:job-location", kwargs={"location_slug": "manipal"}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_city"]["canonical_name"], "Manipal")
        self.assertTrue(response.context["active_city"].get("is_locality"))


class SEOAndUrlArchitectureTests(BaseSEOTestSetup):
    """Validates dynamic titles, meta descriptions, canonical URLs, breadcrumbs, and sitemap."""

    def test_subject_seo_metadata(self):
        """Subject page must have unique H1, title, meta description, and canonical URL."""
        response = self.client.get(reverse("core:job-subject", kwargs={"subject_slug": "english-teacher"}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<title>English Teacher Jobs in India | SevaJobs</title>")
        self.assertContains(response, "English Teacher Jobs in India</h1>")
        self.assertContains(response, 'rel="canonical"')
        self.assertContains(response, "/jobs/india/english-teacher/")

    def test_state_seo_metadata(self):
        """State page must have clean state title, H1, and canonical URL."""
        response = self.client.get(reverse("core:job-location", kwargs={"location_slug": "telangana"}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<title>Teaching Jobs in Telangana | SevaJobs</title>")
        self.assertContains(response, "Teaching Jobs in Telangana</h1>")
        self.assertContains(response, "/jobs/telangana/")

    def test_city_seo_metadata(self):
        """City page must have clean city title, H1, and canonical URL."""
        response = self.client.get(reverse("core:job-location", kwargs={"location_slug": "hyderabad"}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<title>Teaching Jobs in Hyderabad | SevaJobs</title>")
        self.assertContains(response, "Teaching Jobs in Hyderabad</h1>")
        self.assertContains(response, "/jobs/hyderabad/")

    def test_query_parameter_grade_backward_compatibility(self):
        """Preserve query param ?grade=Primary on /jobs/ and /current-vacancies."""
        resp_jobs = self.client.get(f"{reverse('core:job-search')}?grade=Primary")
        self.assertEqual(resp_jobs.status_code, 200)
        self.assertEqual(resp_jobs.context["total_results"], 2)

        resp_vacancies = self.client.get(f"{reverse('core:current-vacancies')}?grade=Primary")
        self.assertEqual(resp_vacancies.status_code, 200)
        self.assertEqual(resp_vacancies.context["total_results"], 2)

    def test_job_detail_does_not_collide_with_location_slug(self):
        """Job detail route /jobs/<slug>/ must resolve properly without collision."""
        response = self.client.get(reverse("core:job-detail", kwargs={"slug": self.job_tg_physics.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Secondary Physics Teacher")
        self.assertContains(response, "Telangana Model School")

    def test_sitemap_xml_contains_canonical_routes(self):
        """sitemap.xml must return valid XML containing canonical subjects, cities, and states."""
        response = self.client.get(reverse("django.contrib.sitemaps.views.sitemap"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/xml")

        root = ET.fromstring(response.content)
        locs = [elem.text for elem in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]

        # Must contain canonical routes
        self.assertTrue(any("/jobs/india/mathematics-teacher/" in loc for loc in locs))
        self.assertTrue(any("/jobs/hyderabad/" in loc for loc in locs))
        self.assertTrue(any("/jobs/telangana/" in loc for loc in locs))
        self.assertTrue(any("/current-vacancies/" in loc for loc in locs))

    def test_robots_txt(self):
        """robots.txt must point to sitemap.xml and disallow protected admin/api endpoints."""
        response = self.client.get(reverse("robots-txt"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("User-agent: *", content)
        self.assertIn("Disallow: /admin/", content)
        self.assertIn("Disallow: /api/", content)
        self.assertIn("Sitemap:", content)
        self.assertIn("/sitemap.xml", content)
