"""
Tests for Walk-in shortfall compensation, bulk email quotas, and campaign workflows.
"""

from datetime import timedelta
from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.billing.campaign_service import RecruiterCampaignService
from apps.billing.models import (
    SubscriptionPlan,
    RecruiterSubscription,
    WalkInPackageBooking,
    WalkInEvent,
    RecruiterCampaign,
    RecruiterCampaignRecipient,
)
from apps.billing.services import BillingEntitlementService
from apps.recruiters.models import Company, RecruiterProfile


class WalkInAndCampaignTestCase(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Greenwood High", slug="greenwood-high")
        self.recruiter_user = User.objects.create_user(
            email="hr@greenwood.edu", phone="9911223344", role=User.Role.RECRUITER, first_name="HR", last_name="Greenwood"
        )
        self.profile = RecruiterProfile.objects.create(user=self.recruiter_user, company=self.company)

        self.admin_user = User.objects.create_user(
            email="admin@sevajobs.in", phone="9900000000", role=User.Role.ADMIN, first_name="Admin", last_name="Seva", is_staff=True, is_superuser=True
        )

        # Walk-in subscription
        walkin_plan = SubscriptionPlan.objects.get(code="walkin_school")
        self.sub = RecruiterSubscription.objects.create(
            company=self.company,
            plan=walkin_plan,
            status=RecruiterSubscription.Status.ACTIVE,
            starts_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=365),
            remaining_resume_credits=20,
            remaining_email_credits=500,
            remaining_walkin_events=2,
        )

        self.booking = WalkInPackageBooking.objects.create(
            company=self.company,
            subscription=self.sub,
            total_events=2,
            min_attendees_per_event=10,
        )

        self.event1 = WalkInEvent.objects.create(
            booking=self.booking,
            company=self.company,
            event_number=1,
            venue_name="Greenwood Campus",
            status=WalkInEvent.Status.SCHEDULED,
        )

    def test_walkin_shortfall_compensation(self):
        # Actual attendance was only 6 (< 10)
        self.event1.actual_attendees = 6
        self.event1.status = WalkInEvent.Status.COMPLETED
        self.event1.save()

        # Initial resume credits = 20
        self.assertEqual(self.sub.remaining_resume_credits, 20)

        # Trigger compensation
        success, msg = BillingEntitlementService.compensate_walkin_shortfall(self.event1, self.admin_user)
        self.assertTrue(success)

        self.sub.refresh_from_db()
        # +10 resume unlock credits granted
        self.assertEqual(self.sub.remaining_resume_credits, 30)

        self.event1.refresh_from_db()
        self.assertTrue(self.event1.shortfall_compensated)
        self.assertIn("1 compensatory online promotion", self.event1.compensation_notes)

        # Second attempt should be rejected (prevent duplicate compensation)
        success2, msg2 = BillingEntitlementService.compensate_walkin_shortfall(self.event1, self.admin_user)
        self.assertFalse(success2)
        self.assertIn("already been issued", msg2)

    def test_bulk_email_campaign_daily_limit(self):
        # Daily limit is 200 emails / day
        can_send_200, _ = BillingEntitlementService.can_send_bulk_email(self.company, 200)
        self.assertTrue(can_send_200)

        # 201 exceeds limit
        can_send_201, msg = BillingEntitlementService.can_send_bulk_email(self.company, 201)
        self.assertFalse(can_send_201)
        self.assertIn("Daily sending limit reached", msg)

    def test_campaign_admin_approval_workflow(self):
        # Create 5 candidates
        candidate_ids = []
        for i in range(5):
            u = User.objects.create_user(
                email=f"candidate_{i}@example.com", phone=f"900000000{i}", role=User.Role.JOB_SEEKER
            )
            candidate_ids.append(u.id)

        campaign = RecruiterCampaignService.create_campaign(
            company=self.company,
            created_by=self.recruiter_user,
            name="Science Teacher Walkin Invitation",
            subject="Interview at Greenwood High for {{candidate_name}}",
            body_html="<p>Dear {{candidate_name}}, please attend interview.</p>",
            candidate_ids=candidate_ids,
        )

        self.assertEqual(campaign.approval_status, RecruiterCampaign.ApprovalStatus.PENDING_APPROVAL)
        self.assertEqual(campaign.recipient_count, 5)

        # Credits deducted
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.remaining_email_credits, 495)

        # Admin approves campaign
        ok = RecruiterCampaignService.approve_campaign(campaign, self.admin_user)
        self.assertTrue(ok)
        campaign.refresh_from_db()
        self.assertEqual(campaign.approval_status, RecruiterCampaign.ApprovalStatus.APPROVED)
        self.assertEqual(campaign.status, RecruiterCampaign.Status.COMPLETED)
        self.assertEqual(campaign.sent_count, 5)

        # Check recipient tracking token and pixel/click tracking
        recipient = campaign.recipients.first()
        self.assertIsNotNone(recipient.tracking_token)
        self.assertEqual(recipient.status, RecruiterCampaignRecipient.Status.SENT)

        # Test tracking pixel hit
        client = Client()
        resp = client.get(f"/billing/track/open/{recipient.tracking_token}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "image/gif")

        recipient.refresh_from_db()
        self.assertEqual(recipient.status, RecruiterCampaignRecipient.Status.OPENED)
        campaign.refresh_from_db()
        self.assertEqual(campaign.opened_count, 1)
