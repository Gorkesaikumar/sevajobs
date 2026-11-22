"""
Billing, Subscriptions, Payments & Recruiter Entitlements Models.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, ROUND_HALF_UP
from django.conf import settings
from django.db import models
from django.utils import timezone
from apps.core.models import BaseModel


# ===========================================================================
# 1. SubscriptionPlan
# ===========================================================================
class SubscriptionPlan(BaseModel):
    """
    Configurable subscription packages and add-ons.
    All commercial pricing and feature limits are defined here and configured
    via Django admin.
    """

    class Category(models.TextChoices):
        JOB_POSTING = "job_posting", "Job Posting"
        WALKIN = "walkin", "Walk-in Recruitment"
        DATABASE_ACCESS = "database_access", "Database Access"
        ADDON = "addon", "Add-on / Top-up"

    code = models.CharField(max_length=50, unique=True, db_index=True, help_text="Unique stable code e.g. 'free', 'premium_50'")
    name = models.CharField(max_length=150)
    category = models.CharField(max_length=30, choices=Category.choices, default=Category.JOB_POSTING, db_index=True)
    description = models.TextField(blank=True)
    price_inr = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), help_text="Base price in INR exclusive of GST")
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("18.00"), help_text="Applicable GST percentage")
    validity_days = models.PositiveIntegerField(default=30, help_text="Validity duration in days")

    # Feature allowances & limits
    job_post_limit = models.PositiveIntegerField(default=0, help_text="Total job posts included")
    featured_days = models.PositiveIntegerField(default=0, help_text="Number of days featured on homepage/top")
    job_active_days = models.PositiveIntegerField(default=30, help_text="Job listing active duration before expiration")
    repost_credits = models.PositiveIntegerField(default=0, help_text="Number of free reposts to top")
    resume_unlock_credits = models.PositiveIntegerField(default=0, help_text="Number of candidate CV unlocks included")
    bulk_email_credits = models.PositiveIntegerField(default=0, help_text="Number of bulk email credits included")
    walkin_events_included = models.PositiveIntegerField(default=0, help_text="Number of guaranteed walkin events")
    walkin_min_attendees = models.PositiveIntegerField(default=10, help_text="Minimum guaranteed attendees per walkin event")

    is_active = models.BooleanField(default=True, db_index=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta(BaseModel.Meta):
        verbose_name = "Subscription Plan"
        verbose_name_plural = "Subscription Plans"
        ordering = ["display_order", "price_inr"]

    def __str__(self) -> str:
        return f"{self.name} (₹{self.price_inr})"

    def calculate_gst(self) -> Decimal:
        rate = (self.gst_rate / Decimal("100.0"))
        return (self.price_inr * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def calculate_total_amount(self) -> Decimal:
        return (self.price_inr + self.calculate_gst()).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def gst_amount(self) -> Decimal:
        return self.calculate_gst()

    @property
    def total_amount(self) -> Decimal:
        return self.calculate_total_amount()


# ===========================================================================
# 2. RecruiterSubscription
# ===========================================================================
class RecruiterSubscription(BaseModel):
    """
    Active or historical subscription held by a Company.
    All quotas and entitlements are tied to Company rather than individual users.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending Payment"
        ACTIVE = "active", "Active"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"
        UPGRADED = "upgraded", "Upgraded"

    company = models.ForeignKey(
        "recruiters.Company",
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name="recruiter_subscriptions",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    starts_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    # Remaining balances (decremented atomically upon usage)
    remaining_job_posts = models.PositiveIntegerField(default=0)
    remaining_repost_credits = models.PositiveIntegerField(default=0)
    remaining_resume_credits = models.PositiveIntegerField(default=0)
    remaining_email_credits = models.PositiveIntegerField(default=0)
    remaining_walkin_events = models.PositiveIntegerField(default=0)

    class Meta(BaseModel.Meta):
        verbose_name = "Recruiter Subscription"
        verbose_name_plural = "Recruiter Subscriptions"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["status", "expires_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.company.name} - {self.plan.name} ({self.status})"

    @property
    def is_currently_active(self) -> bool:
        if self.status != self.Status.ACTIVE:
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        return True

    @property
    def days_remaining(self) -> int:
        if not self.expires_at:
            return 9999
        diff = (self.expires_at - timezone.now()).days
        return max(0, diff)


# ===========================================================================
# 3. ResumeUnlock
# ===========================================================================
class ResumeUnlock(BaseModel):
    """
    Record of a candidate profile / CV unlocked by a Company.
    One credit = Permanent unlock for THAT company (plan unlock), or 30 days
    validity for Quick Unlock packs.
    """

    class SourceType(models.TextChoices):
        PLAN = "plan", "Subscription Plan Credit"
        QUICK_PACK = "quick_pack", "Quick Unlock Pack"
        COMPENSATION = "compensation", "Shortfall Compensation"
        ADMIN = "admin", "Admin Override"

    company = models.ForeignKey(
        "recruiters.Company",
        on_delete=models.CASCADE,
        related_name="resume_unlocks",
    )
    unlocked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="unlocked_resumes",
    )
    candidate_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="unlocked_by_companies",
    )
    unlocked_at = models.DateTimeField(default=timezone.now, db_index=True)
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Null for permanent unlock. Set for temporary unlocks (e.g. 30-day Quick Unlock packs).",
    )
    source_type = models.CharField(
        max_length=20,
        choices=SourceType.choices,
        default=SourceType.PLAN,
    )
    is_contacted = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Recruiter tag: whether candidate was contacted after unlock",
    )
    contacted_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Resume Unlock"
        verbose_name_plural = "Resume Unlocks"
        ordering = ["-unlocked_at"]
        indexes = [
            models.Index(fields=["company", "candidate_user"]),
            models.Index(fields=["company", "is_contacted"]),
        ]

    def __str__(self) -> str:
        return f"{self.company.name} -> {self.candidate_user.email} ({self.source_type})"

    @property
    def is_valid(self) -> bool:
        if self.expires_at is None:
            return True
        return self.expires_at > timezone.now()


# ===========================================================================
# 4. WalkInPackageBooking & WalkInEvent
# ===========================================================================
class WalkInPackageBooking(BaseModel):
    """
    Booking for Walk-in Recruitment at School (Annual package).
    Includes scheduled events and minimum attendee guarantee.
    """

    company = models.ForeignKey(
        "recruiters.Company",
        on_delete=models.CASCADE,
        related_name="walkin_package_bookings",
    )
    subscription = models.ForeignKey(
        RecruiterSubscription,
        on_delete=models.CASCADE,
        related_name="walkin_bookings",
    )
    total_events = models.PositiveSmallIntegerField(default=2)
    completed_events = models.PositiveSmallIntegerField(default=0)
    min_attendees_per_event = models.PositiveSmallIntegerField(default=10)
    is_active = models.BooleanField(default=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Walk-in Package Booking"
        verbose_name_plural = "Walk-in Package Bookings"

    def __str__(self) -> str:
        return f"Walk-in Package for {self.company.name} ({self.completed_events}/{self.total_events})"


class WalkInEvent(BaseModel):
    """
    Individual walk-in recruitment event tracking and shortfall compensation.
    If actual attendees < min guaranteed attendees, shortfall compensation is issued:
    1 compensatory online promotion (worth ₹5,000) + 10 resume unlock credits.
    """

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    booking = models.ForeignKey(
        WalkInPackageBooking,
        on_delete=models.CASCADE,
        related_name="events",
    )
    company = models.ForeignKey(
        "recruiters.Company",
        on_delete=models.CASCADE,
        related_name="walkin_events",
    )
    event_number = models.PositiveSmallIntegerField(default=1)
    event_date = models.DateField(null=True, blank=True)
    venue_name = models.CharField(max_length=255, blank=True)
    venue_address = models.TextField(blank=True)
    contact_person = models.CharField(max_length=150, blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)

    actual_attendees = models.PositiveIntegerField(null=True, blank=True)
    attendance_recorded_at = models.DateTimeField(null=True, blank=True)
    attendance_recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_walkin_events",
    )

    shortfall_compensated = models.BooleanField(default=False)
    compensation_granted_at = models.DateTimeField(null=True, blank=True)
    compensation_notes = models.TextField(blank=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Walk-in Event"
        verbose_name_plural = "Walk-in Events"
        ordering = ["-event_date"]

    def __str__(self) -> str:
        return f"Event #{self.event_number} - {self.company.name} ({self.status})"


# ===========================================================================
# 5. EmailTemplate & RecruiterCampaign
# ===========================================================================
class EmailTemplate(BaseModel):
    """
    Recruiter email template builder (Interview Invite, Rejection, Custom).
    """

    class TemplateType(models.TextChoices):
        INTERVIEW_INVITE = "interview_invite", "Interview Invite"
        REJECTION = "rejection", "Candidate Rejection"
        OFFER = "offer", "Job Offer"
        CUSTOM = "custom", "Custom Template"

    company = models.ForeignKey(
        "recruiters.Company",
        on_delete=models.CASCADE,
        related_name="billing_email_templates",
        null=True,
        blank=True,
        help_text="Null for system default templates",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    template_type = models.CharField(
        max_length=30,
        choices=TemplateType.choices,
        default=TemplateType.CUSTOM,
        db_index=True,
    )
    name = models.CharField(max_length=150)
    subject = models.CharField(max_length=255)
    body_html = models.TextField()
    is_default = models.BooleanField(default=False)

    class Meta(BaseModel.Meta):
        verbose_name = "Email Template"
        verbose_name_plural = "Email Templates"

    def __str__(self) -> str:
        return f"{self.name} ({self.get_template_type_display()})"


class RecruiterCampaign(BaseModel):
    """
    Recruiter bulk email campaign.
    Requires mandatory Admin Approval before dispatch.
    Sending limit: 200 emails / day / company.
    Strictly restricted to internal SevaJobs candidates.
    """

    class ApprovalStatus(models.TextChoices):
        PENDING_APPROVAL = "pending_approval", "Pending Approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING_APPROVAL = "pending_approval", "Pending Approval"
        APPROVED = "approved", "Approved"
        QUEUED = "queued", "Queued"
        SENDING = "sending", "Sending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    company = models.ForeignKey(
        "recruiters.Company",
        on_delete=models.CASCADE,
        related_name="billing_campaigns",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="billing_campaigns",
    )
    name = models.CharField(max_length=255)
    template = models.ForeignKey(
        EmailTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    subject = models.CharField(max_length=255)
    body_html = models.TextField()

    approval_status = models.CharField(
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING_APPROVAL,
        db_index=True,
    )
    rejection_reason = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_billing_campaigns",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING_APPROVAL,
        db_index=True,
    )

    recipient_count = models.PositiveIntegerField(default=0)
    sent_count = models.PositiveIntegerField(default=0)
    delivered_count = models.PositiveIntegerField(default=0)
    opened_count = models.PositiveIntegerField(default=0)
    clicked_count = models.PositiveIntegerField(default=0)

    class Meta(BaseModel.Meta):
        verbose_name = "Recruiter Bulk Email Campaign"
        verbose_name_plural = "Recruiter Bulk Email Campaigns"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} - {self.company.name} ({self.approval_status})"


class RecruiterCampaignRecipient(BaseModel):
    """
    Individual recipient tracking record for recruiter campaigns.
    Generates unique tracking token for open rate and click rate attribution.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        OPENED = "opened", "Opened"
        CLICKED = "clicked", "Clicked"

    campaign = models.ForeignKey(
        RecruiterCampaign,
        on_delete=models.CASCADE,
        related_name="recipients",
    )
    candidate_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="recruiter_campaign_receipts",
    )
    email = models.EmailField(db_index=True)
    tracking_token = models.CharField(max_length=64, unique=True, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    sent_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    clicked_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Campaign Recipient"
        verbose_name_plural = "Campaign Recipients"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.email} ({self.campaign.name})"


# ===========================================================================
# 6. PaymentOrder & PaymentWebhookEvent
# ===========================================================================
class PaymentOrder(BaseModel):
    """
    Cashfree payment orders for subscription packages and add-ons.
    Maintains server-side pricing integrity, GST separation, and idempotency.
    """

    class ItemType(models.TextChoices):
        PLAN = "plan", "Subscription Plan"
        QUICK_UNLOCK = "quick_unlock", "Quick Unlock Add-on"

    class Status(models.TextChoices):
        CREATED = "created", "Created"
        PAID = "paid", "Paid / Success"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    order_id = models.CharField(max_length=64, unique=True, db_index=True, help_text="Internal unique order reference")
    cf_order_id = models.CharField(max_length=128, blank=True, db_index=True, help_text="Cashfree gateway order id")
    payment_session_id = models.CharField(max_length=255, blank=True, help_text="Cashfree checkout session ID")

    company = models.ForeignKey(
        "recruiters.Company",
        on_delete=models.CASCADE,
        related_name="payment_orders",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payment_orders",
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    item_code = models.CharField(max_length=50)
    item_type = models.CharField(max_length=20, choices=ItemType.choices, default=ItemType.PLAN)

    base_amount = models.DecimalField(max_digits=10, decimal_places=2)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("18.00"))
    gst_amount = models.DecimalField(max_digits=10, decimal_places=2)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default="INR")

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CREATED,
        db_index=True,
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    cf_payment_id = models.CharField(max_length=128, blank=True)
    payment_method = models.CharField(max_length=50, blank=True)
    raw_response = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Payment Order"
        verbose_name_plural = "Payment Orders"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.order_id} - {self.company.name} - ₹{self.total_amount} ({self.status})"


class PaymentWebhookEvent(BaseModel):
    """
    Audit log of raw incoming webhook notifications from Cashfree.
    Guarantees idempotency and protects against replay attacks.
    """

    event_id = models.CharField(max_length=128, unique=True, db_index=True)
    event_type = models.CharField(max_length=100)
    order_id = models.CharField(max_length=64, blank=True, db_index=True)
    signature_valid = models.BooleanField(default=False)
    raw_payload = models.JSONField(default=dict)
    processed = models.BooleanField(default=False, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Payment Webhook Event"
        verbose_name_plural = "Payment Webhook Events"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.event_type} - {self.event_id} (Processed: {self.processed})"
