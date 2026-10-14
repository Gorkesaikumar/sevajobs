"""
SevaJobs — Database-Backed Job Discovery & Search Service.

Unifies Recruiter Jobs (`Job`) and Staff Jobs (`StaffJob`) into a single,
production-ready, high-performance query pipeline supporting:
  - Subject discovery & normalization
  - City discovery & alias resolution
  - Strict State-level discovery (without city conflation)
  - Teaching Level / Grade filtering
  - Text search, experience, salary, work mode, and sorting
  - Automatic SEO metadata, breadcrumbs, and canonical URL generation
"""

from __future__ import annotations
from typing import Optional, Dict, Any, List, Tuple
from django.db.models import Q, QuerySet
from django.utils import timezone
from django.core.paginator import Paginator, Page
from django.urls import reverse
from django.utils.http import urlencode

from apps.jobs.models import Job, StaffJob
from apps.jobs.navigation import (
    SUBJECT_CATALOG,
    CITY_CATALOG,
    STATE_CATALOG,
    LEVEL_CATALOG,
    resolve_subject,
    resolve_city,
    resolve_state,
    resolve_level,
    resolve_location,
    get_seo_navigation,
)
from apps.jobs.autocomplete import normalize_search_query


class JobDiscoveryService:
    """Authoritative query and discovery service for public SevaJobs vacancies."""

    @staticmethod
    def get_public_recruiter_queryset() -> QuerySet[Job]:
        """
        Returns active, admin-approved public recruiter vacancies.
        Excludes draft, pending, rejected, paused, closed, and expired statuses.
        Applies select_related for optimal database performance.
        """
        return (
            Job.objects.filter(
                status=Job.Status.ACTIVE,
                approval_status=Job.ApprovalStatus.APPROVED,
                is_active=True,
            )
            .select_related("company", "category")
        )

    @staticmethod
    def get_public_staff_queryset() -> QuerySet[StaffJob]:
        """
        Returns active public staff-posted vacancies.
        """
        return (
            StaffJob.objects.filter(
                status=StaffJob.Status.ACTIVE,
                is_active=True,
            )
            .select_related("created_by")
        )

    @classmethod
    def search_jobs(
        cls,
        *,
        subject_slug: Optional[str] = None,
        city_slug: Optional[str] = None,
        state_slug: Optional[str] = None,
        location_slug: Optional[str] = None,
        grade: Optional[str] = None,
        q: Optional[str] = None,
        location_query: Optional[str] = None,
        experience: Optional[str] = None,
        job_types: Optional[List[str]] = None,
        experience_levels: Optional[List[str]] = None,
        is_remote: Optional[bool] = None,
        salary_min: Optional[int] = None,
        salary_max: Optional[int] = None,
        category_slug: Optional[str] = None,
        sort: str = "-published_at",
        page: int = 1,
        page_size: int = 12,
        request=None,
    ) -> Dict[str, Any]:
        """
        Main query entrypoint. Resolves validated criteria, applies database-level
        filters to both Job and StaffJob, sorts, paginates, and compiles SEO metadata.
        """
        rqs = cls.get_public_recruiter_queryset()
        sqs = cls.get_public_staff_queryset()

        active_subject = None
        active_city = None
        active_state = None
        active_level = None
        location_info = None

        # 1. Resolve Location Slug if provided
        if location_slug:
            location_info = resolve_location(location_slug)
            if location_info:
                if location_info["type"] == "city":
                    active_city = location_info["data"]
                elif location_info["type"] == "state":
                    active_state = location_info["data"]

        # 2. Explicit City / State overrides if supplied
        if city_slug:
            active_city = resolve_city(city_slug)
        if state_slug:
            active_state = resolve_state(state_slug)

        # 3. Resolve Subject Slug
        if subject_slug:
            active_subject = resolve_subject(subject_slug)

        # 4. Resolve Grade / Level
        if grade:
            active_level = resolve_level(grade)

        # --------------------------------------------------------------------
        # Database Filtering: Subject
        # --------------------------------------------------------------------
        if active_subject:
            keywords = active_subject.get("title_keywords", [active_subject["subject"]])
            subj_term = active_subject["subject"]

            # Recruiter Job query
            q_subj_r = Q()
            for kw in keywords:
                q_subj_r |= Q(title__icontains=kw)
            q_subj_r |= Q(metadata__subject__iexact=subj_term)
            q_subj_r |= Q(metadata__subject_specialization__icontains=subj_term)
            for alias in active_subject.get("aliases", []):
                q_subj_r |= Q(metadata__subject__iexact=alias)
            rqs = rqs.filter(q_subj_r)

            # Staff Job query
            q_subj_s = Q()
            for kw in keywords:
                q_subj_s |= Q(designation__icontains=kw)
            q_subj_s |= Q(qualification__icontains=subj_term)
            for alias in active_subject.get("aliases", []):
                q_subj_s |= Q(qualification__icontains=alias)
            sqs = sqs.filter(q_subj_s)

        # --------------------------------------------------------------------
        # Database Filtering: City (including Manipal)
        # --------------------------------------------------------------------
        if active_city:
            canonical_city = active_city["canonical_name"]
            aliases = active_city.get("aliases", [canonical_city.lower()])

            q_city_r = Q()
            q_city_s = Q()

            q_city_r = Q(city__iexact=canonical_city)
            q_city_r |= (Q(city="") | Q(city__isnull=True)) & (
                Q(company__city__iexact=canonical_city) | Q(location__icontains=canonical_city)
            )
            q_city_s = Q(city__iexact=canonical_city)

            for alias in aliases:
                q_city_r |= Q(city__iexact=alias)
                q_city_r |= (Q(city="") | Q(city__isnull=True)) & (
                    Q(company__city__iexact=alias) | Q(location__icontains=alias)
                )
                q_city_s |= Q(city__iexact=alias) | Q(job_location__icontains=alias)

            rqs = rqs.filter(q_city_r)
            sqs = sqs.filter(q_city_s)

        # --------------------------------------------------------------------
        # Database Filtering: State (STRICT state-level filtering)
        # --------------------------------------------------------------------
        if active_state:
            canonical_state = active_state["canonical_name"]
            aliases = active_state.get("aliases", [canonical_state.lower()])

            q_state_r = Q(state__iexact=canonical_state)
            q_state_r |= (Q(state="") | Q(state__isnull=True)) & (
                Q(company__state__iexact=canonical_state) | Q(location__icontains=canonical_state)
            )
            q_state_s = Q(state__iexact=canonical_state)

            for alias in aliases:
                q_state_r |= Q(state__iexact=alias)
                q_state_r |= (Q(state="") | Q(state__isnull=True)) & (
                    Q(company__state__iexact=alias) | Q(location__icontains=alias)
                )
                q_state_s |= Q(state__iexact=alias) | Q(job_location__icontains=alias)

            rqs = rqs.filter(q_state_r)
            sqs = sqs.filter(q_state_s)

        # --------------------------------------------------------------------
        # Database Filtering: Grade / Level
        # --------------------------------------------------------------------
        if active_level:
            level_slug = active_level["slug"]
            if level_slug == "primary":
                q_lvl_r = (
                    Q(title__icontains="Primary") | Q(title__icontains="PRT") |
                    Q(metadata__grade_class__icontains="Primary") |
                    Q(metadata__category_label__icontains="Primary") |
                    Q(metadata__category_label__icontains="PRT")
                )
                q_lvl_s = Q(designation__icontains="Primary") | Q(designation__icontains="PRT")
            elif level_slug == "middle-school":
                q_lvl_r = (
                    Q(title__icontains="Middle") | Q(title__icontains="TGT") |
                    Q(metadata__grade_class__icontains="Middle") |
                    Q(metadata__category_label__icontains="Middle") |
                    Q(metadata__category_label__icontains="TGT")
                )
                q_lvl_s = Q(designation__icontains="Middle") | Q(designation__icontains="TGT")
            elif level_slug == "secondary":
                q_lvl_r = (
                    (Q(title__icontains="Secondary") & ~Q(title__icontains="Senior Secondary")) |
                    Q(title__icontains="10th") |
                    Q(metadata__grade_class__icontains="10th") |
                    Q(metadata__category_label__icontains="high school")
                )
                q_lvl_s = (
                    Q(designation__icontains="Secondary") & ~Q(designation__icontains="Senior Secondary")
                ) | Q(designation__icontains="10th")
            elif level_slug == "senior-secondary":
                q_lvl_r = (
                    Q(title__icontains="Senior Secondary") | Q(title__icontains="PGT") |
                    Q(title__icontains="Lecturer") | Q(title__icontains="12th") |
                    Q(metadata__grade_class__icontains="12th") |
                    Q(metadata__grade_class__icontains="Senior Secondary")
                )
                q_lvl_s = (
                    Q(designation__icontains="Senior Secondary") |
                    Q(designation__icontains="PGT") |
                    Q(designation__icontains="Lecturer")
                )
            elif level_slug == "pre-primary":
                q_lvl_r = (
                    Q(title__icontains="Pre-Primary") | Q(title__icontains="Pre Primary") |
                    Q(title__icontains="KG") | Q(title__icontains="Nursery") |
                    Q(title__icontains="Kindergarten") | Q(title__icontains="Montessori")
                )
                q_lvl_s = (
                    Q(designation__icontains="Pre-Primary") | Q(designation__icontains="Pre Primary") |
                    Q(designation__icontains="KG") | Q(designation__icontains="Nursery")
                )
            elif level_slug == "neet-jee-faculty":
                q_lvl_r = (
                    Q(title__icontains="NEET") | Q(title__icontains="JEE") |
                    Q(title__icontains="CET") | Q(title__icontains="IIT") |
                    Q(title__icontains="Faculty") | Q(title__icontains="Professor")
                )
                q_lvl_s = (
                    Q(designation__icontains="NEET") | Q(designation__icontains="JEE") |
                    Q(designation__icontains="CET") | Q(designation__icontains="Faculty")
                )
            else:  # all-teaching
                q_lvl_r = (
                    Q(segment="teaching") | Q(category__name="Teaching") |
                    Q(title__icontains="Teacher") | Q(title__icontains="Lecturer") |
                    Q(title__icontains="Professor") | Q(title__icontains="Faculty")
                )
                q_lvl_s = (
                    Q(designation__icontains="Teacher") | Q(designation__icontains="Lecturer") |
                    Q(designation__icontains="Faculty")
                )

            rqs = rqs.filter(q_lvl_r)
            sqs = sqs.filter(q_lvl_s)

        # --------------------------------------------------------------------
        # Database Filtering: Search Query (q)
        # --------------------------------------------------------------------
        if q:
            clean_q = q.strip()
            normalized = normalize_search_query(clean_q)
            q_filter_r = (
                Q(title__icontains=clean_q) | Q(description__icontains=clean_q) |
                Q(location__icontains=clean_q) | Q(state__icontains=clean_q) |
                Q(district__icontains=clean_q) | Q(city__icontains=clean_q) |
                Q(category__name__icontains=clean_q) |
                Q(preferred_qualifications__name__icontains=clean_q)
            )
            q_filter_s = (
                Q(designation__icontains=clean_q) | Q(organization_name__icontains=clean_q) |
                Q(job_location__icontains=clean_q) | Q(state__icontains=clean_q) |
                Q(district__icontains=clean_q) | Q(city__icontains=clean_q) |
                Q(qualification__icontains=clean_q)
            )
            if normalized and normalized.lower() != clean_q.lower():
                q_filter_r |= (
                    Q(title__icontains=normalized) | Q(description__icontains=normalized) |
                    Q(location__icontains=normalized)
                )
                q_filter_s |= (
                    Q(designation__icontains=normalized) |
                    Q(organization_name__icontains=normalized) |
                    Q(job_location__icontains=normalized)
                )
            rqs = rqs.filter(q_filter_r)
            sqs = sqs.filter(q_filter_s)

        # --------------------------------------------------------------------
        # Database Filtering: Location Query string (from search bar)
        # --------------------------------------------------------------------
        if location_query:
            loc = location_query.strip()
            rqs = rqs.filter(
                Q(location__icontains=loc) | Q(city__icontains=loc) |
                Q(district__icontains=loc) | Q(state__icontains=loc)
            )
            sqs = sqs.filter(
                Q(job_location__icontains=loc) | Q(city__icontains=loc) |
                Q(district__icontains=loc) | Q(state__icontains=loc)
            )

        # --------------------------------------------------------------------
        # Database Filtering: Experience
        # --------------------------------------------------------------------
        if experience:
            exp_str = experience.strip()
            if exp_str.isdigit():
                years = int(exp_str)
                rqs = rqs.filter(
                    Q(min_experience_years__lte=years) &
                    (Q(max_experience_years__isnull=True) | Q(max_experience_years__gte=years))
                )
            elif exp_str.lower() in ["fresher", "0"]:
                rqs = rqs.filter(Q(min_experience_years=0) | Q(experience_level="FRESHER"))
            else:
                rqs = rqs.filter(experience_level__iexact=exp_str)

        if experience_levels:
            rqs = rqs.filter(experience_level__in=experience_levels)

        # --------------------------------------------------------------------
        # Database Filtering: Job Type, Remote, Salary, Category
        # --------------------------------------------------------------------
        has_recruiter_only_filters = False
        if job_types:
            rqs = rqs.filter(job_type__in=job_types)
            has_recruiter_only_filters = True

        if is_remote is not None and is_remote:
            rqs = rqs.filter(is_remote=True)
            has_recruiter_only_filters = True

        if category_slug:
            rqs = rqs.filter(category__slug=category_slug)
            has_recruiter_only_filters = True

        if salary_min is not None:
            rqs = rqs.filter(salary_min__gte=salary_min)
            sqs = sqs.filter(offered_salary__gte=salary_min)

        if salary_max is not None:
            rqs = rqs.filter(salary_max__lte=salary_max)
            sqs = sqs.filter(offered_salary__lte=salary_max)

        # --------------------------------------------------------------------
        # Database-level Sorting
        # --------------------------------------------------------------------
        if sort == "published_at":
            rqs = rqs.order_by("published_at", "created_at")
            sqs = sqs.order_by("published_at", "created_at")
        elif sort == "salary_min":
            rqs = rqs.order_by("salary_min", "-published_at", "-created_at")
            sqs = sqs.order_by("offered_salary", "-published_at", "-created_at")
        elif sort == "-salary_min":
            rqs = rqs.order_by("-salary_min", "-published_at", "-created_at")
            sqs = sqs.order_by("-offered_salary", "-published_at", "-created_at")
        elif sort == "-applications_count":
            rqs = rqs.order_by("-applications_count", "-published_at", "-created_at")
            sqs = sqs.order_by("-published_at", "-created_at")
        else:  # default Newest First ("-published_at") with featured first
            rqs = rqs.order_by("-is_featured", "-published_at", "-created_at")
            sqs = sqs.order_by("-published_at", "-created_at")

        # --------------------------------------------------------------------
        # Merging and In-memory Pagination
        # --------------------------------------------------------------------
        recruiter_jobs = list(rqs)
        staff_jobs = [] if has_recruiter_only_filters else list(sqs)
        combined_jobs = recruiter_jobs + staff_jobs

        # In-memory tie-breaker to ensure featured & newest precedence
        if sort == "published_at":
            combined_jobs.sort(key=lambda j: j.published_at or j.created_at)
        elif sort == "salary_min":
            combined_jobs.sort(key=lambda j: getattr(j, "salary_min", None) or getattr(j, "offered_salary", 0))
        elif sort == "-salary_min":
            combined_jobs.sort(key=lambda j: getattr(j, "salary_min", None) or getattr(j, "offered_salary", 0), reverse=True)
        else:
            combined_jobs.sort(key=lambda j: (getattr(j, "is_featured", False), j.published_at or j.created_at), reverse=True)

        paginator = Paginator(combined_jobs, page_size)
        page_obj = paginator.get_page(page)

        # --------------------------------------------------------------------
        # Compile SEO Metadata & Titles
        # --------------------------------------------------------------------
        seo_meta = cls._compile_seo_metadata(
            active_subject=active_subject,
            active_city=active_city,
            active_state=active_state,
            active_level=active_level,
            search_query=q,
            search_location=location_query,
            total_count=paginator.count,
            request=request,
        )

        # Build recovery suggestions if zero results
        recovery_suggestions = []
        if paginator.count == 0:
            if active_subject:
                recovery_suggestions.append(f"Try exploring related subjects like Mathematics, Physics, or Computer Science.")
            if active_state:
                recovery_suggestions.append(f"Currently there are no vacancies directly matching state '{active_state['name']}'. Check nearby metropolitan areas.")
            if active_city:
                recovery_suggestions.append(f"No vacancies currently in '{active_city['name']}'. Try searching broader state vacancies or remote teaching jobs.")
            if active_level:
                recovery_suggestions.append(f"Explore all teaching grades or senior secondary faculty openings.")
            if q:
                recovery_suggestions.append(f"Try searching for broader terms like 'Teacher', 'PGT', or 'TGT'.")
            if not recovery_suggestions:
                recovery_suggestions.append("Try resetting your search filters to browse all teaching jobs.")

        return {
            "page_obj": page_obj,
            "jobs": page_obj,
            "total_results": paginator.count,
            "seo_meta": seo_meta,
            "recovery_suggestions": recovery_suggestions,
            "active_subject": active_subject,
            "active_city": active_city,
            "active_state": active_state,
            "active_level": active_level,
            "search_query": q,
            "search_location": location_query,
            "selected_experience": experience,
            "navigation": get_seo_navigation(),
        }

    @staticmethod
    def _compile_seo_metadata(
        *,
        active_subject: Optional[Dict[str, Any]],
        active_city: Optional[Dict[str, Any]],
        active_state: Optional[Dict[str, Any]],
        active_level: Optional[Dict[str, Any]],
        search_query: Optional[str],
        search_location: Optional[str],
        total_count: int,
        request=None,
    ) -> Dict[str, Any]:
        """Generates dynamic page title, meta description, H1 heading, breadcrumbs, and canonical URL."""
        site_name = "SevaJobs"
        base_url = "https://sevajobs.com"
        if request:
            base_url = f"{request.scheme}://{request.get_host()}"

        breadcrumbs = [{"label": "Find Jobs", "url": reverse("core:job-search")}]
        related_links = []
        canonical_path = reverse("core:job-search")

        if active_subject:
            h1 = f"{active_subject['name']} in India"
            title = f"{active_subject['name']} in India | {site_name}"
            desc = (
                f"Explore verified {active_subject['short_name']} Teacher vacancies across India's top schools and colleges. "
                f"Apply directly with disclosed salary packages on SevaJobs."
            )
            canonical_path = reverse("core:job-subject", kwargs={"subject_slug": active_subject["slug"]})
            breadcrumbs.append({"label": active_subject["name"], "url": canonical_path})

            # Related subjects
            for slug, item in SUBJECT_CATALOG.items():
                if slug != active_subject["slug"]:
                    related_links.append({
                        "label": item["name"],
                        "url": reverse("core:job-subject", kwargs={"subject_slug": slug}),
                    })

        elif active_state:
            state_name = active_state["canonical_name"]
            h1 = f"Teaching Jobs in {state_name}"
            title = f"Teaching Jobs in {state_name} | {site_name}"
            desc = (
                f"Browse verified school, college, and coaching teaching jobs in {state_name}. "
                f"Find primary, secondary, and lecturer vacancies on SevaJobs."
            )
            canonical_path = reverse("core:job-location", kwargs={"location_slug": active_state["slug"]})
            breadcrumbs.append({"label": f"Jobs in {state_name}", "url": canonical_path})

            # Related states
            for slug, item in STATE_CATALOG.items():
                if slug != active_state["slug"]:
                    related_links.append({
                        "label": f"Jobs in {item['name']}",
                        "url": reverse("core:job-location", kwargs={"location_slug": slug}),
                    })

        elif active_city:
            city_name = active_city["canonical_name"]
            is_locality = active_city.get("is_locality", False)
            h1 = f"Teaching Jobs in {city_name}"
            title = f"Teaching Jobs in {city_name} | {site_name}"
            desc = (
                f"Discover verified teacher vacancies in {city_name}{', ' + active_city.get('state', '') if not is_locality else ''}. "
                f"Explore school, junior college, and competitive coaching jobs."
            )
            canonical_path = reverse("core:job-location", kwargs={"location_slug": active_city["slug"]})
            breadcrumbs.append({"label": f"Jobs in {city_name}", "url": canonical_path})

            # Related cities
            for slug, item in CITY_CATALOG.items():
                if slug != active_city["slug"]:
                    related_links.append({
                        "label": f"Jobs in {item['name']}",
                        "url": reverse("core:job-location", kwargs={"location_slug": slug}),
                    })

        elif active_level:
            level_name = active_level["name"]
            h1 = level_name
            title = f"{level_name} | {site_name}"
            desc = (
                f"Search open {active_level['short_name']} teaching positions across verified schools and institutes in India. "
                f"Apply today on SevaJobs."
            )
            if active_level["grade_param"]:
                canonical_path = f"{reverse('core:current-vacancies')}?{urlencode({'grade': active_level['grade_param']})}"
            else:
                canonical_path = reverse("core:current-vacancies")
            breadcrumbs.append({"label": level_name, "url": canonical_path})

            # Related levels
            for slug, item in LEVEL_CATALOG.items():
                if slug != active_level["slug"]:
                    if item["grade_param"]:
                        rel_url = f"{reverse('core:current-vacancies')}?{urlencode({'grade': item['grade_param']})}"
                    else:
                        rel_url = reverse("core:current-vacancies")
                    related_links.append({"label": item["name"], "url": rel_url})

        elif search_query or search_location:
            parts = []
            if search_query:
                parts.append(f"{search_query.title()} Jobs")
            if search_location:
                parts.append(f"in {search_location.title()}")
            combined_label = " ".join(parts) or "Job Search"
            h1 = f"Teaching {combined_label}"
            title = f"{h1} | {site_name}"
            desc = f"Search teaching jobs matching '{search_query or search_location}' across schools and colleges in India."
            breadcrumbs.append({"label": h1})
        else:
            h1 = "All Current Teaching Vacancies"
            title = f"Teaching Jobs in India | {site_name}"
            desc = "Find passion-driven teaching jobs across India's leading schools, colleges, and coaching institutes on SevaJobs."
            canonical_path = reverse("core:current-vacancies")

        canonical_url = f"{base_url}{canonical_path}"

        return {
            "title": title,
            "meta_description": desc,
            "h1": h1,
            "canonical_url": canonical_url,
            "breadcrumbs": breadcrumbs,
            "related_links": related_links[:8],
        }
