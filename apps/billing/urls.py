"""
URL routing for Billing, Payments, Webhooks, Tracking & Entitlements.
"""

from django.urls import path
from . import views
from . import campaign_views

app_name = "billing"

urlpatterns = [
    # Pricing & Subscription management
    path("pricing/", views.PricingPageView.as_view(), name="pricing"),
    path("dashboard/", views.RecruiterBillingDashboardView.as_view(), name="dashboard"),

    # Recruiter Bulk Email Campaigns (Admin approval gated, 200/day limit)
    path("campaigns/", campaign_views.RecruiterCampaignListView.as_view(), name="campaign-list"),
    path("campaigns/create/", campaign_views.RecruiterCampaignCreateView.as_view(), name="campaign-create"),
    path("campaigns/<uuid:pk>/", campaign_views.RecruiterCampaignDetailView.as_view(), name="campaign-detail"),

    # Cashfree PG checkout flow & callbacks
    path("create-order/", views.CreatePaymentOrderView.as_view(), name="create-order"),
    path("verify/", views.PaymentVerifyView.as_view(), name="verify"),
    path("webhook/", views.CashfreeWebhookView.as_view(), name="webhook"),

    # Email Campaign Open & Click Attribution Tracking
    path("track/open/<str:tracking_token>/", views.EmailTrackingPixelView.as_view(), name="track-open"),
    path("track/click/<str:tracking_token>/", views.EmailTrackingClickView.as_view(), name="track-click"),

    # REST APIs for Candidate Resume Unlocking & Recruiter Tagging
    path("api/resumes/<uuid:candidate_user_id>/unlock/", views.ResumeUnlockAPIView.as_view(), name="api-resume-unlock"),
    path("api/resumes/<uuid:candidate_user_id>/toggle-contacted/", views.ToggleContactedTagAPIView.as_view(), name="api-toggle-contacted"),
]
