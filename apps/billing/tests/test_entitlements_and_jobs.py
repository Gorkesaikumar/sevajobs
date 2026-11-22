"""
Tests for BillingEntitlementService job posting limits, renewals, and reposting.
"""

from datetime import timedelta
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.billing.models import SubscriptionPlan, RecruiterSubscription
from apps.billing.services import BillingEntitlementService
from apps.jobs.models import Job, JobCategory
from apps.recruiters.models import Company, RecruiterProfile


class JobEntitlementsTestCase(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Delhi Public Academy", slug="delhi-public-academy")
        self.recruiter_user = User.objects.create_user(
            email="recruiter@dpa.edu",
            phone="9876543210",
            role=User.Role.RECRUITER,
            first_name="Principal",
            last_name="Sharma",
        )
        self.profile = RecruiterProfile.objects.create(
            user=self.recruiter_user,
            company=self.company,
            designation="Principal",
        )
        self.category = JobCategory.objects.create(name="Teaching", slug="teaching")

    def test_auto_provisions_free_subscription(self):
        sub = BillingEntitlementService.get_company_subscription(self.company)
        self.assertIsNotNone(sub)
        self.assertEqual(sub.plan.code, "free")
        self.assertEqual(sub.status, RecruiterSubscription.Status.ACTIVE)

    def test_free_plan_enforces_two_active_jobs_limit(self):
        # 0 active jobs -> allowed
        can_post, msg = BillingEntitlementService.can_post_job(self.company)
        self.assertTrue(can_post)

        # Create Job 1 (Active)
        job1 = Job.objects.create(
            company=self.company,
            recruiter=self.profile,
            category=self.category,
            title="PGT Mathematics",
            slug="pgt-mathematics",
            description="Math teacher needed",
            location="New Delhi",
            status=Job.Status.ACTIVE,
        )
        BillingEntitlementService.consume_job_post_credit(self.company, job1)

        # 1 active job -> still allowed
        can_post, msg = BillingEntitlementService.can_post_job(self.company)
        self.assertTrue(can_post)

        # Create Job 2 (Active)
        job2 = Job.objects.create(
            company=self.company,
            recruiter=self.profile,
            category=self.category,
            title="TGT English",
            slug="tgt-english",
            description="English teacher needed",
            location="New Delhi",
            status=Job.Status.ACTIVE,
        )
        BillingEntitlementService.consume_job_post_credit(self.company, job2)

        # 2 active jobs -> BLOCKED on Free plan!
        can_post, msg = BillingEntitlementService.can_post_job(self.company)
        self.assertFalse(can_post)
        self.assertIn("Free Plan limit reached", msg)

        # Close Job 1
        job1.status = Job.Status.CLOSED
        job1.save(update_fields=["status"])

        # Now only 1 active job -> allowed again!
        can_post, msg = BillingEntitlementService.can_post_job(self.company)
        self.assertTrue(can_post)

    def test_renew_free_job_action(self):
        # Create an expired job
        expired_job = Job.objects.create(
            company=self.company,
            recruiter=self.profile,
            category=self.category,
            title="PRT Science",
            slug="prt-science",
            description="Science teacher",
            location="New Delhi",
            status=Job.Status.EXPIRED,
            deadline=(timezone.now() - timedelta(days=1)).date(),
        )

        # With 0 active jobs, can renew free
        can_renew, _ = BillingEntitlementService.can_renew_free_job(self.company, expired_job)
        self.assertTrue(can_renew)

        success = BillingEntitlementService.renew_free_job(self.company, expired_job)
        self.assertTrue(success)
        expired_job.refresh_from_db()
        self.assertEqual(expired_job.status, Job.Status.ACTIVE)
        self.assertGreater(expired_job.deadline, timezone.now().date())

    def test_repost_credit_consumption(self):
        premium_plan = SubscriptionPlan.objects.get(code="premium_50")
        sub = RecruiterSubscription.objects.create(
            company=self.company,
            plan=premium_plan,
            status=RecruiterSubscription.Status.ACTIVE,
            starts_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=180),
            remaining_job_posts=50,
            remaining_repost_credits=5,
        )

        job = Job.objects.create(
            company=self.company,
            recruiter=self.profile,
            category=self.category,
            title="Vice Principal",
            slug="vice-principal",
            description="Leadership role",
            location="New Delhi",
            status=Job.Status.ACTIVE,
        )

        can_repost, _ = BillingEntitlementService.can_repost_job(self.company, job)
        self.assertTrue(can_repost)

        success = BillingEntitlementService.consume_repost_credit(self.company, job)
        self.assertTrue(success)
        sub.refresh_from_db()
        self.assertEqual(sub.remaining_repost_credits, 4)
