"""
SevaJobs — Canonical SEO XML Sitemaps.

Exposes only useful, authoritative, indexable URLs to search engine crawlers:
  - Canonical Subject listing pages (/jobs/india/<subject_slug>/)
  - Canonical City listing pages (/jobs/<city_slug>/)
  - Canonical State listing pages (/jobs/<state_slug>/)
  - Current vacancies index (/current-vacancies/)
  - Active, approved Job detail pages
"""

from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from apps.jobs.navigation import SUBJECT_CATALOG, CITY_CATALOG, STATE_CATALOG
from apps.jobs.models import Job


class JobSubjectSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.9

    def items(self):
        return list(SUBJECT_CATALOG.keys())

    def location(self, item):
        return reverse("core:job-subject", kwargs={"subject_slug": item})


class JobCitySitemap(Sitemap):
    changefreq = "daily"
    priority = 0.9

    def items(self):
        return list(CITY_CATALOG.keys())

    def location(self, item):
        return reverse("core:job-location", kwargs={"location_slug": item})


class JobStateSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.85

    def items(self):
        # Exclude Delhi if already in city sitemap to avoid duplicate canonicals
        return [slug for slug in STATE_CATALOG.keys() if slug != "delhi"]

    def location(self, item):
        return reverse("core:job-location", kwargs={"location_slug": item})


class JobStaticSitemap(Sitemap):
    changefreq = "hourly"
    priority = 1.0

    def items(self):
        return ["core:current-vacancies", "core:job-search"]

    def location(self, item):
        return reverse(item)


class JobDetailSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.7

    def items(self):
        return (
            Job.objects.filter(
                status=Job.Status.ACTIVE,
                approval_status=Job.ApprovalStatus.APPROVED,
                is_active=True,
            )
            .order_by("-published_at", "-created_at")
        )

    def lastmod(self, obj):
        return obj.published_at or obj.updated_at or obj.created_at

    def location(self, obj):
        return reverse("core:job-detail", kwargs={"slug": obj.slug})
