"""Tests for CandidateJobAlertMatchingService."""

from datetime import timedelta
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import JobSeekerProfile, User
from apps.jobs.models import Job, StaffJob
from apps.jobs.job_alert_matching_service import CandidateJobAlertMatchingService
from apps.notifications.models import CandidateJobAlertDelivery, JobAlertCampaign
from apps.recruiters.models import Company, RecruiterProfile


class CandidateJobAlertMatchingServiceTests(TestCase):
    def setUp(self):
        # 1. Create candidate user with profile
        self.candidate_user = User.objects.create_user(
            username="candidate_english",
            email="english_teacher@example.com",
            password="testpassword123",
            first_name="Smrithi",
            last_name="Rajan",
            role="job_seeker",
            is_active=True,
        )
        self.candidate_profile = JobSeekerProfile.objects.create(
            user=self.candidate_user,
            designation="English Teacher",
            subject="English",
            preferred_location="Chennai",
            experience_years=3,
            expected_salary=30000,
            job_alerts_enabled=True,
        )

        # 2. Create recruiter company & user
        self.recruiter_user = User.objects.create_user(
            username="recruiter_test",
            email="recruiter@example.com",
            password="testpassword123",
            role="recruiter",
        )
        self.company = Company.objects.create(name="St. Jude's Academy", location="Chennai")
        self.recruiter_profile = RecruiterProfile.objects.create(
            user=self.recruiter_user,
            company=self.company,
        )

        # 3. Create recruiter Job (English - Matches)
        self.job_english = Job.objects.create(
            title="Senior English Teacher (PGT)",
            slug="senior-english-teacher-pgt",
            company=self.company,
            recruiter=self.recruiter_profile,
            location="Chennai",
            min_experience_years=2,
            max_experience_years=5,
            experience_level=Job.ExperienceLevel.THREE_SIX_YEARS,
            salary_min=25000,
            salary_max=35000,
            status=Job.Status.ACTIVE,
            approval_status=Job.ApprovalStatus.APPROVED,
            is_active=True,
            deadline=timezone.now().date() + timedelta(days=30),
        )

        # 4. Create recruiter Job (Maths - Must NOT match English teacher)
        self.job_maths = Job.objects.create(
            title="Mathematics Teacher (TGT)",
            slug="mathematics-teacher-tgt",
            company=self.company,
            recruiter=self.recruiter_profile,
            location="Chennai",
            min_experience_years=2,
            max_experience_years=5,
            experience_level=Job.ExperienceLevel.THREE_SIX_YEARS,
            salary_min=25000,
            salary_max=35000,
            status=Job.Status.ACTIVE,
            approval_status=Job.ApprovalStatus.APPROVED,
            is_active=True,
            deadline=timezone.now().date() + timedelta(days=30),
        )

        # 5. Create StaffJob (English - Matches)
        self.staff_user = User.objects.create_user(
            username="staff_admin",
            email="staff@example.com",
            password="testpassword123",
            role="staff",
        )
        self.staff_job_english = StaffJob.objects.create(
            job_id="STAFF-ENG-001",
            designation="High School English Teacher",
            organization_name="Greenwood Matric School",
            qualification="B.Ed, M.A. English",
            job_location="Chennai",
            offered_salary=30000,
            phone_number="9876543210",
            email="school@greenwood.edu",
            status=StaffJob.Status.ACTIVE,
            is_active=True,
            created_by=self.staff_user,
            published_at=timezone.now(),
        )

    def test_english_candidate_matches_english_jobs_and_not_maths(self):
        """Verify subject conflict guard: English teacher matches English jobs but never Maths."""
        matches = CandidateJobAlertMatchingService.get_matching_jobs_for_candidate(self.candidate_user)
        matched_ids = [m["id"] for m in matches]

        self.assertIn(str(self.job_english.id), matched_ids)
        self.assertIn(str(self.staff_job_english.id), matched_ids)
        self.assertNotIn(str(self.job_maths.id), matched_ids)

    def test_maths_candidate_matches_maths_job(self):
        """Verify candidate with subject=Mathematics matches Maths job."""
        maths_candidate = User.objects.create_user(
            username="candidate_maths",
            email="maths_teacher@example.com",
            password="testpassword123",
            first_name="Ramesh",
            last_name="Kumar",
            role="job_seeker",
            is_active=True,
        )
        JobSeekerProfile.objects.create(
            user=maths_candidate,
            designation="Maths Teacher",
            subject="Mathematics",
            preferred_location="Chennai",
            experience_years=3,
            job_alerts_enabled=True,
        )

        matches = CandidateJobAlertMatchingService.get_matching_jobs_for_candidate(maths_candidate)
        matched_ids = [m["id"] for m in matches]

        self.assertIn(str(self.job_maths.id), matched_ids)
        self.assertNotIn(str(self.job_english.id), matched_ids)

    def test_deduplication_window_excludes_recently_alerted_vacancy(self):
        """Verify deduplication guard: candidate who received alert for a vacancy in last 14 days is not matched."""
        campaign = JobAlertCampaign.objects.create(
            name="Past Campaign",
            created_by=self.staff_user,
            subject="Job Alerts",
            body_html="<p>Jobs</p>",
            status=JobAlertCampaign.Status.COMPLETED,
        )
        # Create delivery 5 days ago (within 14-day window)
        CandidateJobAlertDelivery.record_delivery(
            candidate=self.candidate_user,
            job_id=str(self.job_english.id),
            campaign=campaign,
            sent_at=timezone.now() - timedelta(days=5),
        )

        matches = CandidateJobAlertMatchingService.get_matching_jobs_for_candidate(
            self.candidate_user,
            dedup_window_days=14,
        )
        matched_ids = [m["id"] for m in matches]

        # English job was delivered 5 days ago, so it should be excluded
        self.assertNotIn(str(self.job_english.id), matched_ids)
        # Staff job was NOT delivered, so it is still matched
        self.assertIn(str(self.staff_job_english.id), matched_ids)

    def test_deduplication_window_allows_vacancy_older_than_window(self):
        """Verify delivery older than 14 days allows vacancy to be matched again."""
        campaign = JobAlertCampaign.objects.create(
            name="Old Campaign",
            created_by=self.staff_user,
            subject="Job Alerts",
            body_html="<p>Jobs</p>",
            status=JobAlertCampaign.Status.COMPLETED,
        )
        # Create delivery 20 days ago (outside 14-day window)
        CandidateJobAlertDelivery.record_delivery(
            candidate=self.candidate_user,
            job_id=str(self.job_english.id),
            campaign=campaign,
            sent_at=timezone.now() - timedelta(days=20),
        )

        matches = CandidateJobAlertMatchingService.get_matching_jobs_for_candidate(
            self.candidate_user,
            dedup_window_days=14,
        )
        matched_ids = [m["id"] for m in matches]
        self.assertIn(str(self.job_english.id), matched_ids)

    def test_job_alerts_disabled_candidate_marked_ineligible(self):
        """Verify candidate with job_alerts_enabled=False is marked ineligible."""
        self.candidate_profile.job_alerts_enabled = False
        self.candidate_profile.save()

        eval_result = CandidateJobAlertMatchingService.evaluate_audience(
            filters={"subject": "English", "alerts_enabled_only": True}
        )
        cand_review = [c for c in eval_result["candidates_review"] if c["candidate_id"] == str(self.candidate_user.id)]
        self.assertTrue(len(cand_review) > 0)
        self.assertFalse(cand_review[0]["is_eligible"])
        self.assertIn("opted out", cand_review[0]["exclusion_reason"].lower())
