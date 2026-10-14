"""
Comprehensive automated unit & integration test suite for End-to-End Requirement Workflow.
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import User
from apps.jobs.models import (
    InstitutionRequirement,
    RequirementCandidateMatch,
    RequirementActivityLog,
    RequirementInternalNote,
    Job,
)
from apps.jobs.requirement_services import (
    RequirementWorkflowService,
    RequirementAssignmentService,
    RequirementConversionService,
    RequirementPipelineIntegrationService,
)
from apps.jobs.matching_service import CandidateMatchingService
from apps.jobs.tasks import process_requirement_matching_task
from apps.accounts.models import JobSeekerProfile


class RequirementWorkflowTestCase(TestCase):
    def setUp(self):
        self.client = Client()

        # Users
        self.admin_user = User.objects.create_superuser(
            email="admin@sevajobs.com",
            password="Password123!",
            role="super_admin",
            first_name="Admin",
            last_name="User",
        )
        self.staff_user = User.objects.create_user(
            email="staff@sevajobs.com",
            password="Password123!",
            role="staff",
            first_name="Rahul",
            last_name="Staff",
        )
        self.recruiter_user = User.objects.create_user(
            email="recruiter@school.com",
            password="Password123!",
            role="recruiter",
            first_name="School",
            last_name="Recruiter",
            is_email_verified=True,
        )
        self.candidate_user = User.objects.create_user(
            email="physics_teacher@gmail.com",
            password="Password123!",
            role="job_seeker",
            first_name="Priya",
            last_name="Sharma",
            is_email_verified=True,
        )

        # Candidate Profile
        self.job_seeker_profile = JobSeekerProfile.objects.create(
            user=self.candidate_user,
            subject="Physics",
            designation="PGT Teacher",
            experience_years=4,
            city="Hyderabad",
            state="Telangana",
        )

    def test_requirement_submission_creates_instance_and_req_code(self):
        url = reverse("jobs:submit-requirement")
        payload = {
            "institution_name": "Greenwood High School",
            "phone_number": "9876543210",
            "subject": "Physics",
            "qualification": "M.Sc Physics",
            "teaching_grade": "PGT",
            "positions_count": "3",
            "location": "Hyderabad",
            "experience_range": "3-5",
            "salary_min": "40000",
            "salary_max": "60000",
        }

        response = self.client.post(url, data=payload)
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertTrue(data["req_code"].startswith("REQ-2026-"))

        requirement = InstitutionRequirement.objects.get(pk=data["requirement_id"])
        self.assertEqual(requirement.institution_name, "Greenwood High School")
        self.assertEqual(requirement.positions_count, 3)
        self.assertEqual(requirement.status, InstitutionRequirement.RequirementStatus.CANDIDATES_FOUND)

    def test_duplicate_submission_prevention(self):
        url = reverse("jobs:submit-requirement")
        payload = {
            "institution_name": "St. Johns Academy",
            "phone_number": "9876543211",
            "subject": "Mathematics",
            "qualification": "M.Sc Maths",
            "teaching_grade": "TGT",
            "location": "Bengaluru",
        }

        res1 = self.client.post(url, data=payload)
        self.assertEqual(res1.status_code, 201)

        res2 = self.client.post(url, data=payload)
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()
        self.assertTrue(data2.get("duplicate"))

    def test_requirement_workflow_state_machine(self):
        req = InstitutionRequirement.objects.create(
            institution_name="Delhi Public School",
            phone_number="9876543212",
            subject="Chemistry",
            qualification="M.Sc Chemistry",
            teaching_grade="PGT",
            positions_count=2,
            location="Delhi",
            status=InstitutionRequirement.RequirementStatus.SUBMITTED,
        )

        # Assign
        RequirementWorkflowService.assign(req, self.staff_user, self.admin_user, priority="high")
        req.refresh_from_db()
        self.assertEqual(req.status, InstitutionRequirement.RequirementStatus.ASSIGNED)
        self.assertEqual(req.assigned_staff, self.staff_user)

        # Start Work
        RequirementWorkflowService.start_work(req, self.staff_user)
        req.refresh_from_db()
        self.assertEqual(req.status, InstitutionRequirement.RequirementStatus.IN_PROGRESS)

    def test_requirement_assignment_service(self):
        req = InstitutionRequirement.objects.create(
            institution_name="Oakridge International",
            phone_number="9876543213",
            subject="English",
            qualification="M.A English",
            teaching_grade="TGT",
            positions_count=1,
            location="Hyderabad",
        )

        assigned_req = RequirementAssignmentService.assign_employee(
            requirement_id=req.pk,
            staff_user=self.staff_user,
            assigned_by_user=self.admin_user,
            priority="urgent",
            notes="Client needs urgent placement by Friday.",
        )

        self.assertEqual(assigned_req.assigned_staff, self.staff_user)
        self.assertEqual(assigned_req.priority, "urgent")
        self.assertTrue(RequirementInternalNote.objects.filter(requirement=req).exists())

    def test_candidate_matching_engine(self):
        req = InstitutionRequirement.objects.create(
            institution_name="Meridian School",
            phone_number="9876543214",
            subject="Physics",
            qualification="M.Sc Physics",
            teaching_grade="PGT",
            positions_count=1,
            location="Hyderabad",
            min_experience_years=3,
        )

        matches = CandidateMatchingService.find_and_store_matches(req)
        self.assertTrue(len(matches) > 0)
        match = matches[0]
        self.assertEqual(match.candidate, self.candidate_user)
        self.assertTrue(match.match_score >= 70)
        self.assertTrue(len(match.explanation_list) > 0)

    def test_multi_position_tracking(self):
        req = InstitutionRequirement.objects.create(
            institution_name="Silver Oaks School",
            phone_number="9876543215",
            subject="Physics",
            qualification="M.Sc Physics",
            teaching_grade="PGT",
            positions_count=3,
            location="Hyderabad",
        )

        match1 = RequirementCandidateMatch.objects.create(
            requirement=req,
            candidate=self.candidate_user,
            match_score=90,
            status=RequirementCandidateMatch.MatchStatus.INTERVIEW_SCHEDULED,
        )

        # Joined Candidate 1
        RequirementPipelineIntegrationService.mark_joined(match1, actor=self.staff_user)
        req.refresh_from_db()
        self.assertEqual(req.joined_count, 1)
        self.assertEqual(req.status, InstitutionRequirement.RequirementStatus.PARTIALLY_FILLED)
        self.assertFalse(req.is_fulfilled)

        # Create candidate 2 & candidate 3
        cand2 = User.objects.create_user(email="c2@gmail.com", password="P1!", role="job_seeker")
        cand3 = User.objects.create_user(email="c3@gmail.com", password="P1!", role="job_seeker")
        m2 = RequirementCandidateMatch.objects.create(
            requirement=req,
            candidate=cand2,
            match_score=85,
            status=RequirementCandidateMatch.MatchStatus.INTERVIEW_SCHEDULED,
        )
        m3 = RequirementCandidateMatch.objects.create(
            requirement=req,
            candidate=cand3,
            match_score=80,
            status=RequirementCandidateMatch.MatchStatus.INTERVIEW_SCHEDULED,
        )

        RequirementPipelineIntegrationService.mark_joined(m2, actor=self.staff_user)
        RequirementPipelineIntegrationService.mark_joined(m3, actor=self.staff_user)

        req.refresh_from_db()
        self.assertEqual(req.joined_count, 3)
        self.assertEqual(req.status, InstitutionRequirement.RequirementStatus.FULFILLED)
        self.assertTrue(req.is_fulfilled)

    def test_requirement_conversion_to_job_draft(self):
        req = InstitutionRequirement.objects.create(
            institution_name="Chaitanya Techno School",
            phone_number="9876543216",
            subject="Mathematics",
            qualification="M.Sc Maths",
            teaching_grade="PGT",
            positions_count=2,
            location="Vijayawada",
            salary_min=35000,
            salary_max=55000,
        )

        job = RequirementConversionService.convert_to_job_draft(req.pk, actor=self.admin_user)
        self.assertIsNotNone(job)
        self.assertEqual(job.status, Job.Status.DRAFT)
        self.assertEqual(job.vacancies, 2)
        self.assertEqual(job.salary_min, 35000)

        req.refresh_from_db()
        self.assertEqual(req.converted_job, job)
        self.assertEqual(req.status, InstitutionRequirement.RequirementStatus.JOB_CREATED)

        # Idempotency check: Converting again returns existing job
        job2 = RequirementConversionService.convert_to_job_draft(req.pk, actor=self.admin_user)
        self.assertEqual(job.id, job2.id)

    def test_celery_async_matching_task(self):
        req = InstitutionRequirement.objects.create(
            institution_name="Narayana Olympiad School",
            phone_number="9876543217",
            subject="Physics",
            qualification="M.Sc Physics",
            teaching_grade="PGT",
            positions_count=1,
            location="Hyderabad",
        )

        result_count = process_requirement_matching_task(str(req.pk))
        self.assertTrue(result_count > 0)
        req.refresh_from_db()
        self.assertEqual(req.status, InstitutionRequirement.RequirementStatus.CANDIDATES_FOUND)

    def test_security_object_level_permissions(self):
        req = InstitutionRequirement.objects.create(
            institution_name="Private Academy",
            phone_number="9876543218",
            subject="Biology",
            qualification="M.Sc Botany",
            teaching_grade="TGT",
            positions_count=1,
            location="Vizag",
        )

        # Logged in candidate cannot access internal requirement detail
        self.client.force_login(self.candidate_user)
        res = self.client.get(reverse("jobs:requirement-detail", kwargs={"pk": req.pk}))
        self.assertEqual(res.status_code, 403)

        # Staff can access requirement detail
        self.client.force_login(self.staff_user)
        res_staff = self.client.get(reverse("jobs:requirement-detail", kwargs={"pk": req.pk}))
        self.assertEqual(res_staff.status_code, 200)

    def test_candidate_state_machine_transitions(self):
        """Test candidate recruitment lifecycle state transitions and restrictions."""
        from apps.jobs.requirement_services import CandidateStateTransitionError
        req = InstitutionRequirement.objects.create(
            institution_name="State Machine Academy",
            phone_number="9876543999",
            subject="English",
            qualification="M.A English",
            teaching_grade="TGT",
            positions_count=1,
            location="Hyderabad",
        )
        match = RequirementCandidateMatch.objects.create(
            requirement=req, candidate=self.candidate_user, match_score=90
        )

        # 1. State: MATCHED
        actions = match.allowed_actions
        self.assertTrue(actions["can_shortlist"])
        self.assertFalse(actions["can_interview"])
        self.assertFalse(actions["can_join"])
        self.assertTrue(actions["can_reject"])

        # Invalid Direct Transition: MATCHED -> JOINED
        with self.assertRaises(CandidateStateTransitionError):
            RequirementPipelineIntegrationService.mark_joined(match.pk, actor=self.staff_user)

        # 2. Transition: MATCHED -> SHORTLISTED
        RequirementPipelineIntegrationService.shortlist_candidate(match.pk, actor=self.staff_user)
        match.refresh_from_db()
        self.assertEqual(match.status, "shortlisted")

        actions = match.allowed_actions
        self.assertFalse(actions["can_shortlist"])
        self.assertTrue(actions["can_interview"])
        self.assertFalse(actions["can_join"])
        self.assertTrue(actions["can_reject"])

        # 3. Transition: SHORTLISTED -> INTERVIEW_SCHEDULED
        RequirementPipelineIntegrationService.schedule_interview(match.pk, actor=self.staff_user, interview_details={"date": "2026-10-01", "time": "10:00", "mode": "Online"})
        match.refresh_from_db()
        self.assertEqual(match.status, "interview_scheduled")

        actions = match.allowed_actions
        self.assertFalse(actions["can_interview"])
        self.assertTrue(actions["can_join"])
        self.assertTrue(actions["can_reject"])

        # 4. Transition: INTERVIEW_SCHEDULED -> JOINED
        RequirementPipelineIntegrationService.mark_joined(match.pk, actor=self.staff_user)
        match.refresh_from_db()
        self.assertEqual(match.status, "joined")

        # Terminal JOINED checks
        actions = match.allowed_actions
        self.assertFalse(actions["can_join"])
        self.assertFalse(actions["can_reject"])

        # Blocked: JOINED -> REJECTED
        with self.assertRaises(CandidateStateTransitionError):
            RequirementPipelineIntegrationService.reject_candidate(match.pk, actor=self.staff_user, reason="Late rejection")

    def test_overfill_protection(self):
        """Test overfill protection prevents marking more candidates joined than required positions."""
        from apps.jobs.requirement_services import CandidateStateTransitionError
        req = InstitutionRequirement.objects.create(
            institution_name="Overfill School",
            phone_number="9876543888",
            subject="Chemistry",
            qualification="M.Sc",
            teaching_grade="PGT",
            positions_count=1,
            location="Hyderabad",
        )
        c1 = User.objects.create_user(email="c1_overfill@test.com", password="P1!", role="job_seeker")
        c2 = User.objects.create_user(email="c2_overfill@test.com", password="P1!", role="job_seeker")

        m1 = RequirementCandidateMatch.objects.create(requirement=req, candidate=c1, match_score=90, status="interview_scheduled")
        m2 = RequirementCandidateMatch.objects.create(requirement=req, candidate=c2, match_score=85, status="interview_scheduled")

        # Join 1st candidate (1/1 filled -> FULFILLED)
        RequirementPipelineIntegrationService.mark_joined(m1.pk, actor=self.staff_user)
        req.refresh_from_db()
        self.assertEqual(req.joined_count, 1)
        self.assertTrue(req.is_fulfilled)

        # Attempting to join 2nd candidate must raise overfill error
        with self.assertRaises(CandidateStateTransitionError):
            RequirementPipelineIntegrationService.mark_joined(m2.pk, actor=self.staff_user)

    def test_rejection_from_matched_and_shortlisted(self):
        """Test candidate can be rejected from active states."""
        req = InstitutionRequirement.objects.create(
            institution_name="Rejection School",
            phone_number="9876543777",
            subject="Civics",
            qualification="M.A",
            teaching_grade="TGT",
            positions_count=1,
            location="Hyderabad",
        )
        c1 = User.objects.create_user(email="c1_reject@test.com", password="P1!", role="job_seeker")
        m1 = RequirementCandidateMatch.objects.create(requirement=req, candidate=c1, match_score=80)

        # Reject from MATCHED
        RequirementPipelineIntegrationService.reject_candidate(m1.pk, actor=self.staff_user, reason="Subject mismatch")
        m1.refresh_from_db()
        self.assertEqual(m1.status, "rejected")
        self.assertEqual(m1.rejection_reason, "Subject mismatch")
        self.assertTrue(m1.allowed_actions["is_rejected"])

    def test_requirement_candidate_interview_view(self):
        """Test full page interview scheduling view GET and POST actions."""
        req = InstitutionRequirement.objects.create(
            institution_name="Full Page Interview Academy",
            phone_number="9876543666",
            subject="Mathematics",
            qualification="M.Sc Maths",
            teaching_grade="PGT",
            positions_count=1,
            location="Hyderabad",
        )
        match = RequirementCandidateMatch.objects.create(
            requirement=req, candidate=self.candidate_user, match_score=95, status="shortlisted"
        )

        url = reverse("jobs:requirement-candidate-interview", kwargs={"pk": req.pk, "match_id": match.pk})

        # 1. Staff GET view
        self.client.force_login(self.staff_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/recruiter/requirement_schedule_interview.html")

        # 2. Staff POST schedule interview
        payload = {
            "interview_date": "2026-10-15",
            "interview_time": "11:00",
            "interview_mode": "Online",
            "location_or_link": "https://meet.google.com/test-meet",
            "interviewer_name": "Dr. Principal",
            "interview_notes": "Please join 5 mins early.",
        }
        post_res = self.client.post(url, data=payload)
        self.assertEqual(post_res.status_code, 302)

        match.refresh_from_db()
        self.assertEqual(match.status, "interview_scheduled")
        self.assertTrue(match.allowed_actions["is_interviewed"])
        self.assertTrue(match.allowed_actions["can_join"])

    def test_admin_and_recruiter_interview_routing(self):
        """Test Admin and Recruiter interview URLs preserve their respective dashboard sidebar contexts."""
        req = InstitutionRequirement.objects.create(
            institution_name="Role Routing Academy",
            phone_number="9876543555",
            subject="Physics",
            qualification="M.Sc Physics",
            teaching_grade="PGT",
            positions_count=1,
            location="Hyderabad",
        )
        match = RequirementCandidateMatch.objects.create(
            requirement=req, candidate=self.candidate_user, match_score=90, status="shortlisted"
        )

        admin_url = reverse("admin-panel:requirement-candidate-interview", kwargs={"pk": req.pk, "match_id": match.pk})
        recruiter_url = reverse("recruiter:requirement-candidate-interview", kwargs={"pk": req.pk, "match_id": match.pk})

        # Admin GET
        self.client.force_login(self.admin_user)
        session = self.client.session
        session["current_role_scope"] = "admin"
        session.save()
        self.client.cookies["sessionid_admin"] = session.session_key
        self.client.cookies["sessionid"] = session.session_key

        admin_res = self.client.get(admin_url)
        self.assertEqual(admin_res.status_code, 200)
        self.assertEqual(admin_res.context["layout_template"], "dashboard/admin/_layout.html")
        self.assertEqual(admin_res.context["sidebar_section"], "admin_requirements")

        # Recruiter GET
        from apps.recruiters.models import RecruiterProfile, Company
        company = Company.objects.create(name="Routing Test School", slug="routing-test-school")
        rec_profile = RecruiterProfile.objects.create(user=self.recruiter_user, company=company, designation="HR")

        self.client.force_login(self.recruiter_user)
        session = self.client.session
        session["current_role_scope"] = "recruiter"
        session.save()
        self.client.cookies["sessionid_recruiter"] = session.session_key
        self.client.cookies["sessionid"] = session.session_key

        req.posted_by_user = self.recruiter_user
        req.recruiter = rec_profile
        req.company = company
        req.save()
        rec_res = self.client.get(recruiter_url)
        self.assertEqual(rec_res.status_code, 200)
        self.assertEqual(rec_res.context["layout_template"], "dashboard/recruiter/_layout.html")
        self.assertEqual(rec_res.context["sidebar_section"], "requirements-list")

    def test_requirement_assignment_and_reassignment_workflow(self):
        """Test initial assignment to Staff A, reassignment to Staff B, audit logging, and authorization checks."""
        req = InstitutionRequirement.objects.create(
            institution_name="Test Public School",
            phone_number="9876543210",
            subject="Mathematics",
            qualification="M.Sc Maths",
            teaching_grade="TGT",
            positions_count=2,
            location="Hyderabad",
        )
        staff_b = User.objects.create_user(
            email="staff_b@sevajobs.com",
            password="Password123!",
            role="staff",
            first_name="Amit",
            last_name="Staff",
            is_email_verified=True,
        )

        self.client.force_login(self.admin_user)
        session = self.client.session
        session["current_role_scope"] = "admin"
        session.save()
        self.client.cookies["sessionid_admin"] = session.session_key
        self.client.cookies["sessionid"] = session.session_key

        # Initial Assignment to self.staff_user
        assign_url = reverse("jobs:requirement-assign", kwargs={"pk": req.pk})
        res = self.client.post(assign_url, {"staff_id": self.staff_user.pk, "priority": "high", "notes": "Urgently fill math teacher."})
        self.assertEqual(res.status_code, 302)

        req.refresh_from_db()
        self.assertEqual(req.assigned_staff, self.staff_user)
        self.assertEqual(req.status, "assigned")
        self.assertEqual(req.priority, "high")

        # Verify audit activity log
        logs = req.activity_logs.filter(event_type="assigned")
        self.assertTrue(logs.exists())
        self.assertIn("assigned to Rahul Staff", logs.first().description)

        # Reassignment to staff_b
        res2 = self.client.post(assign_url, {"staff_id": staff_b.pk, "priority": "urgent", "notes": "Reassigned to Amit."})
        self.assertEqual(res2.status_code, 302)

        req.refresh_from_db()
        self.assertEqual(req.assigned_staff, staff_b)
        self.assertEqual(req.priority, "urgent")

        latest_log = req.activity_logs.filter(event_type="assigned").order_by("-created_at").first()
        self.assertIn("reassigned from Rahul Staff to Amit Staff", latest_log.description)

        # Verify assigned requirement appears in AdminAssignedRecruitmentView context
        assigned_rec_url = reverse("admin-panel:assigned-recruitment")
        rec_res = self.client.get(assigned_rec_url)
        self.assertEqual(rec_res.status_code, 200)
        self.assertIn(req, rec_res.context["requirements"])





