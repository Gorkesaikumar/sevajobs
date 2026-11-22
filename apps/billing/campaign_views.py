"""
Recruiter Campaign & Template Builder Views.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.generic import TemplateView, View

from apps.accounts.models import JobSeekerProfile, User
from apps.applications.models import JobApplication
from apps.jobs.models import Job
from .campaign_service import RecruiterCampaignService
from .models import (
    EmailTemplate,
    RecruiterCampaign,
    RecruiterCampaignRecipient,
)
from .services import BillingEntitlementService
from .views import RecruiterAccessMixin

logger = logging.getLogger("apps.billing")


class RecruiterCampaignListView(RecruiterAccessMixin, TemplateView):
    """
    GET /dashboard/recruiter/campaigns/
    List all campaigns, analytics, open/click rates, and daily quota status.
    """

    template_name = "dashboard/recruiter/campaigns_list.html"
    sidebar_section = "campaigns"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.get_company()
        if not company:
            ctx["company"] = None
            return ctx

        sub = BillingEntitlementService.get_company_subscription(company)
        today_sent = BillingEntitlementService.get_today_sent_email_count(company)
        daily_limit = BillingEntitlementService.DAILY_EMAIL_LIMIT_PER_COMPANY
        campaigns = RecruiterCampaign.objects.filter(company=company).order_by("-created_at")

        # Calculate open and click percentages
        campaign_items = []
        for c in campaigns:
            open_rate = (c.opened_count / c.sent_count * 100) if c.sent_count > 0 else 0
            click_rate = (c.clicked_count / c.sent_count * 100) if c.sent_count > 0 else 0
            campaign_items.append({
                "campaign": c,
                "open_rate": round(open_rate, 1),
                "click_rate": round(click_rate, 1),
            })

        ctx.update({
            "company": company,
            "subscription": sub,
            "campaigns": campaign_items,
            "today_sent": today_sent,
            "daily_limit": daily_limit,
            "remaining_today": max(0, daily_limit - today_sent),
        })
        return ctx


class RecruiterCampaignCreateView(RecruiterAccessMixin, View):
    """
    GET/POST /dashboard/recruiter/campaigns/create/
    Create bulk email campaign targeted strictly at SevaJobs candidates.
    Requires admin approval before dispatch.
    """

    template_name = "dashboard/recruiter/campaign_create.html"
    sidebar_section = "campaigns"

    def get(self, request, *args, **kwargs):
        company = self.get_company()
        if not company:
            return redirect("recruiter:company-profile")

        sub = BillingEntitlementService.get_company_subscription(company)
        today_sent = BillingEntitlementService.get_today_sent_email_count(company)
        daily_limit = BillingEntitlementService.DAILY_EMAIL_LIMIT_PER_COMPANY
        templates = EmailTemplate.objects.filter(Q(company=company) | Q(company__isnull=True)).order_by("template_type")

        # Potential candidate pools: applicants to company's jobs
        applicants = (
            User.objects.filter(
                role=User.Role.JOB_SEEKER,
                applications__job__company=company,
                is_active=True,
            )
            .distinct()
            .select_related("job_seeker_profile")[:200]
        )

        ctx = {
            "company": company,
            "subscription": sub,
            "templates": templates,
            "applicants": applicants,
            "today_sent": today_sent,
            "daily_limit": daily_limit,
            "remaining_today": max(0, daily_limit - today_sent),
            "sidebar_section": "campaigns",
        }
        return render(request, self.template_name, ctx)

    def post(self, request, *args, **kwargs):
        company = self.get_company()
        if not company:
            return redirect("recruiter:company-profile")

        name = request.POST.get("name", "").strip()
        subject = request.POST.get("subject", "").strip()
        body_html = request.POST.get("body_html", "").strip()
        template_id = request.POST.get("template_id")
        candidate_ids_raw = request.POST.getlist("candidate_ids")

        if not name or not subject or not body_html:
            messages.error(request, "Campaign name, subject, and message body are required.")
            return redirect("billing:campaign-create")

        if not candidate_ids_raw:
            messages.error(request, "Please select at least one candidate for this campaign.")
            return redirect("billing:campaign-create")

        candidate_ids = []
        for cid in candidate_ids_raw:
            try:
                candidate_ids.append(uuid.UUID(cid))
            except ValueError:
                pass

        if not candidate_ids:
            messages.error(request, "No valid candidates selected.")
            return redirect("billing:campaign-create")

        template = EmailTemplate.objects.filter(pk=template_id).first() if template_id else None

        try:
            campaign = RecruiterCampaignService.create_campaign(
                company=company,
                created_by=request.user,
                name=name,
                subject=subject,
                body_html=body_html,
                candidate_ids=candidate_ids,
                template=template,
            )
            messages.success(
                request,
                f"Campaign '{campaign.name}' with {len(candidate_ids)} recipients has been submitted for Admin approval! "
                "Once reviewed by SevaJobs staff, dispatch will begin.",
            )
            return redirect("billing:campaign-list")
        except ValueError as ve:
            messages.error(request, str(ve))
            return redirect("billing:campaign-create")
        except Exception as e:
            logger.exception("Failed to create campaign: %s", e)
            messages.error(request, f"Failed to submit campaign: {e}")
            return redirect("billing:campaign-create")


class RecruiterCampaignDetailView(RecruiterAccessMixin, TemplateView):
    """
    GET /dashboard/recruiter/campaigns/<uuid:pk>/
    View campaign delivery, open rate, and click rate details.
    """

    template_name = "dashboard/recruiter/campaign_detail.html"
    sidebar_section = "campaigns"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.get_company()
        campaign = get_object_or_404(RecruiterCampaign, pk=self.kwargs.get("pk"), company=company)
        recipients = campaign.recipients.select_related("candidate_user").order_by("-sent_at")[:100]

        open_rate = (campaign.opened_count / campaign.sent_count * 100) if campaign.sent_count > 0 else 0
        click_rate = (campaign.clicked_count / campaign.sent_count * 100) if campaign.sent_count > 0 else 0

        ctx.update({
            "campaign": campaign,
            "recipients": recipients,
            "open_rate": round(open_rate, 1),
            "click_rate": round(click_rate, 1),
        })
        return ctx
