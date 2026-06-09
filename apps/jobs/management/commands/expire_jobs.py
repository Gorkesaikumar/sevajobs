"""
Expire active jobs whose application deadline has passed.

Run on a schedule (cron / Celery beat):

    python manage.py expire_jobs
"""

from django.core.management.base import BaseCommand

from apps.jobs.services import JobService


class Command(BaseCommand):
    help = "Mark active jobs past their deadline as EXPIRED."

    def handle(self, *args, **options) -> None:
        count = JobService().expire_due_jobs()
        self.stdout.write(self.style.SUCCESS(f"Expired {count} job(s)."))
