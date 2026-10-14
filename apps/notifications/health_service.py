"""
SevaJobs Email Infrastructure Health & Diagnostic Service.
Audits configuration, provider integration readiness, background workers,
daily quota, suppression lists, and facilitates safe administrator test emails.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.utils import timezone

logger = logging.getLogger("apps.notifications")


def mask_secret(val: Optional[str]) -> str:
    """Safely mask secret strings (e.g. re_abc123... -> re_*** (length=24))."""
    if not val:
        return "[NOT SET]"
    val_str = str(val).strip()
    if len(val_str) <= 6:
        return "***"
    prefix = val_str[:3]
    return f"{prefix}*** (length={len(val_str)})"


class EmailHealthService:
    """
    Centralized health check service for SevaJobs email infrastructure.
    Can be invoked from management commands, admin dashboard views, or health monitors.
    """

    @classmethod
    def run_diagnostics(cls, check_api: bool = False) -> Dict[str, Any]:
        """
        Gathers complete diagnostic status across configuration, client SDK,
        queue worker, quota consumption, and delivery history.
        """
        report: Dict[str, Any] = {
            "timestamp": timezone.now().isoformat(),
            "environment": {
                "debug": getattr(settings, "DEBUG", False),
                "settings_module": getattr(settings, "SETTINGS_MODULE", ""),
            },
            "configuration": {},
            "provider_client": {},
            "queue_worker": {},
            "quota_status": {},
            "recent_activity": {},
            "live_api_check": None,
            "overall_status": "UNKNOWN",
        }

        # 1. Configuration Audit
        email_backend = getattr(settings, "EMAIL_BACKEND", "")
        resend_api_key = getattr(settings, "RESEND_API_KEY", "")
        resend_from_email = getattr(settings, "RESEND_FROM_EMAIL", "")
        resend_from_name = getattr(settings, "RESEND_FROM_NAME", "")
        resend_webhook_secret = getattr(settings, "RESEND_WEBHOOK_SECRET", "")
        default_from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "")
        server_email = getattr(settings, "SERVER_EMAIL", "")
        frontend_url = getattr(settings, "FRONTEND_URL", "")

        is_resend_backend = email_backend == "apps.notifications.backends.ResendEmailBackend"
        has_api_key = bool(resend_api_key)
        has_from_email = bool(resend_from_email)
        has_webhook_secret = bool(resend_webhook_secret)

        sender_domain = resend_from_email.split("@")[-1] if "@" in resend_from_email else ""

        report["configuration"] = {
            "email_backend": email_backend,
            "is_resend_backend": is_resend_backend,
            "resend_api_key_configured": has_api_key,
            "resend_api_key_masked": mask_secret(resend_api_key),
            "resend_from_email": resend_from_email or "[NOT SET]",
            "resend_from_name": resend_from_name or "[NOT SET]",
            "sender_domain": sender_domain or "[UNKNOWN]",
            "resend_webhook_secret_configured": has_webhook_secret,
            "resend_webhook_secret_masked": mask_secret(resend_webhook_secret),
            "default_from_email": default_from_email or "[NOT SET]",
            "server_email": server_email or "[NOT SET]",
            "frontend_url": frontend_url or "[NOT SET]",
        }

        # 2. Provider Client Initialization
        client_init_ok = False
        client_error = None
        client_version = "unknown"
        try:
            import resend
            if resend_api_key:
                resend.api_key = resend_api_key
            client_init_ok = True
            client_version = getattr(resend, "__version__", getattr(resend, "version", "unknown"))
        except Exception as e:
            client_error = str(e)
            client_version = "unavailable"

        report["provider_client"] = {
            "resend_package_installed": client_init_ok,
            "resend_version": client_version,
            "client_initialized": client_init_ok and has_api_key,
            "initialization_error": client_error,
        }

        # 3. Queue & Background Worker Check
        eager_mode = getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False)
        broker_url = getattr(settings, "CELERY_BROKER_URL", "")
        redis_reachable = None

        if "redis" in broker_url.lower():
            try:
                import redis
                client = redis.Redis.from_url(broker_url, socket_timeout=2)
                client.ping()
                redis_reachable = True
            except Exception:
                redis_reachable = False

        report["queue_worker"] = {
            "celery_eager_mode": eager_mode,
            "broker_url_configured": bool(broker_url),
            "broker_scheme": broker_url.split("://")[0] if "://" in broker_url else "unknown",
            "redis_reachable": redis_reachable,
            "mode": "Synchronous (Local Eager)" if eager_mode else ("Async Redis Worker (Online)" if redis_reachable else "Async Worker (Redis Unreachable)"),
        }

        # 4. Quota & Persistence Check
        from apps.notifications.quota_service import DailyEmailQuotaService
        from apps.notifications.models import (
            DailyEmailQuotaTracking,
            CampaignRecipient,
            JobAlertRecipient,
            EmailSuppression,
        )

        quota_status = DailyEmailQuotaService.get_quota_status()
        report["quota_status"] = quota_status

        # 5. Recent Activity & Suppression
        today_record = DailyEmailQuotaTracking.objects.filter(date=timezone.now().date()).first()
        last_sent_at = today_record.last_sent_at if today_record else None
        if not last_sent_at:
            last_cr = CampaignRecipient.objects.filter(status=CampaignRecipient.RecipientStatus.SENT).order_by("-sent_at").first()
            last_jar = JobAlertRecipient.objects.filter(status=JobAlertRecipient.RecipientStatus.SENT).order_by("-sent_at").first()
            if last_cr and last_jar:
                last_sent_at = max(filter(None, [last_cr.sent_at, last_jar.sent_at]))
            elif last_cr:
                last_sent_at = last_cr.sent_at
            elif last_jar:
                last_sent_at = last_jar.sent_at

        total_suppressed = EmailSuppression.objects.count()
        bounces_count = EmailSuppression.objects.filter(reason=EmailSuppression.Reason.BOUNCE).count()
        complaints_count = EmailSuppression.objects.filter(reason=EmailSuppression.Reason.COMPLAINT).count()
        unsubscribes_count = EmailSuppression.objects.filter(reason=EmailSuppression.Reason.UNSUBSCRIBE).count()

        report["recent_activity"] = {
            "last_sent_at": last_sent_at.isoformat() if last_sent_at else None,
            "total_suppressed_recipients": total_suppressed,
            "permanent_bounces": bounces_count,
            "spam_complaints": complaints_count,
            "unsubscribed_users": unsubscribes_count,
        }

        # 6. Optional Live Provider API Check
        if check_api:
            if not has_api_key:
                report["live_api_check"] = {
                    "status": "skipped",
                    "reason": "RESEND_API_KEY is not configured.",
                }
            else:
                try:
                    import resend
                    resend.api_key = resend_api_key
                    domains_resp = resend.Domains.list()
                    domains_list = []
                    if isinstance(domains_resp, dict):
                        raw_data = domains_resp.get("data", [])
                    elif hasattr(domains_resp, "data"):
                        raw_data = getattr(domains_resp, "data", [])
                    else:
                        raw_data = []

                    for d in raw_data:
                        d_name = d.get("name") if isinstance(d, dict) else getattr(d, "name", "")
                        d_status = d.get("status") if isinstance(d, dict) else getattr(d, "status", "")
                        domains_list.append({"name": d_name, "status": d_status})

                    matching_domain = next((d for d in domains_list if d["name"].lower() == sender_domain.lower()), None)
                    report["live_api_check"] = {
                        "status": "connected",
                        "authenticated": True,
                        "domains_found": domains_list,
                        "sender_domain_verified": bool(matching_domain and matching_domain["status"] == "verified"),
                        "matching_domain_status": matching_domain["status"] if matching_domain else "not_listed_in_resend",
                    }
                except Exception as api_err:
                    report["live_api_check"] = {
                        "status": "failed",
                        "error": str(api_err),
                    }

        # 7. Overall Health Status Evaluation
        if not is_resend_backend:
            overall = "DEV_CONSOLE_BACKEND" if "console" in email_backend else "CUSTOM_BACKEND"
        elif not has_api_key:
            overall = "CONFIG_INCOMPLETE_MISSING_API_KEY"
        elif not has_from_email:
            overall = "CONFIG_INCOMPLETE_MISSING_FROM_EMAIL"
        elif report["queue_worker"]["redis_reachable"] is False and not eager_mode:
            overall = "DEGRADED_WORKER_UNREACHABLE"
        elif quota_status.get("status") == "limit_reached":
            overall = "QUOTA_LIMIT_REACHED"
        else:
            overall = "HEALTHY"

        report["overall_status"] = overall
        return report

    @classmethod
    def send_diagnostic_test(cls, recipient: str, actor_email: str = "") -> Dict[str, Any]:
        """
        Sends a single safe diagnostic test email to the specified recipient.
        """
        clean_to = (recipient or "").strip().lower()
        if not clean_to or "@" not in clean_to or "." not in clean_to:
            return {
                "status": "error",
                "message": f"Invalid recipient email format: '{recipient}'",
            }

        email_backend = getattr(settings, "EMAIL_BACKEND", "")
        default_from = getattr(settings, "DEFAULT_FROM_EMAIL", "support@sevajobs.com")

        subject = "[SevaJobs Diagnostic] Safe Email Infrastructure Test"
        text_body = (
            f"This is an automated diagnostic test from SevaJobs Email Infrastructure.\n\n"
            f"Timestamp: {timezone.now().isoformat()}\n"
            f"Backend: {email_backend}\n"
            f"Recipient: {clean_to}\n"
            f"Initiated by: {actor_email or 'Administrator'}\n"
            f"Platform: SevaJobs Recruitment\n"
        )
        html_body = f"""
        <div style="font-family: sans-serif; padding: 20px; color: #334155; max-width: 600px; margin: 0 auto; border: 1px solid #e2e8f0; border-radius: 8px;">
            <h2 style="color: #4f46e5; margin-bottom: 12px;">SevaJobs Email Infrastructure Diagnostic</h2>
            <p style="font-size: 14px; line-height: 1.5; color: #475569;">
                This is a safe diagnostic test email dispatched by an authorized administrator to verify end-to-end provider connectivity and template rendering.
            </p>
            <table style="border-collapse: collapse; width: 100%; margin-top: 16px; font-size: 13px;">
                <tr style="border-bottom: 1px solid #f1f5f9;"><td style="padding: 8px 4px; font-weight: bold; width: 35%;">Dispatched At:</td><td>{timezone.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</td></tr>
                <tr style="border-bottom: 1px solid #f1f5f9;"><td style="padding: 8px 4px; font-weight: bold;">Configured Backend:</td><td><code>{email_backend}</code></td></tr>
                <tr style="border-bottom: 1px solid #f1f5f9;"><td style="padding: 8px 4px; font-weight: bold;">Recipient:</td><td>{clean_to}</td></tr>
                <tr style="border-bottom: 1px solid #f1f5f9;"><td style="padding: 8px 4px; font-weight: bold;">Sender Identity:</td><td>{default_from}</td></tr>
            </table>
            <p style="margin-top: 24px; font-size: 12px; color: #94a3b8;">
                SevaJobs &bull; Education &bull; Healthcare &bull; Social Work
            </p>
        </div>
        """

        try:
            connection = get_connection(fail_silently=False)
            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=default_from,
                to=[clean_to],
                headers={"X-Diagnostic-Test": "True"},
                connection=connection,
            )
            msg.attach_alternative(html_body, "text/html")
            sent_count = msg.send(fail_silently=False)

            provider_msg_id = getattr(msg, "provider_message_id", "") or (
                msg.extra_headers.get("provider_message_id", "")
                if hasattr(msg, "extra_headers") and msg.extra_headers
                else ""
            )

            return {
                "status": "sent" if sent_count > 0 else "not_sent",
                "recipient": clean_to,
                "backend_used": email_backend,
                "provider_message_id": provider_msg_id or "local_dispatched",
                "dispatched_at": timezone.now().isoformat(),
            }
        except Exception as e:
            logger.exception("Diagnostic test email send failed: %s", e)
            return {
                "status": "failed",
                "error": str(e),
                "backend_used": email_backend,
            }
