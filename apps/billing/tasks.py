"""
Celery tasks for Billing, Payments, and Recruiter Campaigns.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger("apps.billing")


@shared_task(name="billing.dispatch_campaign")
def dispatch_campaign_task(campaign_id: str) -> int:
    """
    Asynchronously dispatches an approved recruiter campaign.
    """
    from .models import RecruiterCampaign
    from .campaign_service import RecruiterCampaignService

    try:
        campaign = RecruiterCampaign.objects.get(pk=campaign_id)
        if campaign.status != RecruiterCampaign.Status.APPROVED:
            logger.warning("Campaign %s is not in APPROVED status (status=%s). Skipping dispatch.", campaign_id, campaign.status)
            return 0
        return RecruiterCampaignService.dispatch_campaign(campaign)
    except Exception as exc:
        logger.exception("Failed to dispatch campaign %s: %s", campaign_id, exc)
        return 0


@shared_task(name="billing.expire_quick_unlocks")
def expire_quick_unlocks() -> int:
    """
    Periodic task: identifies quick-unlock records whose 30-day validity has passed.
    """
    from .models import ResumeUnlock

    now = timezone.now()
    expired_qs = ResumeUnlock.objects.filter(expires_at__isnull=False, expires_at__lte=now)
    count = expired_qs.count()
    if count > 0:
        logger.info("Identified %d expired quick-unlock records.", count)
    return count


@shared_task(name="billing.reconcile_pending_payment_orders")
def reconcile_pending_payment_orders() -> int:
    """
    Periodic task: checks PaymentOrders created > 15 minutes ago but still in CREATED status.
    Queries Cashfree PG to reconcile any completed transactions where webhooks were delayed.
    """
    from .models import PaymentOrder
    from .cashfree_service import CashfreePaymentGateway
    from .services import BillingEntitlementService

    cutoff = timezone.now() - timedelta(minutes=15)
    pending_orders = PaymentOrder.objects.filter(
        status=PaymentOrder.Status.CREATED,
        created_at__lte=cutoff,
        cf_order_id__isnull=False,
    ).exclude(cf_order_id="")[:20]

    reconciled = 0
    pg = CashfreePaymentGateway()
    for order in pending_orders:
        try:
            status_data = pg.get_order_status(order.order_id)
            cf_status = status_data.get("order_status", "").upper()
            if cf_status == "PAID":
                BillingEntitlementService.activate_paid_order(order, raw_response=status_data)
                reconciled += 1
                logger.info("Reconciled order %s via Cashfree polling to PAID.", order.order_id)
            elif cf_status in ("EXPIRED", "TERMINATED", "FAILED"):
                order.status = PaymentOrder.Status.FAILED
                order.raw_response = status_data
                order.save(update_fields=["status", "raw_response"])
        except Exception as exc:
            logger.warning("Reconciliation check failed for order %s: %s", order.order_id, exc)

    return reconciled
