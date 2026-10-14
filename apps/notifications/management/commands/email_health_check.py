"""
Management command: email_health_check
Performs comprehensive diagnostic audit of SevaJobs email infrastructure,
Resend API configuration, worker/queue availability, daily quotas, and delivery metrics.

Usage:
  python manage.py email_health_check
  python manage.py email_health_check --check-provider-api
  python manage.py email_health_check --send-test-to admin@example.com
  python manage.py email_health_check --json
"""

from __future__ import annotations

import json
from typing import Any, Dict

from django.core.management.base import BaseCommand
from apps.notifications.health_service import EmailHealthService, mask_secret


class Command(BaseCommand):
    help = "Audit and verify SevaJobs email infrastructure, Resend configuration, and bulk quotas."

    def add_arguments(self, parser):
        parser.add_argument(
            "--check-provider-api",
            action="store_true",
            help="Perform read-only live API check against Resend (verifies key and domains).",
        )
        parser.add_argument(
            "--send-test-to",
            type=str,
            default="",
            help="Send a single safe diagnostic test email to the specified recipient address.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Output diagnostic results in JSON format.",
        )

    def handle(self, *args, **options):
        is_json = options.get("json", False)
        check_api = options.get("check_provider_api", False)
        test_recipient = options.get("send_test_to", "").strip()

        report = EmailHealthService.run_diagnostics(check_api=check_api)

        if test_recipient:
            test_res = EmailHealthService.send_diagnostic_test(test_recipient, actor_email="manage.py")
            report["test_send_result"] = test_res

        if is_json:
            self.stdout.write(json.dumps(report, indent=2))
            return

        self._render_text_report(report)

    def _render_text_report(self, r: Dict[str, Any]):
        out = self.stdout.write
        style = self.style

        out(style.SUCCESS("=" * 70))
        out(style.SUCCESS("       SEVAJOBS EMAIL INFRASTRUCTURE HEALTH CHECK REPORT"))
        out(style.SUCCESS("=" * 70))

        # Overall Status
        st = r["overall_status"]
        if st in ("HEALTHY", "DEV_CONSOLE_BACKEND"):
            status_badge = style.SUCCESS(f"  [OK] Overall Status: {st}")
        else:
            status_badge = style.WARNING(f"  [!] Overall Status: {st}")
        out(status_badge)
        out(f"  Timestamp: {r['timestamp']}")
        out(f"  Debug Mode: {r['environment']['debug']}")

        # 1. Configuration
        cfg = r["configuration"]
        out("\n" + style.MIGRATE_HEADING("1. DJANGO & PROVIDER CONFIGURATION:"))
        out(f"  Email Backend:              {cfg['email_backend']}")
        out(f"  Is Resend Backend:          {'YES' if cfg['is_resend_backend'] else 'NO (Custom/Dev)'}")
        out(f"  Resend API Key:             {cfg['resend_api_key_masked']}")
        out(f"  Resend Sender Email:        {cfg['resend_from_email']}")
        out(f"  Resend Sender Name:         {cfg['resend_from_name']}")
        out(f"  Sender Domain:              {cfg['sender_domain']}")
        out(f"  Resend Webhook Secret:      {cfg['resend_webhook_secret_masked']}")
        out(f"  Default From Email:         {cfg['default_from_email']}")
        out(f"  Frontend URL:               {cfg['frontend_url']}")

        # 2. Client Readiness
        pc = r["provider_client"]
        out("\n" + style.MIGRATE_HEADING("2. RESEND SDK / CLIENT STATUS:"))
        out(f"  Resend Package Installed:   {'YES' if pc['resend_package_installed'] else 'NO'}")
        out(f"  Resend Package Version:     {pc['resend_version']}")
        out(f"  Client SDK Ready:           {'READY' if pc['client_initialized'] else 'NOT INITIALIZED'}")
        if pc.get("initialization_error"):
            out(style.ERROR(f"  Init Error:                 {pc['initialization_error']}"))

        # 3. Queue & Worker Status
        qw = r["queue_worker"]
        out("\n" + style.MIGRATE_HEADING("3. ASYNC QUEUE & BACKGROUND WORKER:"))
        out(f"  Operating Mode:             {qw['mode']}")
        out(f"  Celery Always Eager:        {'YES (Dev inline execution)' if qw['celery_eager_mode'] else 'NO (Asynchronous)'}")
        out(f"  Broker Scheme:              {qw['broker_scheme']}")
        if qw.get("redis_reachable") is not None:
            out(f"  Redis Reachable:            {'YES' if qw['redis_reachable'] else 'NO (Connection Failed)'}")

        # 4. Quota Accounting
        qs = r["quota_status"]
        out("\n" + style.MIGRATE_HEADING("4. BULK EMAIL QUOTA (TODAY):"))
        out(f"  Date:                       {qs.get('date')}")
        out(f"  Sent Today:                 {qs.get('sent_today', 0)}")
        out(f"  In Queue / Reserved:        {qs.get('in_queue', 0)}")
        out(f"  Total Consumed:             {qs.get('total_consumed', 0)} / {qs.get('daily_limit', 100)}")
        out(f"  Remaining Bulk Quota:       {qs.get('remaining', 0)}")
        out(f"  Consumption Level:          {qs.get('consumption_percentage', 0)}% (Status: {qs.get('status', 'unknown').upper()})")
        out(f"  Delivered Today:            {qs.get('delivered_today', 0)}")
        out(f"  Failed Today:               {qs.get('failed_today', 0)}")

        # 5. Recent Activity & Suppressions
        ra = r["recent_activity"]
        out("\n" + style.MIGRATE_HEADING("5. ACTIVITY & SUPPRESSION LISTS:"))
        out(f"  Last Email Sent At:         {ra.get('last_sent_at') or 'None recorded today'}")
        out(f"  Total Suppressed Addresses: {ra.get('total_suppressed_recipients', 0)}")
        out(f"    - Hard Bounces:           {ra.get('permanent_bounces', 0)}")
        out(f"    - Spam Complaints:        {ra.get('spam_complaints', 0)}")
        out(f"    - Unsubscribes:           {ra.get('unsubscribed_users', 0)}")

        # 6. Live API Check
        if r.get("live_api_check"):
            lac = r["live_api_check"]
            out("\n" + style.MIGRATE_HEADING("6. LIVE RESEND API CONNECTIVITY:"))
            out(f"  Status:                     {lac.get('status').upper()}")
            if lac.get("status") == "connected":
                out(f"  Authenticated:              YES")
                out(f"  Sender Domain Verified:     {'YES' if lac.get('sender_domain_verified') else 'NO / UNVERIFIED'}")
                out(f"  Sender Domain Status:       {lac.get('matching_domain_status')}")
                domains = lac.get("domains_found", [])
                out(f"  Domains in Account:         {len(domains)}")
                for d in domains:
                    out(f"    - {d.get('name')}: {d.get('status')}")
            elif lac.get("status") == "skipped":
                out(f"  Skipped:                    {lac.get('reason')}")
            else:
                out(style.ERROR(f"  API Check Error:            {lac.get('error')}"))

        # 7. Test Send Result
        if r.get("test_send_result"):
            tsr = r["test_send_result"]
            out("\n" + style.MIGRATE_HEADING("7. SAFE DIAGNOSTIC TEST EMAIL SEND:"))
            out(f"  Status:                     {tsr.get('status').upper()}")
            out(f"  Recipient:                  {tsr.get('recipient')}")
            out(f"  Backend Used:               {tsr.get('backend_used')}")
            if tsr.get("provider_message_id"):
                out(f"  Provider Message ID:        {tsr.get('provider_message_id')}")
            if tsr.get("error"):
                out(style.ERROR(f"  Send Error:                 {tsr.get('error')}"))

        out("\n" + style.SUCCESS("=" * 70))
