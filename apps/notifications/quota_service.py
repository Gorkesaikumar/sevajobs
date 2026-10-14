"""
Domain service for atomic daily email quota tracking, capacity reservation,
and accounting across bulk email campaigns.

Enforces:
- Hard limit of 100 emails/day (configurable via BULK_EMAIL_DAILY_LIMIT).
- Operational target of 90 emails/day (configurable via BULK_EMAIL_DAILY_TARGET).
- Warning threshold of 80 emails/day (configurable via BULK_EMAIL_DAILY_WARNING_THRESHOLD).
- Concurrency-safe reservations using database transactions and row-level locking.
"""

from __future__ import annotations

import logging
from typing import Dict, Any, Optional
from datetime import date
from django.conf import settings
from django.db import transaction, models
from django.utils import timezone

from .models import DailyEmailQuotaTracking, CampaignRecipient

logger = logging.getLogger("apps.notifications")


class DailyEmailQuotaService:
    """Manages daily email quota reservations, tracking, and reconciliation."""

    @classmethod
    def get_configured_limits(cls) -> Dict[str, int]:
        """Fetch active daily quota parameters from Django settings."""
        return {
            "daily_limit": getattr(settings, "BULK_EMAIL_DAILY_LIMIT", 100),
            "daily_target": getattr(settings, "BULK_EMAIL_DAILY_TARGET", 90),
            "warning_threshold": getattr(settings, "BULK_EMAIL_DAILY_WARNING_THRESHOLD", 80),
        }

    @classmethod
    def get_or_create_today_quota(cls, today: Optional[date] = None) -> DailyEmailQuotaTracking:
        """Retrieve or create the tracking record for the specified or current calendar date."""
        target_date = today or timezone.now().date()
        limits = cls.get_configured_limits()
        record, _ = DailyEmailQuotaTracking.objects.get_or_create(
            date=target_date,
            defaults={
                "daily_limit": limits["daily_limit"],
                "daily_target": limits["daily_target"],
            },
        )
        return record

    @classmethod
    def get_quota_status(cls, today: Optional[date] = None) -> Dict[str, Any]:
        """
        Compute full operational quota status including sent, queued, remaining,
        and threshold warnings.
        """
        record = cls.get_or_create_today_quota(today)
        limits = cls.get_configured_limits()

        consumed = record.sent_count + record.reserved_count
        remaining = max(0, record.daily_limit - consumed)
        target_remaining = max(0, record.daily_target - consumed)
        percent_used = min(100.0, round((consumed / record.daily_limit) * 100, 1)) if record.daily_limit > 0 else 100.0

        if consumed >= record.daily_limit:
            status_text = "limit_reached"
        elif consumed >= limits["warning_threshold"]:
            status_text = "warning"
        else:
            status_text = "normal"

        return {
            "date": record.date.isoformat(),
            "sent_today": record.sent_count,
            "in_queue": record.reserved_count,
            "delivered_today": record.delivered_count,
            "failed_today": record.failed_count,
            "daily_limit": record.daily_limit,
            "daily_target": record.daily_target,
            "warning_threshold": limits["warning_threshold"],
            "total_consumed": consumed,
            "used": consumed,
            "remaining": remaining,
            "target_remaining": target_remaining,
            "status": status_text,
            "is_warning": consumed >= limits["warning_threshold"],
            "is_target_reached": consumed >= record.daily_target,
            "is_limit_reached": consumed >= record.daily_limit,
            "percent_used": percent_used,
            "consumption_percentage": percent_used,
            "last_sent_at": record.last_sent_at.isoformat() if record.last_sent_at else None,
            "last_error": record.last_error,
        }

    @classmethod
    def can_reserve_quota(cls, count: int, today: Optional[date] = None) -> bool:
        """Check whether 'count' emails can be accommodated within the remaining daily limit."""
        if count <= 0:
            return True
        status = cls.get_quota_status(today)
        return status["remaining"] >= count

    @classmethod
    def reserve_quota(cls, count: int, today: Optional[date] = None) -> bool:
        """
        Atomically reserve email capacity for queued recipients.
        Uses SELECT FOR UPDATE row locking to prevent race conditions across concurrent workers.
        """
        if count <= 0:
            return True

        target_date = today or timezone.now().date()
        limits = cls.get_configured_limits()

        with transaction.atomic():
            record, _ = DailyEmailQuotaTracking.objects.select_for_update().get_or_create(
                date=target_date,
                defaults={
                    "daily_limit": limits["daily_limit"],
                    "daily_target": limits["daily_target"],
                },
            )

            total_consumed = record.sent_count + record.reserved_count
            if total_consumed + count > record.daily_limit:
                logger.warning(
                    "Quota reservation rejected for date=%s: requested=%d, consumed=%d, limit=%d",
                    target_date, count, total_consumed, record.daily_limit
                )
                return False

            record.reserved_count += count
            record.save(update_fields=["reserved_count", "updated_at"])

        logger.info("Reserved %d quota capacity on date=%s. New reserved_count=%d", count, target_date, record.reserved_count)
        return True

    @classmethod
    def release_reserved_quota(cls, count: int, today: Optional[date] = None) -> None:
        """Release unused reserved capacity (e.g. when campaigns are cancelled or recipients suppressed)."""
        if count <= 0:
            return

        target_date = today or timezone.now().date()
        with transaction.atomic():
            record = DailyEmailQuotaTracking.objects.select_for_update().filter(date=target_date).first()
            if record:
                record.reserved_count = max(0, record.reserved_count - count)
                record.save(update_fields=["reserved_count", "updated_at"])
                logger.info("Released %d reserved quota capacity on date=%s. New reserved_count=%d", count, target_date, record.reserved_count)

    @classmethod
    def record_send_success(cls, count: int = 1, today: Optional[date] = None) -> None:
        """Transition reserved capacity into confirmed sent count upon provider acceptance."""
        if count <= 0:
            return

        target_date = today or timezone.now().date()
        with transaction.atomic():
            record = cls.get_or_create_today_quota(target_date)
            record = DailyEmailQuotaTracking.objects.select_for_update().get(pk=record.pk)

            # Move from reserved to sent
            record.reserved_count = max(0, record.reserved_count - count)
            record.sent_count += count
            record.last_sent_at = timezone.now()
            record.save(update_fields=["reserved_count", "sent_count", "last_sent_at", "updated_at"])

    @classmethod
    def record_send_failure(cls, count: int = 1, error: str = "", today: Optional[date] = None) -> None:
        """Record terminal delivery failures and release associated reservation."""
        if count <= 0:
            return

        target_date = today or timezone.now().date()
        with transaction.atomic():
            record = cls.get_or_create_today_quota(target_date)
            record = DailyEmailQuotaTracking.objects.select_for_update().get(pk=record.pk)

            record.reserved_count = max(0, record.reserved_count - count)
            record.failed_count += count
            if error:
                record.last_error = str(error)[:500]
            record.save(update_fields=["reserved_count", "failed_count", "last_error", "updated_at"])

    @classmethod
    def record_delivery_success(cls, count: int = 1, today: Optional[date] = None) -> None:
        """Increment verified delivered count from Resend webhook events."""
        if count <= 0:
            return

        target_date = today or timezone.now().date()
        with transaction.atomic():
            record = cls.get_or_create_today_quota(target_date)
            DailyEmailQuotaTracking.objects.filter(pk=record.pk).update(
                delivered_count=models.F("delivered_count") + count,
                updated_at=timezone.now(),
            )

    @classmethod
    def reconcile_today_quota(cls, today: Optional[date] = None) -> DailyEmailQuotaTracking:
        """
        Reconcile quota tracking against actual persisted CampaignRecipient records.
        Protects against discrepancies from worker restarts or unexpected crashes.
        """
        target_date = today or timezone.now().date()
        with transaction.atomic():
            record = cls.get_or_create_today_quota(target_date)
            record = DailyEmailQuotaTracking.objects.select_for_update().get(pk=record.pk)

            from .models import JobAlertRecipient

            cr_sent = CampaignRecipient.objects.filter(
                sent_at__date=target_date,
                status__in=[CampaignRecipient.RecipientStatus.SENT, CampaignRecipient.RecipientStatus.DELIVERED],
            ).count()
            ja_sent = JobAlertRecipient.objects.filter(
                sent_at__date=target_date,
                status__in=[JobAlertRecipient.RecipientStatus.SENT, JobAlertRecipient.RecipientStatus.DELIVERED],
            ).count()
            actual_sent = cr_sent + ja_sent

            cr_delivered = CampaignRecipient.objects.filter(
                delivered_at__date=target_date,
                status=CampaignRecipient.RecipientStatus.DELIVERED,
            ).count()
            ja_delivered = JobAlertRecipient.objects.filter(
                delivered_at__date=target_date,
                status=JobAlertRecipient.RecipientStatus.DELIVERED,
            ).count()
            actual_delivered = cr_delivered + ja_delivered

            cr_failed = CampaignRecipient.objects.filter(
                failed_at__date=target_date,
                status=CampaignRecipient.RecipientStatus.FAILED,
            ).count()
            ja_failed = JobAlertRecipient.objects.filter(
                failed_at__date=target_date,
                status=JobAlertRecipient.RecipientStatus.FAILED,
            ).count()
            actual_failed = cr_failed + ja_failed

            cr_queue = CampaignRecipient.objects.filter(
                models.Q(queued_at__date=target_date) | models.Q(campaign__created_at__date=target_date),
                status__in=[CampaignRecipient.RecipientStatus.QUEUED, CampaignRecipient.RecipientStatus.SENDING],
            ).count()
            ja_queue = JobAlertRecipient.objects.filter(
                models.Q(queued_at__date=target_date) | models.Q(campaign__created_at__date=target_date),
                status__in=[JobAlertRecipient.RecipientStatus.QUEUED, JobAlertRecipient.RecipientStatus.SENDING],
            ).count()
            actual_in_queue = cr_queue + ja_queue

            record.sent_count = actual_sent
            record.delivered_count = actual_delivered
            record.failed_count = actual_failed
            record.reserved_count = actual_in_queue
            record.save(update_fields=["sent_count", "delivered_count", "failed_count", "reserved_count", "updated_at"])

        logger.info(
            "Reconciled quota for date=%s: sent=%d, delivered=%d, failed=%d, in_queue=%d",
            target_date, actual_sent, actual_delivered, actual_failed, actual_in_queue
        )
        return record

    reconcile_today = reconcile_today_quota
