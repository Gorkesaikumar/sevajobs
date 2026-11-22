"""
Recruiter Candidate Database Search View.
Provides searchable access to 20,000+ teacher resumes with server-side masking,
instant credit unlock, Quick Unlock upsell modal, and Contacted tag tracking.
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone
from django.views.generic import TemplateView

from apps.accounts.models import JobSeekerProfile, User
from .models import ResumeUnlock, SubscriptionPlan
from .services import BillingEntitlementService
from .views import RecruiterAccessMixin

logger = logging.getLogger("apps.billing")


class RecruiterCandidateSearchView(RecruiterAccessMixin, TemplateView):
    """
    GET /dashboard/recruiter/candidates/
    Talent search across all open-to-work teacher profiles.
    Server-side masks contact details unless unlocked by the recruiter's company.
    """

    template_name = "dashboard/recruiter/candidate_search.html"
    sidebar_section = "candidate-database"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.get_company()
        if not company:
            ctx["company"] = None
            return ctx

        sub = BillingEntitlementService.get_company_subscription(company)
        quick_unlock_plan = SubscriptionPlan.objects.filter(code="quick_unlock_10").first()

        # Query parameters
        q = self.request.GET.get("q", "").strip()
        subject = self.request.GET.get("subject", "").strip()
        location = self.request.GET.get("location", "").strip()
        min_exp = self.request.GET.get("min_exp", "").strip()
        unlocked_only = self.request.GET.get("unlocked_only", "") == "1"

        qs = (
            JobSeekerProfile.objects.filter(
                user__role=User.Role.JOB_SEEKER,
                user__is_active=True,
                is_open_to_work=True,
            )
            .select_related("user")
            .prefetch_related("skills", "qualifications", "user__resumes")
            .distinct()
        )

        if q:
            qs = qs.filter(
                Q(headline__icontains=q)
                | Q(designation__icontains=q)
                | Q(subject__icontains=q)
                | Q(skills__name__icontains=q)
                | Q(user__first_name__icontains=q)
                | Q(user__last_name__icontains=q)
            )

        if subject:
            qs = qs.filter(subject__icontains=subject)

        if location:
            qs = qs.filter(
                Q(current_location__icontains=location)
                | Q(preferred_location__icontains=location)
            )

        if min_exp:
            try:
                qs = qs.filter(experience_years__gte=int(min_exp))
            except ValueError:
                pass

        # Fetch all unlocked candidate user IDs for this company
        now = timezone.now()
        unlocked_map = {
            u.candidate_user_id: u
            for u in ResumeUnlock.objects.filter(company=company).filter(
                Q(expires_at__isnull=True) | Q(expires_at__gt=now)
            )
        }

        if unlocked_only:
            qs = qs.filter(user_id__in=unlocked_map.keys())

        paginator = Paginator(qs, 15)
        page_num = self.request.GET.get("page", 1)
        page_obj = paginator.get_page(page_num)

        # Build display candidate items with masking
        candidate_items = []
        for profile in page_obj:
            candidate_user = profile.user
            unlock = unlocked_map.get(candidate_user.id)
            is_unlocked = unlock is not None
            is_contacted = unlock.is_contacted if unlock else False

            email = candidate_user.email if is_unlocked else BillingEntitlementService.mask_email(candidate_user.email)
            phone = candidate_user.phone if is_unlocked else BillingEntitlementService.mask_phone(candidate_user.phone)

            primary_resume = None
            if is_unlocked:
                res = candidate_user.resumes.filter(is_primary=True).first() or candidate_user.resumes.first()
                if res and res.file:
                    primary_resume = res.file.url

            candidate_items.append({
                "profile": profile,
                "user": candidate_user,
                "is_unlocked": is_unlocked,
                "is_contacted": is_contacted,
                "display_email": email,
                "display_phone": phone,
                "primary_resume_url": primary_resume,
            })

        ctx.update({
            "company": company,
            "subscription": sub,
            "quick_unlock_plan": quick_unlock_plan,
            "page_obj": page_obj,
            "candidates": candidate_items,
            "total_count": paginator.count,
            "q": q,
            "subject": subject,
            "location": location,
            "min_exp": min_exp,
            "unlocked_only": unlocked_only,
            "cashfree_env": getattr(settings, "CASHFREE_ENV", "TEST"),
        })
        return ctx
