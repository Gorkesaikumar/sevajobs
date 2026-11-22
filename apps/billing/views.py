"""
Billing, Payment, Webhook, and Recruiter Entitlements Views.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import HttpRequest, HttpResponse, JsonResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import TemplateView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.permissions import IsRecruiter
from apps.recruiters.models import Company, RecruiterProfile
from .cashfree_service import CashfreePaymentGateway
from .models import (
    SubscriptionPlan,
    RecruiterSubscription,
    ResumeUnlock,
    PaymentOrder,
    PaymentWebhookEvent,
    RecruiterCampaign,
    RecruiterCampaignRecipient,
)
from .services import BillingEntitlementService

logger = logging.getLogger("apps.billing")

# 1x1 transparent GIF bytes for email open tracking
TRANSPARENT_GIF_BYTES = (
    b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff"
    b"\x00\x00\x00\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00"
    b"\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b"
)


def get_public_base_url(request: HttpRequest | None = None) -> str:
    """
    Resolves the canonical public base URL (e.g. 'https://sevajobs.in').
    Priority:
    1. settings.SITE_URL or settings.PUBLIC_BASE_URL
    2. request.build_absolute_uri('/')
    3. fallback to 'https://sevajobs.in'
    Ensures 'https://' in production environments.
    """
    base = getattr(settings, "SITE_URL", "") or getattr(settings, "PUBLIC_BASE_URL", "")
    if base:
        base = str(base).strip().rstrip("/")
        if not getattr(settings, "DEBUG", True) and base.startswith("http://"):
            base = "https://" + base[len("http://"):]
        return base

    if request:
        uri = request.build_absolute_uri("/").rstrip("/")
        if not getattr(settings, "DEBUG", True) and uri.startswith("http://"):
            uri = "https://" + uri[len("http://"):]
        return uri

    return "https://sevajobs.in"


class RecruiterAccessMixin(LoginRequiredMixin, UserPassesTestMixin):
    login_url = "/recruiter/login/"

    def test_func(self):
        if not self.request.user.is_authenticated:
            return False
        return self.request.user.is_recruiter or getattr(self.request.user, "is_admin_role", False)

    def get_company(self) -> Company | None:
        recruiter_profile = getattr(self.request.user, "recruiter_profile", None)
        if recruiter_profile:
            return recruiter_profile.company
        return Company.objects.filter(recruiters__user=self.request.user).first()


# ===========================================================================
# 1. Public / Recruiter Pricing Page (/pricing/)
# ===========================================================================
class PricingPageView(TemplateView):
    """
    Public and recruiter pricing page.
    Displays exactly 4 primary pricing cards + Quick Unlock add-on:
    1. Free Job Posting (₹0)
    2. Premium Job Posting (₹5,999 + GST)
    3. Walk-in at School! (₹29,999 + GST)
    4. Database Access Pro (₹49,999 + GST)
    + Quick Unlock (₹999 + GST for 10 resumes)
    """

    template_name = "pages/pricing.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        all_plans = SubscriptionPlan.objects.filter(is_active=True).order_by("display_order", "price_inr")

        # Select exactly the 4 primary plans to display prominently
        primary_codes = ["free", "premium_50", "walkin_school", "db_access_pro"]
        primary_plans = []
        for code in primary_codes:
            p = all_plans.filter(code=code).first()
            if p:
                primary_plans.append(p)

        quick_unlock = all_plans.filter(code="quick_unlock_10").first()
        db_1k = all_plans.filter(code="db_access_1k").first()

        company = None
        current_sub = None
        if self.request.user.is_authenticated and self.request.user.is_recruiter:
            profile = getattr(self.request.user, "recruiter_profile", None)
            if profile:
                company = profile.company
                current_sub = BillingEntitlementService.get_company_subscription(company)

        ctx.update({
            "primary_plans": primary_plans,
            "quick_unlock_plan": quick_unlock,
            "db_1k_plan": db_1k,
            "company": company,
            "current_subscription": current_sub,
            "cashfree_env": getattr(settings, "CASHFREE_ENV", "TEST"),
        })
        return ctx


# ===========================================================================
# 2. Recruiter Billing Dashboard (/dashboard/recruiter/billing/)
# ===========================================================================
class RecruiterBillingDashboardView(RecruiterAccessMixin, TemplateView):
    """
    Dedicated Recruiter Billing & Entitlements dashboard.
    Shows current package, active balances, purchase history, and quick top-up options.
    """

    template_name = "dashboard/recruiter/billing.html"
    sidebar_section = "billing"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.get_company()
        if not company:
            ctx["company"] = None
            return ctx

        current_sub = BillingEntitlementService.get_company_subscription(company)
        active_jobs = BillingEntitlementService.get_active_job_count(company)
        recent_orders = PaymentOrder.objects.filter(company=company).order_by("-created_at")[:15]
        quick_unlock_plan = SubscriptionPlan.objects.filter(code="quick_unlock_10").first()
        unlocked_count = ResumeUnlock.objects.filter(company=company).count()

        ctx.update({
            "company": company,
            "current_subscription": current_sub,
            "active_jobs_count": active_jobs,
            "free_job_limit": BillingEntitlementService.FREE_ACTIVE_JOB_LIMIT,
            "recent_orders": recent_orders,
            "quick_unlock_plan": quick_unlock_plan,
            "unlocked_resumes_count": unlocked_count,
            "cashfree_env": getattr(settings, "CASHFREE_ENV", "TEST"),
        })
        return ctx


# ===========================================================================
# 3. Create Payment Order API / Endpoint
# ===========================================================================
class CreatePaymentOrderView(RecruiterAccessMixin, View):
    """
    POST /billing/create-order/
    Initializes a Cashfree PG order with server-calculated GST and returns payment_session_id.
    """

    def post(self, request: HttpRequest, *args, **kwargs) -> JsonResponse:
        company = self.get_company()
        if not company:
            return JsonResponse({"success": False, "error": "Company profile required."}, status=400)

        plan_code = request.POST.get("plan_code") or request.GET.get("plan_code")
        if not plan_code:
            try:
                body = json.loads(request.body.decode("utf-8"))
                plan_code = body.get("plan_code")
            except Exception:
                pass

        if not plan_code:
            return JsonResponse({"success": False, "error": "Plan code is required."}, status=400)

        plan = get_object_or_404(SubscriptionPlan, code=plan_code, is_active=True)
        if plan.code == "free":
            return JsonResponse(
                {"success": False, "error": "Free plan does not require payment."},
                status=400,
            )

        # Server-side monetary integrity
        base_amt = plan.price_inr
        gst_amt = plan.gst_amount
        total_amt = plan.total_amount

        # Generate unique order ID
        uid = uuid.uuid4().hex[:10].upper()
        order_id = f"ORDER_SJ_{uid}"

        item_type = (
            PaymentOrder.ItemType.QUICK_UNLOCK
            if plan.category == SubscriptionPlan.Category.ADDON
            else PaymentOrder.ItemType.PLAN
        )

        payment_order = PaymentOrder.objects.create(
            order_id=order_id,
            company=company,
            user=request.user,
            plan=plan,
            item_code=plan.code,
            item_type=item_type,
            base_amount=base_amt,
            gst_rate=plan.gst_rate,
            gst_amount=gst_amt,
            total_amount=total_amt,
            currency="INR",
            status=PaymentOrder.Status.CREATED,
        )

        # Build canonical public callback URLs (honoring reverse proxy HTTPS & SITE_URL)
        base_url = get_public_base_url(request)
        return_url = f"{base_url}/billing/verify/?order_id={order_id}"
        notify_url = f"{base_url}/billing/webhook/"

        pg = CashfreePaymentGateway()
        try:
            cf_resp = pg.create_order(
                order_id=order_id,
                amount=total_amt,
                customer_id=str(request.user.pk),
                customer_name=request.user.full_name or company.name,
                customer_email=request.user.email,
                customer_phone=request.user.phone or company.phone or "9999999999",
                return_url=return_url,
                notify_url=notify_url,
                order_note=f"SevaJobs: {plan.name}",
            )

            payment_order.cf_order_id = cf_resp.get("cf_order_id", "")
            payment_order.payment_session_id = cf_resp.get("payment_session_id", "")
            payment_order.raw_response = cf_resp
            payment_order.save(update_fields=["cf_order_id", "payment_session_id", "raw_response"])

            return JsonResponse({
                "success": True,
                "order_id": order_id,
                "cf_order_id": payment_order.cf_order_id,
                "payment_session_id": payment_order.payment_session_id,
                "total_amount": str(total_amt),
                "plan_name": plan.name,
                "environment": pg.env,
            })
        except Exception as e:
            logger.exception("Failed to create Cashfree order %s: %s", order_id, e)
            payment_order.status = PaymentOrder.Status.FAILED
            payment_order.raw_response = {"error": str(e)}
            payment_order.save(update_fields=["status", "raw_response"])

            # Sanitize user error to prevent raw Python socket/traceback leakage
            err_str = str(e)
            if any(k in err_str.lower() for k in ("unreachable", "timeout", "timed out", "connection", "connecttimeouterror")):
                user_error = "Payment gateway is currently unreachable or timed out. Please check your connection and try again in a moment."
            elif isinstance(e, ValueError):
                user_error = err_str
            else:
                user_error = "Unable to initialize payment checkout. Please try again shortly or contact support."

            return JsonResponse({"success": False, "error": user_error}, status=500)


# ===========================================================================
# 4. Payment Return / Verification View
# ===========================================================================
class PaymentVerifyView(View):
    """
    GET /billing/verify/?order_id=ORDER_SJ_...
    Cashfree redirects the browser here upon checkout completion.
    Verifies gateway status and triggers idempotent entitlement activation.
    """

    def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponseRedirect:
        order_id = request.GET.get("order_id", "").strip()
        if not order_id:
            messages.error(request, "Order ID missing from payment verification request.")
            return redirect("billing:dashboard")

        order = PaymentOrder.objects.filter(order_id=order_id).first()
        if not order:
            messages.error(request, f"Order '{order_id}' could not be found.")
            return redirect("billing:dashboard")

        if order.status == PaymentOrder.Status.PAID:
            messages.success(request, f"Payment for '{order.plan.name if order.plan else order.item_code}' is confirmed!")
            return redirect("billing:dashboard")

        # Fetch status from Cashfree
        pg = CashfreePaymentGateway()
        try:
            cf_order = pg.get_order_status(order_id)
            cf_status = cf_order.get("order_status", "").upper()

            if cf_status == "PAID":
                BillingEntitlementService.process_successful_payment(
                    order_id=order_id,
                    cf_order_id=cf_order.get("cf_order_id", ""),
                    raw_response=cf_order,
                )
                messages.success(
                    request,
                    f"Payment successful! Your '{order.plan.name if order.plan else 'package'}' is now active.",
                )
            elif cf_status in ("FAILED", "USER_DROPPED", "CANCELLED"):
                order.status = PaymentOrder.Status.FAILED
                order.raw_response = cf_order
                order.save(update_fields=["status", "raw_response"])
                messages.error(request, f"Payment was {cf_status.lower()}. Please try again.")
            else:
                messages.info(request, "Your payment is being processed. Balances will update shortly.")
        except Exception as e:
            logger.exception("Error verifying payment for order %s: %s", order_id, e)
            messages.warning(request, "Could not verify payment instantly. Our system will check shortly.")

        return redirect("billing:dashboard")


# ===========================================================================
# 5. Cashfree Asynchronous Webhook Handler
# ===========================================================================
@method_decorator(csrf_exempt, name="dispatch")
class CashfreeWebhookView(View):
    """
    GET/POST /billing/webhook/
    Server-to-server webhook endpoint for Cashfree PG events.
    Verifies HMAC-SHA256 signature, logs event, and idempotently provisions entitlements.
    """

    def get(self, request: HttpRequest, *args, **kwargs) -> JsonResponse:
        """Health check endpoint for webhooks."""
        return JsonResponse({
            "status": "active",
            "message": "Cashfree webhook listener is running.",
            "endpoint": "/billing/webhook/",
        })

    def post(self, request: HttpRequest, *args, **kwargs) -> JsonResponse:
        raw_body = request.body

        # 1. Parse JSON first (400 on invalid/malformed JSON)
        try:
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error("Invalid JSON payload in Cashfree webhook: %s", e)
            return JsonResponse({"status": "invalid_json", "error": "Malformed JSON payload"}, status=400)

        # 2. Extract signature and timestamp headers
        signature = (
            request.headers.get("x-webhook-signature")
            or request.headers.get("x-cf-signature")
            or request.META.get("HTTP_X_WEBHOOK_SIGNATURE")
            or request.META.get("HTTP_X_CF_SIGNATURE")
            or ""
        )
        timestamp = (
            request.headers.get("x-webhook-timestamp")
            or request.headers.get("x-cf-timestamp")
            or request.META.get("HTTP_X_WEBHOOK_TIMESTAMP")
            or request.META.get("HTTP_X_CF_TIMESTAMP")
            or ""
        )

        pg = CashfreePaymentGateway()
        is_valid_sig = pg.verify_webhook_signature(raw_body, signature, timestamp)

        event_type = str(payload.get("type") or payload.get("event") or "").upper()
        event_data = payload.get("data", {}) if isinstance(payload.get("data"), dict) else {}
        order_info = event_data.get("order", {}) if isinstance(event_data.get("order"), dict) else {}
        payment_info = event_data.get("payment", {}) if isinstance(event_data.get("payment"), dict) else {}
        order_id = str(
            order_info.get("order_id")
            or event_data.get("order_id")
            or payload.get("order_id")
            or ""
        ).strip()

        # 3. Handle Cashfree Dashboard Test/Ping Events cleanly
        is_test_event = (
            event_type in ("TEST_WEBHOOK", "TEST", "PING")
            or order_id.lower().startswith("test")
            or "test" in event_type.lower()
        )
        if is_test_event:
            # If signature provided on test ping, verify it; reject if bad
            if signature and not is_valid_sig:
                logger.warning("Rejected Cashfree test webhook due to invalid signature.")
                return JsonResponse({"status": "invalid_signature", "error": "Test webhook signature failed"}, status=401)

            logger.info("Cashfree dashboard test webhook received and verified: %s", event_type)
            return JsonResponse({
                "status": "ok",
                "message": "Test webhook verified successfully.",
                "event_type": event_type,
            }, status=200)

        # 4. Reject invalid HMAC signatures with HTTP 401 BEFORE database persistence
        # (Prevents unauthenticated scanner bots / random POSTs from polluting the database)
        if not is_valid_sig:
            logger.warning(
                "Rejected Cashfree webhook due to invalid signature (Order: '%s', Event: '%s', IP: %s).",
                order_id,
                event_type,
                request.META.get("REMOTE_ADDR"),
            )
            return JsonResponse({"status": "invalid_signature", "error": "Signature verification failed"}, status=401)

        # 5. Deterministic event_id generation for deduplication / replay protection
        cf_payment_id = str(payment_info.get("cf_payment_id", "") or "").strip()
        event_time = str(payload.get("event_time", "") or "").strip()

        if order_id and cf_payment_id and event_type:
            deterministic_event_id = f"{order_id}_{cf_payment_id}_{event_type}"[:128]
        elif order_id and event_type and event_time:
            deterministic_event_id = f"{order_id}_{event_type}_{event_time}"[:128]
        elif payload.get("event_id"):
            deterministic_event_id = str(payload["event_id"])[:128]
        else:
            body_digest = hashlib.sha256((timestamp or "").encode("utf-8") + b":" + raw_body).hexdigest()
            deterministic_event_id = f"cf_{body_digest[:48]}"

        # 6. Idempotent get_or_create of PaymentWebhookEvent
        webhook_event, created = PaymentWebhookEvent.objects.get_or_create(
            event_id=deterministic_event_id,
            defaults={
                "event_type": event_type or "UNKNOWN",
                "order_id": order_id,
                "signature_valid": True,
                "raw_payload": payload,
            },
        )

        if not created and webhook_event.processed:
            logger.info("Webhook event '%s' was already processed. Skipping duplicate delivery.", deterministic_event_id)
            return JsonResponse({"status": "already_processed", "message": "Event already processed."}, status=200)

        # 7. Process payment events
        payment_status = str(payment_info.get("payment_status", "")).upper()
        order_status = str(order_info.get("order_status", "")).upper()

        is_paid_event = (
            event_type in ("PAYMENT_SUCCESS_WEBHOOK", "ORDER_PAID_WEBHOOK")
            or payment_status == "SUCCESS"
            or order_status == "PAID"
        )

        if is_paid_event and order_id:
            payment_method = payment_info.get("payment_group", "") or payment_info.get("payment_method", "")

            success, msg = BillingEntitlementService.process_successful_payment(
                order_id=order_id,
                cf_payment_id=cf_payment_id,
                payment_method=payment_method,
                raw_response=payload,
            )
            webhook_event.processed = success
            webhook_event.processed_at = timezone.now()
            webhook_event.error_message = "" if success else msg
            webhook_event.save(update_fields=["processed", "processed_at", "error_message"])

        return JsonResponse({"status": "ok"})


# ===========================================================================
# 6. Candidate Resume Unlock & Contacted Tag APIs
# ===========================================================================
class ResumeUnlockAPIView(APIView):
    """
    POST /api/v1/billing/resumes/<uuid:candidate_user_id>/unlock/
    Unlocks a candidate profile and resume using 1 company credit.
    """

    permission_classes = [IsAuthenticated, IsRecruiter]

    def post(self, request: HttpRequest, candidate_user_id: uuid.UUID) -> Response:
        profile = getattr(request.user, "recruiter_profile", None)
        if not profile or not profile.company:
            return Response({"error": "Recruiter company profile required."}, status=status.HTTP_400_BAD_REQUEST)

        candidate_user = get_object_or_404(User, pk=candidate_user_id)
        company = profile.company

        success, msg, unlock = BillingEntitlementService.unlock_candidate(
            company=company,
            candidate_user=candidate_user,
            unlocked_by=request.user,
            source_type=ResumeUnlock.SourceType.PLAN,
        )

        if not success:
            return Response({"success": False, "error": msg}, status=status.HTTP_402_PAYMENT_REQUIRED)

        # Fetch resume download URL
        primary_resume = candidate_user.resumes.filter(is_primary=True).first() or candidate_user.resumes.first()
        resume_url = (
            request.build_absolute_uri(primary_resume.file.url)
            if (primary_resume and primary_resume.file)
            else None
        )

        return Response({
            "success": True,
            "message": msg,
            "candidate": {
                "id": str(candidate_user.pk),
                "name": candidate_user.full_name,
                "email": candidate_user.email,
                "phone": candidate_user.phone,
                "is_unlocked": True,
                "is_contacted": unlock.is_contacted if unlock else False,
                "primary_resume": resume_url,
            },
        })


class ToggleContactedTagAPIView(APIView):
    """
    POST /api/v1/billing/resumes/<uuid:candidate_user_id>/toggle-contacted/
    Toggles the recruiter 'Contacted' tag on an already unlocked candidate.
    """

    permission_classes = [IsAuthenticated, IsRecruiter]

    def post(self, request: HttpRequest, candidate_user_id: uuid.UUID) -> Response:
        profile = getattr(request.user, "recruiter_profile", None)
        if not profile or not profile.company:
            return Response({"error": "Recruiter company profile required."}, status=status.HTTP_400_BAD_REQUEST)

        candidate_user = get_object_or_404(User, pk=candidate_user_id)
        success, is_contacted = BillingEntitlementService.toggle_contacted_tag(
            company=profile.company,
            candidate_user=candidate_user,
        )

        if not success:
            return Response(
                {"success": False, "error": "Candidate must be unlocked before tagging as contacted."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({
            "success": True,
            "is_contacted": is_contacted,
            "message": f"Candidate tagged as {'contacted' if is_contacted else 'not contacted'}.",
        })


# ===========================================================================
# 7. Bulk Email Tracking (Open & Click Trackers)
# ===========================================================================
class EmailTrackingPixelView(View):
    """
    GET /billing/track/open/<str:tracking_token>/
    1x1 transparent tracking pixel embedded in outgoing recruiter campaign emails.
    """

    def get(self, request: HttpRequest, tracking_token: str) -> HttpResponse:
        recipient = RecruiterCampaignRecipient.objects.filter(tracking_token=tracking_token).select_related("campaign").first()
        if recipient:
            if not recipient.opened_at:
                recipient.opened_at = timezone.now()
                recipient.status = RecruiterCampaignRecipient.Status.OPENED
                recipient.save(update_fields=["opened_at", "status"])

                # Increment campaign opened count
                campaign = recipient.campaign
                campaign.opened_count += 1
                campaign.save(update_fields=["opened_count"])

        resp = HttpResponse(TRANSPARENT_GIF_BYTES, content_type="image/gif")
        resp["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp["Pragma"] = "no-cache"
        resp["Expires"] = "0"
        return resp


class EmailTrackingClickView(View):
    """
    GET /billing/track/click/<str:tracking_token>/?url=<target_url>
    Redirect tracking for links in recruiter emails.
    """

    def get(self, request: HttpRequest, tracking_token: str) -> HttpResponseRedirect:
        target_url = request.GET.get("url", "/").strip()
        recipient = RecruiterCampaignRecipient.objects.filter(tracking_token=tracking_token).select_related("campaign").first()
        if recipient:
            if not recipient.clicked_at:
                recipient.clicked_at = timezone.now()
                recipient.status = RecruiterCampaignRecipient.Status.CLICKED
                recipient.save(update_fields=["clicked_at", "status"])

                campaign = recipient.campaign
                campaign.clicked_count += 1
                campaign.save(update_fields=["clicked_count"])

        return HttpResponseRedirect(target_url or "/")
