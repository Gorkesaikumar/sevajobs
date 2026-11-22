"""
Billing, Subscription & Entitlements Service Layer.
Enforces business logic, atomic credit deduction, candidate masking,
and idempotency across all recruiter actions.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any, Tuple

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.jobs.models import Job
from apps.recruiters.models import Company
from .models import (
    SubscriptionPlan,
    RecruiterSubscription,
    ResumeUnlock,
    WalkInPackageBooking,
    WalkInEvent,
    PaymentOrder,
)

logger = logging.getLogger("apps.billing")


class BillingEntitlementService:
    """
    Central entitlement and billing management service.
    """

    DAILY_EMAIL_LIMIT_PER_COMPANY = 200
    FREE_ACTIVE_JOB_LIMIT = 2

    @classmethod
    def get_company_subscription(cls, company: Company) -> RecruiterSubscription:
        """
        Returns the active subscription for a company.
        If no active subscription exists, returns or initializes the default Free plan.
        """
        now = timezone.now()
        active_sub = (
            RecruiterSubscription.objects.filter(
                company=company,
                status=RecruiterSubscription.Status.ACTIVE,
            )
            .filter(models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now))
            .select_related("plan")
            .order_by("-created_at")
            .first()
        )
        if active_sub:
            return active_sub

        # Auto-provision Free Plan
        free_plan, _ = SubscriptionPlan.objects.get_or_create(
            code="free",
            defaults={
                "name": "Free Job Posting",
                "category": SubscriptionPlan.Category.JOB_POSTING,
                "price_inr": Decimal("0.00"),
                "gst_rate": Decimal("18.00"),
                "validity_days": 3650,  # 10 years for baseline free access
                "job_post_limit": cls.FREE_ACTIVE_JOB_LIMIT,
                "featured_days": 0,
                "job_active_days": 30,
                "repost_credits": 0,
                "resume_unlock_credits": 0,
                "bulk_email_credits": 0,
                "walkin_events_included": 0,
                "is_active": True,
            },
        )
        sub, _ = RecruiterSubscription.objects.get_or_create(
            company=company,
            plan=free_plan,
            status=RecruiterSubscription.Status.ACTIVE,
            defaults={
                "starts_at": now,
                "expires_at": now + timedelta(days=free_plan.validity_days),
                "remaining_job_posts": free_plan.job_post_limit,
                "remaining_repost_credits": 0,
                "remaining_resume_credits": 0,
                "remaining_email_credits": 0,
                "remaining_walkin_events": 0,
            },
        )
        return sub

    @classmethod
    def get_active_job_count(cls, company: Company) -> int:
        """Counts currently active (published/approved) jobs for a company."""
        return Job.objects.filter(
            company=company,
            status=Job.Status.ACTIVE,
        ).count()

    @classmethod
    def can_post_job(cls, company: Company) -> Tuple[bool, str]:
        """
        Checks whether the company is entitled to create/publish a new job.
        Rule: Free plan allows max 2 active jobs. Premium plans deduct from remaining balance.
        """
        sub = cls.get_company_subscription(company)
        if sub.plan.code == "free":
            active_count = cls.get_active_job_count(company)
            if active_count >= cls.FREE_ACTIVE_JOB_LIMIT:
                return (
                    False,
                    f"Free Plan limit reached ({active_count}/{cls.FREE_ACTIVE_JOB_LIMIT} active jobs). "
                    "Close an active job or upgrade to Premium to post more.",
                )
            return True, "Allowed under Free Plan."

        if sub.remaining_job_posts <= 0:
            return (
                False,
                f"No job posting credits remaining in your '{sub.plan.name}' plan. Please renew or upgrade.",
            )

        return True, f"Allowed ({sub.remaining_job_posts} credits remaining)."

    @classmethod
    def consume_job_post_credit(cls, company: Company, job: Job) -> bool:
        """
        Consumes 1 job post credit atomically and configures featured & active durations.
        """
        with transaction.atomic():
            sub = (
                RecruiterSubscription.objects.select_for_update()
                .filter(company=company, status=RecruiterSubscription.Status.ACTIVE)
                .order_by("-created_at")
                .first()
            )
            if not sub:
                sub = cls.get_company_subscription(company)

            plan = sub.plan
            if plan.code == "free":
                active_count = cls.get_active_job_count(company)
                if active_count >= cls.FREE_ACTIVE_JOB_LIMIT:
                    return False
                job.deadline = (timezone.now() + timedelta(days=plan.job_active_days)).date()
                job.save(update_fields=["deadline"])
                return True

            if sub.remaining_job_posts <= 0:
                return False

            sub.remaining_job_posts -= 1
            sub.save(update_fields=["remaining_job_posts"])

            # Configure premium perks on the job
            if plan.featured_days > 0:
                job.is_featured = True
                job.featured_until = timezone.now() + timedelta(days=plan.featured_days)
            if plan.job_active_days > 0:
                job.deadline = (timezone.now() + timedelta(days=plan.job_active_days)).date()

            job.save(update_fields=["is_featured", "featured_until", "deadline"])
            logger.info("Consumed 1 job post credit for company %s on job %s.", company.name, job.pk)
            return True

    @classmethod
    def can_renew_free_job(cls, company: Company, job: Job) -> Tuple[bool, str]:
        """
        Free plan feature: Auto-expire jobs after 30 days, but provide 'Renew Free' action.
        Only allowed if currently active jobs < 2.
        """
        active_count = cls.get_active_job_count(company)
        # If this job is already active, it wouldn't increase active count
        if job.status == Job.Status.ACTIVE:
            return True, "Job is currently active."
        if active_count >= cls.FREE_ACTIVE_JOB_LIMIT:
            return (
                False,
                f"Cannot renew. You already have {active_count} active jobs (Free limit: {cls.FREE_ACTIVE_JOB_LIMIT}). "
                "Close another job first or upgrade.",
            )
        return True, "Eligible for free renewal."

    @classmethod
    def renew_free_job(cls, company: Company, job: Job) -> bool:
        """Renews an expired/closed job for an additional 30 days under the Free plan."""
        can_renew, _ = cls.can_renew_free_job(company, job)
        if not can_renew:
            return False

        job.status = Job.Status.ACTIVE
        job.deadline = (timezone.now() + timedelta(days=30)).date()
        job.published_at = timezone.now()
        job.save(update_fields=["status", "deadline", "published_at"])
        logger.info("Renewed free job %s for company %s.", job.pk, company.name)
        return True

    @classmethod
    def can_repost_job(cls, company: Company, job: Job) -> Tuple[bool, str]:
        """Checks if recruiter can repost a job to the top using 1 repost credit."""
        sub = cls.get_company_subscription(company)
        if sub.remaining_repost_credits <= 0:
            return False, "No repost credits remaining in your subscription."
        return True, f"{sub.remaining_repost_credits} repost credits available."

    @classmethod
    def consume_repost_credit(cls, company: Company, job: Job) -> bool:
        """Deducts 1 repost credit and bumps the job to the top of listings."""
        with transaction.atomic():
            sub = (
                RecruiterSubscription.objects.select_for_update()
                .filter(company=company, status=RecruiterSubscription.Status.ACTIVE)
                .order_by("-created_at")
                .first()
            )
            if not sub or sub.remaining_repost_credits <= 0:
                return False

            sub.remaining_repost_credits -= 1
            sub.save(update_fields=["remaining_repost_credits"])

            job.created_at = timezone.now()
            job.published_at = timezone.now()
            job.save(update_fields=["created_at", "published_at"])
            logger.info("Consumed 1 repost credit for company %s on job %s.", company.name, job.pk)
            return True

    # -----------------------------------------------------------------------
    # Resume Database Access Control & Masking
    # -----------------------------------------------------------------------
    @classmethod
    def is_candidate_unlocked(cls, company: Company | None, candidate_user: User) -> bool:
        """
        Determines whether candidate's contact details and CV are unlocked for this company.
        One credit = Permanent unlock for THAT company (plan unlock), or valid within 30 days (quick pack).
        """
        if not company or not candidate_user:
            return False

        now = timezone.now()
        unlock = (
            ResumeUnlock.objects.filter(
                company=company,
                candidate_user=candidate_user,
            )
            .filter(models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now))
            .first()
        )
        return unlock is not None

    @classmethod
    def get_candidate_unlock_record(cls, company: Company | None, candidate_user: User) -> ResumeUnlock | None:
        if not company or not candidate_user:
            return None
        now = timezone.now()
        return (
            ResumeUnlock.objects.filter(
                company=company,
                candidate_user=candidate_user,
            )
            .filter(models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now))
            .first()
        )

    @classmethod
    def can_unlock_resume(cls, company: Company) -> Tuple[bool, str]:
        sub = cls.get_company_subscription(company)
        if sub.remaining_resume_credits <= 0:
            return (
                False,
                "No resume unlock credits remaining. Purchase the Quick Unlock Add-on (10 unlocks for ₹999) "
                "or Database Access Pro.",
            )
        return True, f"{sub.remaining_resume_credits} credits available."

    @classmethod
    def unlock_candidate(
        cls,
        company: Company,
        candidate_user: User,
        unlocked_by: User | None = None,
        source_type: str = ResumeUnlock.SourceType.PLAN,
    ) -> Tuple[bool, str, ResumeUnlock | None]:
        """
        Consumes 1 resume credit and permanently unlocks candidate profile for this company.
        (Or 30-day validity if source_type == QUICK_PACK).
        """
        if cls.is_candidate_unlocked(company, candidate_user):
            existing = cls.get_candidate_unlock_record(company, candidate_user)
            return True, "Candidate is already unlocked for your company.", existing

        with transaction.atomic():
            sub = (
                RecruiterSubscription.objects.select_for_update()
                .filter(company=company, status=RecruiterSubscription.Status.ACTIVE)
                .order_by("-created_at")
                .first()
            )
            if not sub:
                sub = cls.get_company_subscription(company)

            if sub.remaining_resume_credits <= 0:
                return (
                    False,
                    "Insufficient resume credits. Upgrade to Database Access or get Quick Unlock (10 unlocks for ₹999).",
                    None,
                )

            sub.remaining_resume_credits -= 1
            sub.save(update_fields=["remaining_resume_credits"])

            # Set expiration: null for permanent plan unlocks, +30d for quick packs
            expires_at = (
                timezone.now() + timedelta(days=30)
                if source_type == ResumeUnlock.SourceType.QUICK_PACK
                else None
            )

            unlock = ResumeUnlock.objects.create(
                company=company,
                candidate_user=candidate_user,
                unlocked_by=unlocked_by,
                source_type=source_type,
                expires_at=expires_at,
            )
            logger.info(
                "Company %s unlocked candidate %s using %s credit.",
                company.name,
                candidate_user.email,
                source_type,
            )
            return True, "Candidate profile unlocked successfully.", unlock

    @classmethod
    def toggle_contacted_tag(cls, company: Company, candidate_user: User) -> Tuple[bool, bool]:
        """
        Toggles recruiter 'Contacted' tag on an unlocked candidate.
        Returns (success, is_contacted).
        """
        unlock = cls.get_candidate_unlock_record(company, candidate_user)
        if not unlock:
            return False, False

        unlock.is_contacted = not unlock.is_contacted
        unlock.contacted_at = timezone.now() if unlock.is_contacted else None
        unlock.save(update_fields=["is_contacted", "contacted_at"])
        return True, unlock.is_contacted

    @staticmethod
    def mask_phone(phone: str | None) -> str:
        """Masks phone number as 98XXXXX210."""
        digits = "".join(filter(str.isdigit, str(phone or "")))
        if len(digits) < 10:
            return "XXXXXXXXXX"
        return f"{digits[:2]}XXXXX{digits[-3:]}"

    @staticmethod
    def mask_email(email: str | None) -> str:
        """Masks email address as sa***@gmail.com."""
        if not email or "@" not in email:
            return "candid***@sevajobs.in"
        user_part, domain = email.split("@", 1)
        if len(user_part) <= 2:
            masked_user = user_part + "***"
        else:
            masked_user = user_part[:2] + "***"
        return f"{masked_user}@{domain}"

    # -----------------------------------------------------------------------
    # Bulk Email Quota & Validation
    # -----------------------------------------------------------------------
    @classmethod
    def get_today_sent_email_count(cls, company: Company) -> int:
        """Calculates emails dispatched by this company today."""
        from .models import RecruiterCampaignRecipient
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return RecruiterCampaignRecipient.objects.filter(
            campaign__company=company,
            sent_at__gte=today_start,
            status__in=[
                RecruiterCampaignRecipient.Status.SENT,
                RecruiterCampaignRecipient.Status.OPENED,
                RecruiterCampaignRecipient.Status.CLICKED,
            ],
        ).count()

    @classmethod
    def can_send_bulk_email(cls, company: Company, recipient_count: int) -> Tuple[bool, str]:
        """
        Validates email balance and strictly enforces 200 emails / day / company ceiling.
        """
        if recipient_count <= 0:
            return False, "Recipient count must be greater than zero."

        sub = cls.get_company_subscription(company)
        if sub.remaining_email_credits < recipient_count:
            return (
                False,
                f"Insufficient bulk email credits. Need {recipient_count}, but plan has {sub.remaining_email_credits}.",
            )

        today_sent = cls.get_today_sent_email_count(company)
        if today_sent + recipient_count > cls.DAILY_EMAIL_LIMIT_PER_COMPANY:
            remaining_today = max(0, cls.DAILY_EMAIL_LIMIT_PER_COMPANY - today_sent)
            return (
                False,
                f"Daily sending limit reached (max {cls.DAILY_EMAIL_LIMIT_PER_COMPANY} emails/day/company). "
                f"You can send up to {remaining_today} more emails today.",
            )

        return True, "Eligible to dispatch bulk email campaign."

    @classmethod
    def consume_email_credits(cls, company: Company, count: int) -> bool:
        """Deducts email credits atomically."""
        with transaction.atomic():
            sub = (
                RecruiterSubscription.objects.select_for_update()
                .filter(company=company, status=RecruiterSubscription.Status.ACTIVE)
                .order_by("-created_at")
                .first()
            )
            if not sub or sub.remaining_email_credits < count:
                return False

            sub.remaining_email_credits -= count
            sub.save(update_fields=["remaining_email_credits"])
            logger.info("Consumed %d email credits for company %s.", count, company.name)
            return True

    # -----------------------------------------------------------------------
    # Payment Processing & Idempotent Activation
    # -----------------------------------------------------------------------
    @classmethod
    def process_successful_payment(
        cls,
        order_id: str,
        cf_order_id: str = "",
        cf_payment_id: str = "",
        payment_method: str = "",
        raw_response: dict | None = None,
    ) -> Tuple[bool, str]:
        """
        Atomically and idempotently activates package entitlements upon payment success.
        """
        with transaction.atomic():
            order = (
                PaymentOrder.objects.select_for_update()
                .filter(order_id=order_id)
                .select_related("company", "plan", "user")
                .first()
            )
            if not order:
                return False, f"Order '{order_id}' not found."

            if order.status == PaymentOrder.Status.PAID:
                return True, "Order already processed and paid."

            order.status = PaymentOrder.Status.PAID
            order.paid_at = timezone.now()
            if cf_order_id:
                order.cf_order_id = cf_order_id
            if cf_payment_id:
                order.cf_payment_id = cf_payment_id
            if payment_method:
                order.payment_method = payment_method
            if raw_response:
                order.raw_response = raw_response
            order.save()

            company = order.company
            now = timezone.now()

            # Case A: Subscription Plan
            if order.item_type == PaymentOrder.ItemType.PLAN and order.plan:
                plan = order.plan

                # Deactivate older active subscriptions
                RecruiterSubscription.objects.filter(
                    company=company,
                    status=RecruiterSubscription.Status.ACTIVE,
                ).update(status=RecruiterSubscription.Status.UPGRADED)

                expires_at = now + timedelta(days=plan.validity_days)
                new_sub = RecruiterSubscription.objects.create(
                    company=company,
                    plan=plan,
                    status=RecruiterSubscription.Status.ACTIVE,
                    starts_at=now,
                    expires_at=expires_at,
                    remaining_job_posts=plan.job_post_limit,
                    remaining_repost_credits=plan.repost_credits,
                    remaining_resume_credits=plan.resume_unlock_credits,
                    remaining_email_credits=plan.bulk_email_credits,
                    remaining_walkin_events=plan.walkin_events_included,
                )

                # If walk-in events included, provision walk-in package booking
                if plan.walkin_events_included > 0:
                    booking = WalkInPackageBooking.objects.create(
                        company=company,
                        subscription=new_sub,
                        total_events=plan.walkin_events_included,
                        completed_events=0,
                        min_attendees_per_event=plan.walkin_min_attendees,
                    )
                    for ev_num in range(1, plan.walkin_events_included + 1):
                        WalkInEvent.objects.create(
                            booking=booking,
                            company=company,
                            event_number=ev_num,
                            venue_name=company.name,
                            venue_address=company.address or company.location,
                            status=WalkInEvent.Status.SCHEDULED,
                        )

                logger.info(
                    "Activated subscription %s for company %s (Order: %s).",
                    plan.name,
                    company.name,
                    order.order_id,
                )
                return True, f"Subscription '{plan.name}' activated successfully."

            # Case B: Quick Unlock 10 Add-on
            elif order.item_type == PaymentOrder.ItemType.QUICK_UNLOCK:
                sub = (
                    RecruiterSubscription.objects.select_for_update()
                    .filter(company=company, status=RecruiterSubscription.Status.ACTIVE)
                    .order_by("-created_at")
                    .first()
                )
                if not sub:
                    sub = cls.get_company_subscription(company)

                sub.remaining_resume_credits += 10
                sub.save(update_fields=["remaining_resume_credits"])
                logger.info(
                    "Added 10 resume unlock credits to company %s (Order: %s).",
                    company.name,
                    order.order_id,
                )
                return True, "10 Quick Unlock credits added to your account."

            return True, "Payment processed."

    # -----------------------------------------------------------------------
    # Walk-in Event Shortfall Compensation
    # -----------------------------------------------------------------------
    @classmethod
    def compensate_walkin_shortfall(
        cls,
        walkin_event: WalkInEvent,
        admin_user: User | None = None,
    ) -> Tuple[bool, str]:
        """
        If actual attendees < min guaranteed attendees (10), grants:
        - 1 compensatory online promotion worth ₹5,000 (logged & flagged)
        - 10 extra resume unlock credits
        Non-refundable; one compensation per shortfall event.
        """
        if walkin_event.shortfall_compensated:
            return False, "Shortfall compensation has already been issued for this event."

        min_required = walkin_event.booking.min_attendees_per_event
        actual = walkin_event.actual_attendees or 0
        if actual >= min_required:
            return False, f"Attendance commitment met ({actual} >= {min_required}). No shortfall."

        with transaction.atomic():
            company = walkin_event.company
            sub = (
                RecruiterSubscription.objects.select_for_update()
                .filter(company=company, status=RecruiterSubscription.Status.ACTIVE)
                .order_by("-created_at")
                .first()
            )
            if not sub:
                sub = cls.get_company_subscription(company)

            # Grant 10 compensatory resume credits
            sub.remaining_resume_credits += 10
            sub.save(update_fields=["remaining_resume_credits"])

            walkin_event.shortfall_compensated = True
            walkin_event.compensation_granted_at = timezone.now()
            walkin_event.compensation_notes = (
                f"Attendance shortfall: {actual}/{min_required} attended. "
                "Issued 1 compensatory online promotion (worth ₹5,000) and 10 extra resume unlock credits."
            )
            walkin_event.save(
                update_fields=[
                    "shortfall_compensated",
                    "compensation_granted_at",
                    "compensation_notes",
                ]
            )
            logger.info(
                "Shortfall compensation issued for company %s on event #%s.",
                company.name,
                walkin_event.event_number,
            )
            return True, "Compensatory promotion and 10 resume unlocks credited successfully."
