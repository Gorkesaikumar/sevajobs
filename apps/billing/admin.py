"""
Django admin configuration for billing models.
"""

from django.contrib import admin
from .models import (
    SubscriptionPlan,
    RecruiterSubscription,
    ResumeUnlock,
    WalkInPackageBooking,
    WalkInEvent,
    EmailTemplate,
    RecruiterCampaign,
    RecruiterCampaignRecipient,
    PaymentOrder,
    PaymentWebhookEvent,
)


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = [
        "code", "name", "category", "price_inr", "gst_rate",
        "validity_days", "job_post_limit", "resume_unlock_credits",
        "bulk_email_credits", "is_active", "display_order",
    ]
    list_filter = ["category", "is_active"]
    search_fields = ["code", "name", "description"]
    ordering = ["display_order", "price_inr"]


@admin.register(RecruiterSubscription)
class RecruiterSubscriptionAdmin(admin.ModelAdmin):
    list_display = [
        "company", "plan", "status", "starts_at", "expires_at",
        "remaining_job_posts", "remaining_resume_credits",
        "remaining_email_credits", "remaining_repost_credits",
    ]
    list_filter = ["status", "plan"]
    search_fields = ["company__name", "plan__name", "plan__code"]
    raw_id_fields = ["company"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(ResumeUnlock)
class ResumeUnlockAdmin(admin.ModelAdmin):
    list_display = [
        "company", "candidate_user", "unlocked_by", "unlocked_at",
        "expires_at", "source_type", "is_contacted", "contacted_at",
    ]
    list_filter = ["source_type", "is_contacted"]
    search_fields = ["company__name", "candidate_user__email", "candidate_user__phone"]
    raw_id_fields = ["company", "unlocked_by", "candidate_user"]
    readonly_fields = ["unlocked_at", "created_at", "updated_at"]


class WalkInEventInline(admin.TabularInline):
    model = WalkInEvent
    extra = 0
    fields = [
        "event_number", "event_date", "venue_name", "status",
        "actual_attendees", "shortfall_compensated",
    ]
    readonly_fields = ["shortfall_compensated"]


@admin.register(WalkInPackageBooking)
class WalkInPackageBookingAdmin(admin.ModelAdmin):
    list_display = [
        "company", "subscription", "total_events",
        "completed_events", "min_attendees_per_event", "is_active",
    ]
    list_filter = ["is_active"]
    search_fields = ["company__name"]
    raw_id_fields = ["company", "subscription"]
    inlines = [WalkInEventInline]


@admin.register(WalkInEvent)
class WalkInEventAdmin(admin.ModelAdmin):
    list_display = [
        "booking", "company", "event_number", "event_date",
        "status", "actual_attendees", "shortfall_compensated",
    ]
    list_filter = ["status", "shortfall_compensated"]
    search_fields = ["company__name", "venue_name"]
    raw_id_fields = ["booking", "company", "attendance_recorded_by"]


@admin.register(EmailTemplate)
class EmailTemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "template_type", "company", "is_default", "created_at"]
    list_filter = ["template_type", "is_default"]
    search_fields = ["name", "subject", "company__name"]
    raw_id_fields = ["company", "created_by"]


class RecruiterCampaignRecipientInline(admin.TabularInline):
    model = RecruiterCampaignRecipient
    extra = 0
    fields = ["email", "status", "sent_at", "opened_at", "clicked_at"]
    readonly_fields = ["email", "status", "sent_at", "opened_at", "clicked_at"]
    can_delete = False


@admin.register(RecruiterCampaign)
class RecruiterCampaignAdmin(admin.ModelAdmin):
    list_display = [
        "name", "company", "approval_status", "status",
        "recipient_count", "sent_count", "opened_count", "clicked_count",
        "created_at",
    ]
    list_filter = ["approval_status", "status"]
    search_fields = ["name", "subject", "company__name"]
    raw_id_fields = ["company", "created_by", "template", "reviewed_by"]
    inlines = [RecruiterCampaignRecipientInline]


@admin.register(PaymentOrder)
class PaymentOrderAdmin(admin.ModelAdmin):
    list_display = [
        "order_id", "company", "item_code", "base_amount", "gst_amount",
        "total_amount", "status", "paid_at", "created_at",
    ]
    list_filter = ["status", "item_type"]
    search_fields = ["order_id", "cf_order_id", "company__name", "user__email"]
    raw_id_fields = ["company", "user", "plan"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(PaymentWebhookEvent)
class PaymentWebhookEventAdmin(admin.ModelAdmin):
    list_display = ["event_id", "event_type", "order_id", "signature_valid", "processed", "created_at"]
    list_filter = ["signature_valid", "processed", "event_type"]
    search_fields = ["event_id", "order_id"]
    readonly_fields = ["created_at", "updated_at"]
