import json
from django.test import TestCase, Client
from django.urls import reverse
from apps.accounts.models import User, JobSeekerProfile
from apps.recruiters.models import RecruiterProfile, Company as CompanyProfile
from apps.teaching.models import TeacherProfile
from apps.jobs.models import Job, InstitutionRequirement, RequirementCandidateMatch, Skill, Qualification
from apps.jobs.autocomplete import normalize_search_query
from apps.jobs.matching_service import CandidateMatchingService

class TeacherSearchAndRequirementTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Create recruiter user & profile
        self.recruiter_user = User.objects.create_user(
            email="recruiter@school.com",
            password="Password123!",
            first_name="Greenwood",
            last_name="Admin",
            role=User.Role.RECRUITER,
            phone="9876543210",
            is_email_verified=True
        )
        self.company = CompanyProfile.objects.create(
            name="Greenwood High School",
            slug="greenwood-high-school",
            city="Hyderabad"
        )
        self.recruiter_profile = RecruiterProfile.objects.create(
            user=self.recruiter_user,
            company=self.company
        )

        # Create candidate user & profile
        self.candidate_user = User.objects.create_user(
            email="teacher@gmail.com",
            password="Password123!",
            first_name="Sai",
            last_name="Kumar",
            role=User.Role.JOB_SEEKER,
            phone="9988776655"
        )
        self.candidate_seeker = JobSeekerProfile.objects.create(
            user=self.candidate_user,
            headline="PGT Physics Teacher",
            subject="Physics",
            designation="PGT Physics",
            city="Hyderabad",
            current_location="Hyderabad",
            experience_years=5,
            is_open_to_work=True
        )
        self.teacher_profile = TeacherProfile.objects.create(
            user=self.candidate_user,
            applying_position="pgt",
            subject_specialization="Physics",
            total_experience_years=5.0
        )

        # Create sample job
        self.job = Job.objects.create(
            recruiter=self.recruiter_profile,
            company=self.company,
            title="PGT Physics Teacher",
            slug="pgt-physics-teacher",
            description="Seeking PGT Physics Teacher for High School.",
            location="Hyderabad",
            city="Hyderabad",
            experience_level=Job.ExperienceLevel.THREE_SIX_YEARS,
            min_experience_years=3,
            max_experience_years=7,
            status=Job.Status.ACTIVE,
            approval_status=Job.ApprovalStatus.APPROVED
        )

    # -------------------------------------------------------------------------
    # 1. Normalization & Autocomplete Tests
    # -------------------------------------------------------------------------
    def test_term_normalization(self):
        self.assertEqual(normalize_search_query("math"), "Mathematics")
        self.assertEqual(normalize_search_query("cs"), "Computer Science")
        self.assertEqual(normalize_search_query("phy"), "Physics")
        self.assertEqual(normalize_search_query("neet"), "NEET Faculty")

    def test_autocomplete_api_keywords(self):
        url = reverse("jobs:autocomplete")
        response = self.client.get(url, {"q": "phy"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("suggestions", data)
        results = [s.get("value") or s.get("label") for s in data["suggestions"]]
        self.assertTrue(any("Physics" in str(r) for r in results))

    def test_autocomplete_api_location(self):
        url = reverse("jobs:autocomplete")
        response = self.client.get(url, {"q": "hyd", "type": "location"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        results = [s.get("value") or s.get("label") for s in data["suggestions"]]
        self.assertTrue(len(results) >= 0)

    # -------------------------------------------------------------------------
    # 2. Search View Integration Test
    # -------------------------------------------------------------------------
    def test_job_search_view(self):
        url = reverse("core:job-search")
        response = self.client.get(url, {
            "q": "physics",
            "experience": "5",
            "location": "Hyderabad"
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Physics")

    # -------------------------------------------------------------------------
    # 3. Quick Requirement Submission Tests
    # -------------------------------------------------------------------------
    def test_submit_requirement_success(self):
        url = reverse("jobs:submit-requirement")
        payload = {
            "institution_name": "Greenwood High School",
            "contact_phone": "9876543210",
            "subject": "Physics",
            "qualification": "msc",
            "teaching_grade": "pgt",
            "positions": 2,
            "location": "Hyderabad",
            "experience": "5_years",
            "min_salary": 40000,
            "max_salary": 60000,
            "salary_period": "month"
        }
        response = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("requirement_id", data)

        req_id = data["requirement_id"]
        req = InstitutionRequirement.objects.get(id=req_id)
        self.assertEqual(req.subject, "Physics")
        self.assertEqual(req.positions_count, 2)

    def test_submit_requirement_duplicate_prevention(self):
        url = reverse("jobs:submit-requirement")
        payload = {
            "institution_name": "Greenwood High School",
            "contact_phone": "9876543210",
            "subject": "Physics",
            "qualification": "msc",
            "teaching_grade": "pgt",
            "positions": 2,
            "location": "Hyderabad",
            "experience": "5_years"
        }
        # First submission
        res1 = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res1.status_code, 201)

        # Immediate duplicate submission
        res2 = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()
        self.assertTrue(data2.get("duplicate"))

    # -------------------------------------------------------------------------
    # 4. Candidate Matching Engine Test
    # -------------------------------------------------------------------------
    def test_candidate_matching_engine(self):
        req = InstitutionRequirement.objects.create(
            recruiter=self.recruiter_profile,
            posted_by_user=self.recruiter_user,
            institution_name="Greenwood High School",
            phone_number="9876543210",
            subject="Physics",
            qualification="msc",
            teaching_grade="pgt",
            positions_count=1,
            location="Hyderabad",
            experience_range="5_years"
        )
        matches = CandidateMatchingService.match_requirement(req)
        self.assertTrue(len(matches) > 0)
        top_match = matches[0]
        self.assertEqual(top_match.candidate, self.candidate_user)
        self.assertGreaterEqual(top_match.match_score, 70)
        self.assertTrue(len(top_match.explanation_list) > 0)

    # -------------------------------------------------------------------------
    # 5. Recruiter Requirements Dashboard Views Test
    # -------------------------------------------------------------------------
    def test_recruiter_requirements_list_and_detail(self):
        self.client.force_login(self.recruiter_user, backend="django.contrib.auth.backends.ModelBackend")
        session = self.client.session
        session['current_role_scope'] = 'recruiter'
        session.save()
        self.client.cookies["sessionid_recruiter"] = session.session_key
        self.client.cookies["sessionid"] = session.session_key

        req = InstitutionRequirement.objects.create(
            recruiter=self.recruiter_profile,
            posted_by_user=self.recruiter_user,
            institution_name="Greenwood High School",
            phone_number="9876543210",
            subject="Physics",
            qualification="msc",
            teaching_grade="pgt",
            positions_count=1,
            location="Hyderabad",
            experience_range="5_years"
        )
        CandidateMatchingService.match_requirement(req)

        # List view
        list_url = reverse("recruiter:requirements-list")
        res_list = self.client.get(list_url)
        self.assertEqual(res_list.status_code, 200)
        self.assertContains(res_list, "Greenwood High School")

        # Detail view
        detail_url = reverse("recruiter:requirement-detail", kwargs={"pk": req.pk})
        res_detail = self.client.get(detail_url)
        self.assertEqual(res_detail.status_code, 200)
        self.assertContains(res_detail, "Sai Kumar")

    def test_recruiter_match_action_shortlist(self):
        self.client.force_login(self.recruiter_user, backend="django.contrib.auth.backends.ModelBackend")
        session = self.client.session
        session['current_role_scope'] = 'recruiter'
        session.save()
        self.client.cookies["sessionid_recruiter"] = session.session_key
        self.client.cookies["sessionid"] = session.session_key

        req = InstitutionRequirement.objects.create(
            recruiter=self.recruiter_profile,
            posted_by_user=self.recruiter_user,
            institution_name="Greenwood High School",
            phone_number="9876543210",
            subject="Physics",
            qualification="msc",
            teaching_grade="pgt",
            positions_count=1,
            location="Hyderabad",
            experience_range="5_years"
        )
        matches = CandidateMatchingService.match_requirement(req)
        match = matches[0]

        action_url = reverse("recruiter:requirement-match-action", kwargs={"pk": req.pk})
        res = self.client.post(action_url, {
            "match_id": str(match.id),
            "action": "shortlist"
        })
        self.assertEqual(res.status_code, 302)

        match.refresh_from_db()
        self.assertEqual(match.status, RequirementCandidateMatch.MatchStatus.SHORTLISTED)
