"""
Tests for candidate contact masking, company-scoped resume unlocks, and Contacted tags.
"""

from datetime import timedelta
from decimal import Decimal
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.accounts.models import JobSeekerProfile, User
from apps.billing.models import SubscriptionPlan, RecruiterSubscription, ResumeUnlock
from apps.billing.services import BillingEntitlementService
from apps.recruiters.models import Company, RecruiterProfile
from apps.recruiters.serializers import CandidateSearchSerializer


class ResumeUnlockingTestCase(TestCase):
    def setUp(self):
        self.company_a = Company.objects.create(name="St. Xavier High School", slug="st-xavier-high-school")
        self.company_b = Company.objects.create(name="Modern Public School", slug="modern-public-school")

        self.recruiter_a_user = User.objects.create_user(
            email="hr@stxavier.edu", phone="9811111111", role=User.Role.RECRUITER, first_name="Father", last_name="Joseph"
        )
        self.recruiter_a = RecruiterProfile.objects.create(user=self.recruiter_a_user, company=self.company_a)

        self.candidate_user = User.objects.create_user(
            email="saikumar@gmail.com", phone="9876543210", role=User.Role.JOB_SEEKER, first_name="Sai", last_name="Kumar"
        )
        self.candidate_profile = JobSeekerProfile.objects.create(
            user=self.candidate_user,
            designation="PGT Physics",
            subject="Physics",
            experience_years=5,
            current_location="Hyderabad",
            is_open_to_work=True,
        )

        # Grant resume unlock credits to Company A
        db_plan = SubscriptionPlan.objects.get(code="db_access_pro")
        self.sub_a = RecruiterSubscription.objects.create(
            company=self.company_a,
            plan=db_plan,
            status=RecruiterSubscription.Status.ACTIVE,
            starts_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=365),
            remaining_resume_credits=10,
        )

    def test_contact_masking_format(self):
        masked_phone = BillingEntitlementService.mask_phone("9876543210")
        self.assertEqual(masked_phone, "98XXXXX210")

        masked_email = BillingEntitlementService.mask_email("saikumar@gmail.com")
        self.assertEqual(masked_email, "sa***@gmail.com")

        masked_short = BillingEntitlementService.mask_email("ab@domain.com")
        self.assertEqual(masked_short, "ab***@domain.com")

    def test_unlock_deducts_credit_and_is_permanent_for_company(self):
        self.assertFalse(BillingEntitlementService.is_candidate_unlocked(self.company_a, self.candidate_user))

        success, msg, unlock = BillingEntitlementService.unlock_candidate(
            company=self.company_a,
            candidate_user=self.candidate_user,
            unlocked_by=self.recruiter_a_user,
            source_type=ResumeUnlock.SourceType.PLAN,
        )
        self.assertTrue(success)
        self.assertIsNotNone(unlock)
        self.assertIsNone(unlock.expires_at)  # Permanent plan unlock

        self.sub_a.refresh_from_db()
        self.assertEqual(self.sub_a.remaining_resume_credits, 9)

        # Now unlocked for Company A
        self.assertTrue(BillingEntitlementService.is_candidate_unlocked(self.company_a, self.candidate_user))

        # But NOT unlocked for Company B!
        self.assertFalse(BillingEntitlementService.is_candidate_unlocked(self.company_b, self.candidate_user))

    def test_toggle_contacted_tag(self):
        # Must be unlocked first
        BillingEntitlementService.unlock_candidate(
            company=self.company_a,
            candidate_user=self.candidate_user,
            unlocked_by=self.recruiter_a_user,
        )

        # Initially False
        unlock = BillingEntitlementService.get_candidate_unlock_record(self.company_a, self.candidate_user)
        self.assertFalse(unlock.is_contacted)

        # Toggle to True
        ok, is_contacted = BillingEntitlementService.toggle_contacted_tag(self.company_a, self.candidate_user)
        self.assertTrue(ok)
        self.assertTrue(is_contacted)

        # Toggle back to False
        ok, is_contacted = BillingEntitlementService.toggle_contacted_tag(self.company_a, self.candidate_user)
        self.assertTrue(ok)
        self.assertFalse(is_contacted)

    def test_candidate_search_serializer_masking(self):
        factory = RequestFactory()
        req = factory.get("/api/v1/recruiters/candidates/")
        req.user = self.recruiter_a_user

        # Before unlock: masked
        serializer = CandidateSearchSerializer(self.candidate_profile, context={"request": req})
        data = serializer.data
        self.assertFalse(data["is_unlocked"])
        self.assertEqual(data["email"], "sa***@gmail.com")
        self.assertEqual(data["phone"], "98XXXXX210")
        self.assertIsNone(data["primary_resume"])

        # Unlock
        BillingEntitlementService.unlock_candidate(self.company_a, self.candidate_user, self.recruiter_a_user)

        # After unlock: clear details
        delattr(self.candidate_profile, "_cached_unlock")
        serializer_after = CandidateSearchSerializer(self.candidate_profile, context={"request": req})
        data_after = serializer_after.data
        self.assertTrue(data_after["is_unlocked"])
        self.assertEqual(data_after["email"], "saikumar@gmail.com")
        self.assertEqual(data_after["phone"], "9876543210")
