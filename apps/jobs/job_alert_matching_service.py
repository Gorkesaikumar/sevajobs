"""
SevaJobs — Centralized Candidate-to-Job Matching Engine (CandidateJobAlertMatchingService).

Evaluates candidate professional profile data against active, approved, published vacancies
in the SevaJobs database (both recruiter Job postings and direct StaffJob postings).
Enforces deterministic compatibility scoring, location normalization, subject and title
compatibility, experience thresholds, and public vacancy availability rules.
"""

from __future__ import annotations

import logging
import re
from typing import Sequence, Dict, Any, List, Optional, Tuple
from django.db.models import Q
from django.utils import timezone
from django.urls import reverse
from django.conf import settings

from apps.accounts.models import User, JobSeekerProfile
from apps.jobs.models import Job, StaffJob, InstitutionRequirement, RequirementCandidateMatch
from apps.applications.models import JobApplication
from apps.recruiters.models import RecruiterProfile, Company

logger = logging.getLogger("apps.jobs")


# Standard subject alias mappings for normalization
SUBJECT_SYNONYMS = {
    "math": "mathematics",
    "maths": "mathematics",
    "maths teacher": "mathematics",
    "cs": "computer science",
    "comp science": "computer science",
    "comp sci": "computer science",
    "it": "information technology",
    "eng": "english",
    "soc": "social studies",
    "social": "social studies",
    "sci": "science",
    "bio": "biology",
    "chem": "chemistry",
    "phy": "physics",
    "phys": "physics",
    "econ": "economics",
    "commerce": "commerce",
    "pe": "physical education",
    "pet": "physical education",
}

SUBJECT_GROUPS: Dict[str, set[str]] = {
    "english": {"english", "eng"},
    "mathematics": {"math", "maths", "mathematics"},
    "physics": {"physics", "phy"},
    "chemistry": {"chemistry", "chem"},
    "biology": {"biology", "bio"},
    "computer_science": {"computer", "cs", "it"},
    "economics": {"economics", "econ"},
    "history": {"history"},
    "geography": {"geography"},
    "music": {"music"},
    "art": {"art"},
    "telugu": {"telugu"},
    "hindi": {"hindi"},
    "physical_education": {"physical", "pe", "pet"},
}



def _clean_token(text: str) -> str:
    """Normalize text by lowercasing and stripping punctuation."""
    if not text:
        return ""
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    return " ".join(cleaned.split())


class CandidateJobAlertMatchingService:
    """
    Evaluates real candidates against real published vacancies (Job and StaffJob).
    Produces deterministic match scores, compatibility explanations, and structured vacancy bundles.
    """

    @classmethod
    def get_public_vacancies(cls, specific_job_ids: Sequence[str] | None = None) -> List[Dict[str, Any]]:
        """
        Query authoritative, currently active and approved vacancies from both Job and StaffJob tables.
        Guarantees that unapproved, expired, or closed jobs are excluded.
        """
        today = timezone.now().date()
        site_root = getattr(settings, "FRONTEND_URL", "https://sevajobs.in").rstrip("/")

        vacancies: List[Dict[str, Any]] = []

        # 1. Recruiter Jobs
        job_qs = Job.objects.filter(
            is_active=True,
            status=Job.Status.ACTIVE,
            approval_status=Job.ApprovalStatus.APPROVED,
        ).filter(
            Q(deadline__isnull=True) | Q(deadline__gte=today)
        ).select_related("company", "category", "minimum_qualification").prefetch_related("preferred_qualifications")

        if specific_job_ids:
            job_qs = job_qs.filter(id__in=specific_job_ids)

        for j in job_qs:
            if not j.slug:
                from django.utils.text import slugify
                import uuid
                base = slugify(f"{j.title}-{j.company.name if j.company else 'job'}") or "job"
                j.slug = f"{base[:260]}-{str(uuid.uuid4())[:8]}"
                j.save(update_fields=["slug"])
            try:
                path = reverse("core:job-detail", kwargs={"slug": j.slug})
            except Exception:
                path = f"/jobs/{j.slug}/"
            vacancies.append({
                "type": "recruiter",
                "id": str(j.id),
                "title": j.title,
                "organization": j.company.name if j.company else "Educational Institution",
                "location": j.location or j.city or j.state or "India",
                "city": j.city or "",
                "state": j.state or "",
                "min_exp": j.min_experience_years,
                "max_exp": j.max_experience_years,
                "salary_min": j.salary_min,
                "salary_max": j.salary_max,
                "salary_display": f"₹{j.salary_min:,} - ₹{j.salary_max:,}" if (j.salary_min and j.salary_max) else (f"₹{j.salary_min:,}+" if j.salary_min else "Disclosed upon interview"),
                "url": f"{site_root}{path}",
                "job_type": j.get_job_type_display(),
                "category": j.category.name if j.category else "Teaching",
                "model_obj": j,
            })

        # 2. Staff Jobs
        staff_qs = StaffJob.objects.filter(
            is_active=True,
            status=StaffJob.Status.ACTIVE,
        )

        if specific_job_ids:
            staff_qs = staff_qs.filter(id__in=specific_job_ids)

        for sj in staff_qs:
            path = reverse("core:staff-job-detail", kwargs={"pk": sj.pk})
            vacancies.append({
                "type": "staff",
                "id": str(sj.id),
                "title": sj.designation,
                "organization": sj.organization_name or "Partner School",
                "location": sj.display_location or sj.job_location or sj.city or "India",
                "city": sj.city or "",
                "state": sj.state or "",
                "min_exp": 0,
                "max_exp": None,
                "salary_min": sj.offered_salary,
                "salary_max": sj.offered_salary,
                "salary_display": f"₹{sj.offered_salary:,}" if sj.offered_salary else "Competitive",
                "url": f"{site_root}{path}",
                "job_type": "Full Time",
                "category": "Teaching",
                "model_obj": sj,
            })

        return vacancies

    @classmethod
    def normalize_subject(cls, subject_text: str) -> str:
        """Map common abbreviations and variations to canonical subject terms."""
        clean = _clean_token(subject_text)
        return SUBJECT_SYNONYMS.get(clean, clean)

    @classmethod
    def calculate_compatibility(
        cls,
        candidate_data: Dict[str, Any],
        vacancy: Dict[str, Any]
    ) -> Tuple[int, List[str]]:
        """
        Calculates compatibility score (0 to 100) and structured match reasons between a candidate and a vacancy.
        Weighting:
          - Subject Match: 35 points
          - Profession / Job Title Match: 30 points
          - Location Compatibility: 20 points
          - Experience Compatibility: 15 points
        Bonus/Penalty:
          - Salary misalignment penalty: up to -10 if expected salary greatly exceeds maximum offered.
        """
        score = 0
        reasons = []

        cand_subj = cls.normalize_subject(candidate_data.get("subject", ""))
        cand_desig = _clean_token(candidate_data.get("designation", ""))
        cand_headline = _clean_token(candidate_data.get("headline", ""))
        cand_city = _clean_token(candidate_data.get("city", ""))
        cand_state = _clean_token(candidate_data.get("state", ""))
        cand_pref_loc = _clean_token(candidate_data.get("preferred_location", ""))
        cand_curr_loc = _clean_token(candidate_data.get("current_location", ""))
        cand_exp = candidate_data.get("experience_years", 0) or 0
        cand_expected_sal = candidate_data.get("expected_salary") or candidate_data.get("current_salary")

        vac_title = _clean_token(vacancy.get("title", ""))
        vac_loc = _clean_token(vacancy.get("location", ""))
        vac_city = _clean_token(vacancy.get("city", ""))
        vac_state = _clean_token(vacancy.get("state", ""))
        vac_min_exp = vacancy.get("min_exp", 0) or 0
        vac_max_exp = vacancy.get("max_exp")
        vac_sal_max = vacancy.get("salary_max") or vacancy.get("salary_min")

        # 1. Subject Matching & Conflict Prevention (35 points)
        # Identify canonical subject group for candidate
        cand_subj_canonical = None
        for grp, tokens in SUBJECT_GROUPS.items():
            if any(t in cand_subj for t in tokens):
                cand_subj_canonical = grp
                break

        # Check for subject conflict in vacancy title
        if cand_subj_canonical:
            vac_subj_canonical = None
            for grp, tokens in SUBJECT_GROUPS.items():
                if any(t in vac_title.split() or f" {t} " in f" {vac_title} " for t in tokens):
                    vac_subj_canonical = grp
                    break

            if vac_subj_canonical and vac_subj_canonical != cand_subj_canonical:
                # Direct subject mismatch: candidate specializes in English but job is for Maths/Physics/etc.
                return 0, [f"Subject mismatch: Vacancy is for {vac_subj_canonical.replace('_', ' ').title()}, candidate specializes in {candidate_data.get('subject')}"]

        subj_matched = False
        if cand_subj_canonical:
            tokens = SUBJECT_GROUPS[cand_subj_canonical]
            if any(t in vac_title for t in tokens):
                subj_matched = True
                score += 35
                reasons.append(f"Subject Match: {candidate_data.get('subject')}")
        elif cand_subj:
            cand_subj_tokens = cand_subj.split()
            for token in cand_subj_tokens:
                if len(token) >= 3 and token in vac_title:
                    subj_matched = True
                    score += 35
                    reasons.append(f"Subject Match: {candidate_data.get('subject')}")
                    break


        # 2. Profession / Designation Match (30 points)
        desig_matched = False
        role_tokens = set(cand_desig.split() + cand_headline.split())
        key_roles = {"teacher", "lecturer", "professor", "faculty", "hod", "principal", "coordinator", "developer", "engineer", "trainer"}
        matching_roles = role_tokens.intersection(key_roles)

        vac_title_tokens = set(vac_title.split())
        overlap = role_tokens.intersection(vac_title_tokens)
        if overlap:
            score += 30
            desig_matched = True
            reasons.append(f"Role Match: {candidate_data.get('designation') or candidate_data.get('headline')}")
        elif matching_roles and any(r in vac_title_tokens for r in matching_roles):
            score += 20
            desig_matched = True
            reasons.append("Teaching Role Compatible")

        # 3. Location Matching (20 points)
        loc_matched = False
        cand_locs = [cand_city, cand_state, cand_pref_loc, cand_curr_loc]
        cand_locs = [l for l in cand_locs if l]

        if not cand_locs:
            # Candidate has not restricted location, award partial baseline points
            score += 10
        else:
            for cl in cand_locs:
                if cl in vac_loc or cl in vac_city or cl in vac_state or vac_city in cl or (vac_loc and vac_loc in cl):
                    score += 20
                    loc_matched = True
                    reasons.append(f"Location Match: {vacancy.get('location')}")
                    break
            if not loc_matched and (cand_state and cand_state in vac_loc):
                score += 15
                loc_matched = True
                reasons.append(f"State Level Match: {candidate_data.get('state')}")

        # 4. Experience Matching (15 points)
        if cand_exp >= vac_min_exp:
            if vac_max_exp is None or cand_exp <= vac_max_exp:
                score += 15
                reasons.append(f"Experience Fit: {cand_exp} Years (Req: {vac_min_exp}+)")
            else:
                score += 10
                reasons.append(f"Experience Exceeds: {cand_exp} Years")
        else:
            # Short on experience
            diff = vac_min_exp - cand_exp
            if diff <= 1:
                score += 5
                reasons.append(f"Near Experience Threshold: {cand_exp} Years")

        # 5. Salary Compatibility Check
        if cand_expected_sal and vac_sal_max:
            if cand_expected_sal > vac_sal_max * 1.5:
                score -= 10
                reasons.append("Expected salary higher than budgeted range")

        return max(0, score), reasons

    @classmethod
    def match_candidate_to_vacancies(
        cls,
        candidate_user: User,
        vacancies: List[Dict[str, Any]],
        min_score: int = 40,
        max_matches_per_candidate: int = 5,
        dedup_window_days: int = 14,
    ) -> Tuple[List[Dict[str, Any]], str]:
        """
        Matches a single candidate against available vacancies.
        Enforces deduplication history check so candidates do not receive jobs they recently got.
        Returns (matched_jobs_list, exclusion_reason).
        """
        profile = getattr(candidate_user, "job_seeker_profile", None)
        teacher_profile = getattr(candidate_user, "teacher_profile", None)

        if not profile and not teacher_profile:
            return [], "Incomplete profile: No job seeker profile created."

        designation = (getattr(profile, "designation", "") or "").strip()
        headline = (getattr(profile, "headline", "") or "").strip()
        subject = (getattr(profile, "subject", "") or getattr(teacher_profile, "subject_specialization", "") or "").strip()

        if not designation and not headline and not subject:
            return [], "Incomplete profile: Missing designation and subject specialization."

        candidate_data = {
            "designation": designation,
            "headline": headline,
            "subject": subject,
            "city": getattr(profile, "city", "") or getattr(teacher_profile, "city", "") or "",
            "state": getattr(profile, "state", "") or getattr(teacher_profile, "state", "") or "",
            "preferred_location": getattr(profile, "preferred_location", "") or "",
            "current_location": getattr(profile, "current_location", "") or "",
            "experience_years": getattr(profile, "experience_years", 0) or int(getattr(teacher_profile, "total_experience_years", 0) or 0),
            "current_salary": getattr(profile, "current_salary", None) or getattr(teacher_profile, "current_salary", None),
            "expected_salary": getattr(profile, "expected_salary", None) or getattr(teacher_profile, "expected_salary", None),
        }

        from apps.notifications.models import CandidateJobAlertDelivery

        matched_jobs = []
        for vac in vacancies:
            # Check deduplication window: Has this job been sent to this candidate in the past N days?
            if CandidateJobAlertDelivery.is_duplicate(
                candidate_id=candidate_user.id,
                job_id=vac["id"],
                dedup_window_days=dedup_window_days,
            ):
                continue

            score, reasons = cls.calculate_compatibility(candidate_data, vac)
            if score >= min_score:
                matched_item = {
                    "id": vac["id"],
                    "type": vac["type"],
                    "title": vac["title"],
                    "organization": vac["organization"],
                    "location": vac["location"],
                    "salary_display": vac["salary_display"],
                    "url": vac["url"],
                    "job_type": vac["job_type"],
                    "score": score,
                    "reasons": reasons,
                }
                matched_jobs.append(matched_item)

        # Sort descending by match score
        matched_jobs.sort(key=lambda x: x["score"], reverse=True)
        top_matches = matched_jobs[:max_matches_per_candidate]

        if not top_matches:
            return [], "No matching active vacancies meeting relevance criteria or already delivered recently."

        return top_matches, ""

    @classmethod
    def get_matching_jobs_for_candidate(
        cls,
        candidate_user: User,
        specific_job_ids: Sequence[str] | None = None,
        min_score: int = 40,
        limit: int = 5,
        dedup_window_days: int = 14,
    ) -> List[Dict[str, Any]]:
        """
        Convenience method to retrieve matching vacancies for a candidate.
        """
        vacancies = cls.get_public_vacancies(specific_job_ids=specific_job_ids)
        matches, _ = cls.match_candidate_to_vacancies(
            candidate_user=candidate_user,
            vacancies=vacancies,
            min_score=min_score,
            max_matches_per_candidate=limit,
            dedup_window_days=dedup_window_days,
        )
        return matches

    @classmethod
    def evaluate_audience(
        cls,
        *,
        filters: Dict[str, Any] | None = None,
        specific_job_ids: Sequence[str] | None = None,
        min_score: int = 40,
        dedup_window_days: int = 14,
    ) -> Dict[str, Any]:
        """
        Core service method that evaluates candidates against real vacancies based on targeting criteria.
        Returns full live counts, candidate reviews, and matching breakdown.
        """
        filters = filters or {}
        from apps.notifications.models import EmailSuppression

        # 1. Base Job Seeker Query
        qs = User.objects.filter(
            role=User.Role.JOB_SEEKER,
            is_deleted=False,
        ).select_related("job_seeker_profile").prefetch_related("job_seeker_profile__qualifications")

        # Targeting filters
        q = (filters.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q))

        profession = (filters.get("profession") or "").strip()
        if profession:
            qs = qs.filter(
                Q(job_seeker_profile__designation__icontains=profession) |
                Q(job_seeker_profile__headline__icontains=profession)
            )

        subject = (filters.get("subject") or "").strip()
        if subject:
            qs = qs.filter(job_seeker_profile__subject__icontains=subject)

        location = (filters.get("location") or "").strip()
        if location:
            qs = qs.filter(
                Q(job_seeker_profile__city__icontains=location) |
                Q(job_seeker_profile__state__icontains=location) |
                Q(job_seeker_profile__preferred_location__icontains=location) |
                Q(job_seeker_profile__current_location__icontains=location)
            )

        min_exp = filters.get("min_exp") or filters.get("experience_min")
        if min_exp is not None and str(min_exp).replace(".", "", 1).isdigit():
            qs = qs.filter(job_seeker_profile__experience_years__gte=float(min_exp))

        max_exp = filters.get("max_exp") or filters.get("experience_max")
        if max_exp is not None and str(max_exp).replace(".", "", 1).isdigit():
            qs = qs.filter(job_seeker_profile__experience_years__lte=float(max_exp))

        pref_job_type = (filters.get("job_type") or "").strip()
        if pref_job_type:
            qs = qs.filter(job_seeker_profile__preferred_job_type=pref_job_type)

        status_filter = (filters.get("status") or "").strip()
        if status_filter == "active":
            qs = qs.filter(is_active=True)
        elif status_filter == "inactive":
            qs = qs.filter(is_active=False)

        total_candidates_found = qs.count()

        # 2. Fetch available vacancies
        vacancies = cls.get_public_vacancies(specific_job_ids=specific_job_ids)

        # 3. Evaluate each candidate
        suppressed_emails = set(
            EmailSuppression.objects.values_list("email", flat=True)
        )

        candidates_review = []
        candidates_with_matching_jobs = 0
        candidates_excluded_no_jobs = 0
        candidates_excluded_suppressed = 0
        candidates_excluded_inactive = 0
        candidates_with_valid_email = 0

        for user in qs.order_by("-date_joined"):
            email = user.email.strip().lower()
            has_valid_email = bool(email and "@" in email)
            if has_valid_email:
                candidates_with_valid_email += 1

            is_suppressed = email in suppressed_emails
            is_active = user.is_active

            profile = getattr(user, "job_seeker_profile", None)
            desig = getattr(profile, "designation", "") if profile else ""
            subj = getattr(profile, "subject", "") if profile else ""
            loc = (getattr(profile, "city", "") or getattr(profile, "preferred_location", "")) if profile else ""

            matched_jobs, exclusion_reason = cls.match_candidate_to_vacancies(
                candidate_user=user,
                vacancies=vacancies,
                min_score=min_score,
                dedup_window_days=dedup_window_days,
            )

            # Determine eligibility status
            is_eligible = True
            reason = ""

            if not is_active:
                is_eligible = False
                reason = "Account is inactive"
                candidates_excluded_inactive += 1
            elif not has_valid_email:
                is_eligible = False
                reason = "Missing or invalid email address"
            elif is_suppressed:
                is_eligible = False
                reason = "Email is suppressed (unsubscribed or bounced)"
                candidates_excluded_suppressed += 1
            elif profile and not profile.job_alerts_enabled:
                is_eligible = False
                reason = "Candidate has opted out of Job Alerts"
            elif not matched_jobs:
                is_eligible = False
                reason = exclusion_reason or "No matching active vacancies found"
                candidates_excluded_no_jobs += 1
            else:
                candidates_with_matching_jobs += 1

            candidates_review.append({
                "candidate_id": str(user.id),
                "user": user,
                "name": user.full_name or user.email.split("@")[0],
                "email": user.email,
                "profession": desig or "Not specified",
                "subject": subj or "Not specified",
                "location": loc or "Not specified",
                "experience_years": getattr(profile, "experience_years", 0) if profile else 0,
                "expected_salary": getattr(profile, "expected_salary", None) if profile else None,
                "matched_jobs": matched_jobs,
                "matched_job_count": len(matched_jobs),
                "is_eligible": is_eligible,
                "exclusion_reason": reason,
            })

        total_excluded = candidates_excluded_no_jobs + candidates_excluded_suppressed + candidates_excluded_inactive
        return {
            "total_candidates": total_candidates_found,
            "total_job_seekers_found": total_candidates_found,
            "active_candidates": qs.filter(is_active=True).count(),
            "active_job_seekers": qs.filter(is_active=True).count(),
            "valid_email_count": candidates_with_valid_email,
            "with_valid_email": candidates_with_valid_email,
            "candidates_with_matching_jobs": candidates_with_matching_jobs,
            "eligible_candidates_count": candidates_with_matching_jobs,
            "candidates_excluded_no_jobs": candidates_excluded_no_jobs,
            "no_matching_jobs_count": candidates_excluded_no_jobs,
            "candidates_excluded_suppressed": candidates_excluded_suppressed,
            "candidates_excluded_inactive": candidates_excluded_inactive,
            "excluded_count": total_excluded,
            "available_vacancies_count": len(vacancies),
            "vacancies": vacancies,
            "candidates_review": candidates_review,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # FIVE ALERT TYPES MATCHING & AUDIENCE EVALUATION ENGINES
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def _format_walkin_dict(cls, j: Job) -> Dict[str, Any]:
        """Format a Job walk-in model instance into standard dictionary structure."""
        start_str = j.walkin_start_date.strftime("%b %d, %Y") if j.walkin_start_date else "Today / Ongoing"
        end_str = f" to {j.walkin_end_date.strftime('%b %d, %Y')}" if j.walkin_end_date and j.walkin_end_date != j.walkin_start_date else ""
        dates_time = f"{start_str}{end_str}"
        if j.walkin_time:
            dates_time += f" ({j.walkin_time})"

        meta = j.metadata or {}
        subject = meta.get("subject", "")

        return {
            "id": str(j.id),
            "title": j.title,
            "organization": j.company.name if j.company else "Direct Institution",
            "location": j.city or j.location,
            "venue": j.walkin_venue or (j.location if j.location else "Institution Premises"),
            "dates_and_time": dates_time,
            "time": j.walkin_time or "10:00 AM - 4:00 PM",
            "instructions": j.walkin_contact_instructions or "Bring 2 copies of your updated CV, original certificates, and photo ID. Candidates can attend directly without applying online.",
            "attendance_note": "Candidates can attend directly without submitting an online application.",
            "url": f"/jobs/{j.slug}/" if j.slug else "#",
            "salary_display": f"₹{j.salary_min:,} - ₹{j.salary_max:,}" if j.salary_min and j.salary_max else "Competitive",
            "min_experience_years": j.min_experience_years or 0,
            "max_experience_years": j.max_experience_years,
            "subject": subject,
        }

    @classmethod
    def get_walkin_vacancies(cls) -> List[Dict[str, Any]]:
        """Retrieve verified active walk-in vacancies from database."""
        today = timezone.now().date()
        walkin_qs = Job.objects.filter(
            is_walkin=True,
            is_active=True,
            status=Job.Status.ACTIVE,
            approval_status=Job.ApprovalStatus.APPROVED,
        ).filter(
            Q(walkin_end_date__gte=today) | Q(walkin_start_date__gte=today) | Q(deadline__gte=today) | Q(deadline__isnull=True)
        ).select_related("company", "category")

        return [cls._format_walkin_dict(j) for j in walkin_qs]

    @classmethod
    def count_matching_candidates_for_walkin(cls, walkin_job: Job) -> int:
        """
        Calculate matching candidates count for a walk-in vacancy based on candidate profile.
        Profile-based candidate qualification without requiring separate public job matches.
        """
        eval_res = cls.evaluate_walkin_audience(
            walkin_job_id=str(walkin_job.id),
            filters={"active_only": True, "alerts_enabled_only": True},
            dedup_window_days=0,
        )
        return eval_res.get("eligible_candidates_count", 0)

    @classmethod
    def get_active_requirements(cls) -> List[Dict[str, Any]]:
        """Retrieve approved and assigned InstitutionRequirements for VIP alerts."""
        reqs = InstitutionRequirement.objects.filter(
            status__in=[
                InstitutionRequirement.RequirementStatus.ASSIGNED,
                InstitutionRequirement.RequirementStatus.IN_PROGRESS,
                InstitutionRequirement.RequirementStatus.MATCHING,
                InstitutionRequirement.RequirementStatus.CANDIDATES_FOUND,
                InstitutionRequirement.RequirementStatus.JOB_CREATED,
            ]
        ).select_related("company").order_by("-created_at")

        results = []
        for r in reqs:
            sal_str = f"₹{r.salary_min:,} - ₹{r.salary_max:,}" if r.salary_min and r.salary_max else "As per institutional norms"
            if r.salary_period == "annual":
                sal_str += " LPA"
            elif r.salary_min:
                sal_str += "/month"

            results.append({
                "id": str(r.id),
                "req_code": r.req_code,
                "subject": r.subject,
                "grade": r.get_teaching_grade_display() if hasattr(r, "get_teaching_grade_display") else r.teaching_grade,
                "institution_name": r.institution_name,
                "location": r.city or r.location,
                "experience": r.experience_range or (f"{r.min_experience_years}+ years" if r.min_experience_years else "Fresher / Experienced"),
                "salary": sal_str,
                "positions_count": r.positions_count,
                "status": r.get_status_display(),
                "url": f"/jobs/requirements/{r.id}/" if hasattr(r, "id") else "#",
            })
        return results

    @classmethod
    def evaluate_interview_audience(
        cls,
        status_filter: Optional[str] = None,
        specific_candidate_id: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Type 2: Interview Alert (Personal) Audience.
        Identifies candidates with real confirmed Shortlisted or Interview Scheduled records.
        """
        filters = filters or {}
        status_filter = status_filter or filters.get("status")
        specific_candidate_id = specific_candidate_id or filters.get("candidate_id")

        candidates_review = []
        seen_emails = set()

        # 1. From JobApplication
        app_statuses = [JobApplication.Status.SHORTLISTED, JobApplication.Status.INTERVIEW_SCHEDULED]
        if status_filter:
            app_statuses = [status_filter]

        app_qs = JobApplication.objects.filter(status__in=app_statuses).select_related(
            "applicant", "applicant__job_seeker_profile", "job", "job__company"
        ).order_by("-updated_at")

        if specific_candidate_id:
            app_qs = app_qs.filter(applicant__id=specific_candidate_id)

        for app in app_qs:
            user = app.applicant
            if not user or user.email in seen_emails:
                continue
            seen_emails.add(user.email)

            job_title = app.job.title if app.job else "Faculty Opening"
            org_name = app.job.company.name if app.job and app.job.company else "Institution"
            status_display = app.get_status_display()

            interview_block_html = ""
            interview_block_plain = ""
            date_str = ""
            mode_str = ""
            loc_str = ""
            if app.status == JobApplication.Status.INTERVIEW_SCHEDULED and app.interview_at:
                date_str = app.interview_at.strftime("%A, %b %d, %Y at %I:%M %p")
                mode_str = app.get_interview_mode_display() if hasattr(app, "get_interview_mode_display") else (app.interview_mode or "Scheduled Mode")
                loc_str = app.interview_location or app.meeting_link or "Institution Campus / Provided Link"
                interview_block_html = f"""
                <p style="margin: 0 0 6px 0;"><strong>Date & Time:</strong> {date_str}</p>
                <p style="margin: 0 0 6px 0;"><strong>Interview Mode:</strong> {mode_str}</p>
                <p style="margin: 0;"><strong>Location / Meeting Link:</strong> {loc_str}</p>
                """
                interview_block_plain = f"Date & Time: {date_str}\nMode: {mode_str}\nVenue/Link: {loc_str}"
                next_steps = "Please review your demo presentation guidelines and have your educational credentials ready. Arrive 15 minutes before the scheduled time."
            else:
                next_steps = "Our academic selection committee has shortlisted your profile. We are currently coordinating interview slots and will update you shortly."

            profile = getattr(user, "job_seeker_profile", None)
            is_eligible = bool(user.is_active and getattr(profile, "job_alerts_enabled", True))
            candidates_review.append({
                "candidate_id": str(user.id),
                "user": user,
                "name": user.get_full_name() or user.username,
                "email": user.email,
                "profession": profile.designation if profile and profile.designation else "Teaching Professional",
                "subject": profile.subject if profile and profile.subject else "General",
                "location": profile.preferred_location if profile and profile.preferred_location else "Not specified",
                "role_title": job_title,
                "institution_name": org_name,
                "candidate_status": status_display,
                "interview_details_block": interview_block_html,
                "interview_details_plain": interview_block_plain,
                "next_steps": next_steps,
                "source_type": "job_application",
                "source_id": str(app.id),
                "is_eligible": is_eligible,
                "exclusion_reason": "" if is_eligible else "User account inactive or alerts disabled",
                "matched_jobs": [{"title": job_title, "organization": org_name, "location": app.job.location if app.job else "Campus", "salary_display": "Official Interview", "job_type": "Interview"}],
                "matched_job_count": 1,
                "metadata": {
                    "role_title": job_title,
                    "employer_name": org_name,
                    "status": status_display,
                    "interview_date": date_str,
                    "interview_time": "",
                    "interview_type": mode_str,
                    "venue_or_link": loc_str,
                    "next_steps": next_steps,
                    "match_id": str(app.id),
                },
            })

        # 2. From RequirementCandidateMatch
        req_statuses = [RequirementCandidateMatch.MatchStatus.SHORTLISTED, RequirementCandidateMatch.MatchStatus.INTERVIEW_SCHEDULED]
        if status_filter:
            req_statuses = [status_filter]

        match_qs = RequirementCandidateMatch.objects.filter(status__in=req_statuses).select_related(
            "candidate", "candidate__job_seeker_profile", "requirement"
        ).order_by("-updated_at")

        if specific_candidate_id:
            match_qs = match_qs.filter(candidate__id=specific_candidate_id)

        for m in match_qs:
            user = m.candidate
            if not user or user.email in seen_emails:
                continue
            seen_emails.add(user.email)

            req_title = f"{m.requirement.subject} ({m.requirement.get_teaching_grade_display() if hasattr(m.requirement, 'get_teaching_grade_display') else m.requirement.teaching_grade})"
            org_name = m.requirement.institution_name or "Academic Institution"
            status_display = m.get_status_display()
            next_steps = "Your profile has been selected for direct review by the institution hiring authority. You will be contacted for scheduling."

            profile = getattr(user, "job_seeker_profile", None)
            is_eligible = bool(user.is_active and getattr(profile, "job_alerts_enabled", True))
            candidates_review.append({
                "candidate_id": str(user.id),
                "user": user,
                "name": user.get_full_name() or user.username,
                "email": user.email,
                "profession": profile.designation if profile and profile.designation else "Teaching Professional",
                "subject": profile.subject if profile and profile.subject else "General",
                "location": profile.preferred_location if profile and profile.preferred_location else "Not specified",
                "role_title": req_title,
                "institution_name": org_name,
                "candidate_status": status_display,
                "interview_details_block": "",
                "interview_details_plain": "",
                "next_steps": next_steps,
                "source_type": "requirement_match",
                "source_id": str(m.id),
                "is_eligible": is_eligible,
                "exclusion_reason": "" if is_eligible else "User account inactive or alerts disabled",
                "matched_jobs": [{"title": req_title, "organization": org_name, "location": m.requirement.location, "salary_display": "Official Interview", "job_type": "Interview"}],
                "matched_job_count": 1,
                "metadata": {
                    "role_title": req_title,
                    "employer_name": org_name,
                    "status": status_display,
                    "interview_date": "",
                    "interview_time": "",
                    "interview_type": "In-Person",
                    "venue_or_link": m.requirement.location or "Institution Campus",
                    "next_steps": next_steps,
                    "match_id": str(m.id),
                },
            })

        eligible_count = sum(1 for c in candidates_review if c["is_eligible"])
        return {
            "total_candidates": len(candidates_review),
            "total_job_seekers_found": len(candidates_review),
            "active_candidates": eligible_count,
            "active_job_seekers": eligible_count,
            "valid_email_count": len(candidates_review),
            "with_valid_email": len(candidates_review),
            "candidates_with_matching_jobs": eligible_count,
            "eligible_candidates_count": eligible_count,
            "candidates_excluded_no_jobs": 0,
            "no_matching_jobs_count": 0,
            "candidates_excluded_suppressed": 0,
            "candidates_excluded_inactive": len(candidates_review) - eligible_count,
            "excluded_count": len(candidates_review) - eligible_count,
            "available_vacancies_count": len(candidates_review),
            "candidates_review": candidates_review,
        }

    @classmethod
    def evaluate_walkin_audience(
        cls,
        walkin_job_id: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        dedup_window_days: int = 14,
    ) -> Dict[str, Any]:
        """
        Type 3: Walk-in Alert (Urgent) Audience.
        Direct profile-based candidate qualification for a walk-in interview event.
        Does NOT require matching public jobs, applications, or external job dependencies.
        """
        from apps.notifications.models import CandidateJobAlertDelivery, EmailSuppression

        filters = filters or {}
        walkins = cls.get_walkin_vacancies()
        target_walkin = None

        if walkin_job_id:
            for w in walkins:
                if str(w["id"]) == str(walkin_job_id):
                    target_walkin = w
                    break
            if not target_walkin:
                # Direct lookup for this walkin job (including drafts/published)
                j_obj = Job.objects.filter(is_walkin=True, pk=walkin_job_id).select_related("company", "category").first()
                if j_obj:
                    target_walkin = cls._format_walkin_dict(j_obj)
        elif walkins:
            target_walkin = walkins[0]

        qs = User.objects.filter(
            role=User.Role.JOB_SEEKER,
            is_deleted=False,
        ).select_related("job_seeker_profile", "teacher_profile").prefetch_related("job_seeker_profile__qualifications").order_by("-date_joined")

        total_candidates_found = qs.count()

        if not target_walkin:
            active_cnt = qs.filter(is_active=True).count()
            valid_email_cnt = qs.filter(email__contains="@").count()
            return {
                "total_candidates": total_candidates_found,
                "total_job_seekers_found": total_candidates_found,
                "active_candidates": active_cnt,
                "active_job_seekers": active_cnt,
                "valid_email_count": valid_email_cnt,
                "with_valid_email": valid_email_cnt,
                "matching_profiles_count": 0,
                "candidates_with_matching_jobs": 0,
                "eligible_candidates_count": 0,
                "candidates_excluded_no_jobs": 0,
                "no_matching_jobs_count": 0,
                "candidates_excluded_suppressed": 0,
                "candidates_excluded_inactive": 0,
                "excluded_count": total_candidates_found,
                "available_vacancies_count": len(walkins),
                "candidates_review": [],
                "selected_walkin": None,
            }

        walkin_descriptor = {
            "id": str(target_walkin["id"]),
            "title": target_walkin["title"],
            "organization": target_walkin["organization"],
            "location": target_walkin.get("location", ""),
            "venue": target_walkin.get("venue") or target_walkin.get("location", "Institution Premises"),
            "dates_and_time": target_walkin.get("dates_and_time", "Today"),
            "time": target_walkin.get("time", "10:00 AM - 4:00 PM"),
            "instructions": target_walkin.get("instructions", "Bring 2 copies of your updated CV, original certificates, and photo ID. Candidates can attend directly without applying online."),
            "attendance_note": "Candidates can attend directly without submitting an online application.",
            "url": target_walkin.get("url", "#"),
            "salary_display": target_walkin.get("salary_display", "Competitive"),
            "job_type": "Walk-in Interview",
            "score": 100,
        }

        # Determine subject specialization from walkin title or metadata
        walkin_title_clean = _clean_token(target_walkin.get("title", ""))
        walkin_meta_subj = _clean_token(target_walkin.get("subject", ""))
        walkin_canonical_subject = None
        for grp, tokens in SUBJECT_GROUPS.items():
            if any(t in walkin_title_clean.split() or f" {t} " in f" {walkin_title_clean} " for t in tokens) or any(t in walkin_meta_subj.split() for t in tokens):
                walkin_canonical_subject = grp
                break

        # Filter criteria extraction
        filter_subject = (filters.get("subject") or "").strip()
        filter_profession = (filters.get("profession") or "").strip()
        filter_location = (filters.get("location") or "").strip()
        exp_min = filters.get("experience_min")
        exp_max = filters.get("experience_max")
        alerts_enabled_only = filters.get("alerts_enabled_only", True)
        active_only = filters.get("active_only", True)
        if "dedup_window_days" in filters:
            try:
                dedup_window_days = int(filters["dedup_window_days"])
            except (ValueError, TypeError):
                pass

        candidates_review = []
        matching_profiles_count = 0
        eligible_candidates_count = 0
        candidates_with_valid_email = 0
        candidates_excluded_suppressed = 0
        candidates_excluded_inactive = 0

        for u in qs:
            profile = getattr(u, "job_seeker_profile", None)
            teacher_profile = getattr(u, "teacher_profile", None)
            cand_name = u.get_full_name() or u.username
            cand_email = (u.email or "").strip().lower()
            cand_desig = (getattr(profile, "designation", "") or "").strip()
            cand_headline = (getattr(profile, "headline", "") or "").strip()
            cand_subj = (getattr(profile, "subject", "") or getattr(teacher_profile, "subject_specialization", "") or "").strip()
            cand_city = (getattr(profile, "city", "") or getattr(teacher_profile, "city", "") or "").strip()
            cand_state = (getattr(profile, "state", "") or getattr(teacher_profile, "state", "") or "").strip()
            cand_pref_loc = (getattr(profile, "preferred_location", "") or "").strip()
            cand_curr_loc = (getattr(profile, "current_location", "") or "").strip()
            cand_exp = getattr(profile, "experience_years", 0) or int(getattr(teacher_profile, "total_experience_years", 0) or 0)
            cand_sal = getattr(profile, "expected_salary", None) or getattr(teacher_profile, "expected_salary", None)

            has_valid_email = bool(cand_email and "@" in cand_email)
            if has_valid_email:
                candidates_with_valid_email += 1

            # --- 1. Profile Compatibility Checks ---
            is_profile_match = True
            mismatch_reasons = []

            # Subject alignment
            if filter_subject and filter_subject not in ("All Subjects (Any)", "All"):
                # Explicit admin filter supplied
                cand_subj_clean = _clean_token(cand_subj)
                filter_subj_clean = _clean_token(filter_subject)
                filter_canonical = None
                for grp, tokens in SUBJECT_GROUPS.items():
                    if any(t in filter_subj_clean.split() for t in tokens):
                        filter_canonical = grp
                        break
                cand_canonical = None
                for grp, tokens in SUBJECT_GROUPS.items():
                    if any(t in cand_subj_clean.split() for t in tokens):
                        cand_canonical = grp
                        break
                if filter_canonical and cand_canonical:
                    if filter_canonical != cand_canonical:
                        is_profile_match = False
                        mismatch_reasons.append(f"Subject specialization mismatch: Candidate specializes in {cand_subj or 'Other'}, filter requires {filter_subject}")
                elif filter_subj_clean not in cand_subj_clean and cand_subj_clean not in filter_subj_clean:
                    is_profile_match = False
                    mismatch_reasons.append(f"Subject mismatch: Candidate specializes in {cand_subj or 'Other'}, filter requires {filter_subject}")
            elif walkin_canonical_subject:
                # No admin filter, but walk-in is for a specific subject (e.g. English)
                cand_subj_clean = _clean_token(cand_subj)
                cand_canonical = None
                for grp, tokens in SUBJECT_GROUPS.items():
                    if any(t in cand_subj_clean.split() for t in tokens):
                        cand_canonical = grp
                        break
                if cand_canonical and cand_canonical != walkin_canonical_subject:
                    is_profile_match = False
                    mismatch_reasons.append(f"Subject conflict: Walk-in is for {walkin_canonical_subject.title()}, candidate specializes in {cand_subj}")

            # Profession / Designation check
            if is_profile_match and filter_profession and filter_profession not in ("All Professions (Any)", "All"):
                prof_filter_clean = _clean_token(filter_profession)
                cand_role_clean = _clean_token(f"{cand_desig} {cand_headline}")
                if prof_filter_clean not in cand_role_clean and not any(t in cand_role_clean.split() for t in prof_filter_clean.split()):
                    is_profile_match = False
                    mismatch_reasons.append(f"Profession mismatch: Filter requires {filter_profession}")

            # Location check (ONLY if explicitly set by admin)
            if is_profile_match and filter_location and filter_location not in ("Any Location", "All"):
                loc_filter_clean = _clean_token(filter_location)
                cand_loc_clean = _clean_token(f"{cand_city} {cand_state} {cand_pref_loc} {cand_curr_loc}")
                if loc_filter_clean not in cand_loc_clean:
                    is_profile_match = False
                    mismatch_reasons.append(f"Location mismatch: Filter requires {filter_location}")

            # Experience checks (if filtered)
            if is_profile_match and exp_min not in (None, ""):
                try:
                    if cand_exp < int(exp_min):
                        is_profile_match = False
                        mismatch_reasons.append(f"Experience below minimum ({cand_exp} < {exp_min} yrs)")
                except (ValueError, TypeError):
                    pass

            if is_profile_match and exp_max not in (None, ""):
                try:
                    if cand_exp > int(exp_max):
                        is_profile_match = False
                        mismatch_reasons.append(f"Experience exceeds maximum ({cand_exp} > {exp_max} yrs)")
                except (ValueError, TypeError):
                    pass

            if is_profile_match:
                matching_profiles_count += 1

            # --- 2. Candidate Eligibility Checks ---
            is_eligible = is_profile_match
            exclusion_reason = "; ".join(mismatch_reasons) if not is_profile_match else ""

            if is_eligible:
                if not has_valid_email:
                    is_eligible = False
                    exclusion_reason = "Invalid email address"
                elif active_only and not u.is_active:
                    is_eligible = False
                    candidates_excluded_inactive += 1
                    exclusion_reason = "User account is inactive"
                elif alerts_enabled_only and profile and not profile.job_alerts_enabled:
                    is_eligible = False
                    candidates_excluded_suppressed += 1
                    exclusion_reason = "Candidate has disabled job alerts"
                elif EmailSuppression.is_suppressed(cand_email):
                    is_eligible = False
                    candidates_excluded_suppressed += 1
                    exclusion_reason = "Email is suppressed (unsubscribed or bounced)"
                elif dedup_window_days > 0 and CandidateJobAlertDelivery.is_duplicate(
                    candidate_id=u.id,
                    job_id=target_walkin["id"],
                    dedup_window_days=dedup_window_days,
                ):
                    is_eligible = False
                    candidates_excluded_suppressed += 1
                    exclusion_reason = f"Walk-in alert already delivered within last {dedup_window_days} days"

            if is_eligible:
                eligible_candidates_count += 1

            meta = {
                "role_title": target_walkin.get("title", ""),
                "organization_name": target_walkin.get("organization", ""),
                "walkin_date": target_walkin.get("dates_and_time", ""),
                "walkin_venue": target_walkin.get("venue", ""),
                "walkin_instructions": target_walkin.get("instructions", ""),
            }

            candidates_review.append({
                "candidate_id": str(u.id),
                "user": u,
                "name": cand_name,
                "email": u.email,
                "profession": cand_desig or "Teaching Professional",
                "subject": cand_subj or "General",
                "location": cand_pref_loc or cand_city or "Any Location",
                "experience_years": cand_exp,
                "expected_salary": cand_sal,
                "matched_jobs": [walkin_descriptor],
                "matched_job_count": 1,
                "is_eligible": is_eligible,
                "exclusion_reason": exclusion_reason,
                "metadata": meta,
            })

        return {
            "total_candidates": total_candidates_found,
            "total_job_seekers_found": total_candidates_found,
            "active_candidates": qs.filter(is_active=True).count(),
            "active_job_seekers": qs.filter(is_active=True).count(),
            "valid_email_count": candidates_with_valid_email,
            "with_valid_email": candidates_with_valid_email,
            "matching_profiles_count": matching_profiles_count,
            "eligible_candidates_count": eligible_candidates_count,
            "candidates_with_matching_jobs": eligible_candidates_count,
            "candidates_excluded_no_jobs": 0,
            "no_matching_jobs_count": 0,
            "candidates_excluded_suppressed": candidates_excluded_suppressed,
            "candidates_excluded_inactive": candidates_excluded_inactive,
            "excluded_count": total_candidates_found - eligible_candidates_count,
            "available_vacancies_count": len(walkins),
            "candidates_review": candidates_review,
            "selected_walkin": target_walkin,
        }

    @classmethod
    def evaluate_employer_audience(
        cls,
        filters: Optional[Dict[str, Any]] = None,
        institute_type: Optional[str] = None,
        location: Optional[str] = None,
        verified_only: bool = False,
    ) -> Dict[str, Any]:
        """
        Type 4: Employer Alert Audience.
        Identifies legitimate recruiter / employer accounts (Schools & Colleges).
        """
        filters = filters or {}
        institute_type = institute_type or filters.get("institute_type") or filters.get("role")
        location = location or filters.get("location")
        verified_only = verified_only or filters.get("verified_only", False)

        qs = User.objects.filter(
            role=User.Role.RECRUITER,
            is_active=True,
        ).select_related("recruiter_profile__company").order_by("-date_joined")

        if institute_type and institute_type != "All":
            qs = qs.filter(recruiter_profile__company__institute_type=institute_type)
        if location:
            qs = qs.filter(
                Q(recruiter_profile__company__location__icontains=location)
                | Q(recruiter_profile__company__city__icontains=location)
                | Q(recruiter_profile__company__state__icontains=location)
            )
        if verified_only:
            qs = qs.filter(recruiter_profile__company__is_verified=True)

        employers_review = []
        for user in qs:
            recruiter = getattr(user, "recruiter_profile", None)
            company = getattr(recruiter, "company", None) if recruiter else None
            company_name = company.name if company else (user.get_full_name() or "Academic Institution")
            contact_name = (company.contact_person_name if company and company.contact_person_name else user.get_full_name()) or "Hiring Authority"
            loc = company.location if company and company.location else (company.city if company else "India")
            inst_type = company.get_institute_type_display() if company and hasattr(company, "get_institute_type_display") else "Institution"

            employers_review.append({
                "candidate_id": str(user.id),
                "employer_id": str(user.id),
                "user": user,
                "name": contact_name,
                "email": user.email,
                "company_name": company_name,
                "institute_type": inst_type,
                "location": loc,
                "profession": "Recruitment Authority",
                "subject": "",
                "is_verified": company.is_verified if company else False,
                "is_eligible": True,
                "exclusion_reason": "",
                "matched_jobs": [],
                "matched_job_count": 0,
                "metadata": {
                    "company_name": company_name,
                    "institute_type": inst_type,
                    "location": loc,
                },
                "post_job_url": "https://sevajobs.in/dashboard/recruiter/jobs/create/",
                "submit_requirement_url": "https://sevajobs.in/jobs/submit-requirement/",
            })

        count = len(employers_review)
        return {
            "total_candidates": count,
            "total_job_seekers_found": count,
            "active_candidates": count,
            "active_job_seekers": count,
            "valid_email_count": count,
            "with_valid_email": count,
            "candidates_with_matching_jobs": count,
            "eligible_candidates_count": count,
            "candidates_excluded_no_jobs": 0,
            "no_matching_jobs_count": 0,
            "candidates_excluded_suppressed": 0,
            "candidates_excluded_inactive": 0,
            "excluded_count": 0,
            "available_vacancies_count": count,
            "candidates_review": employers_review,
        }

    @classmethod
    def evaluate_requirement_audience(
        cls,
        requirement_id: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        dedup_window_days: int = 7,
    ) -> Dict[str, Any]:
        """
        Type 5: Job Requirement Alert (VIP Urgent) Audience.
        Matches candidates against an approved institutional requirement.
        """
        filters = filters or {}
        active_reqs = cls.get_active_requirements()
        if not active_reqs:
            return {
                "total_candidates": 0,
                "total_job_seekers_found": 0,
                "active_candidates": 0,
                "active_job_seekers": 0,
                "valid_email_count": 0,
                "with_valid_email": 0,
                "candidates_with_matching_jobs": 0,
                "eligible_candidates_count": 0,
                "candidates_excluded_no_jobs": 0,
                "no_matching_jobs_count": 0,
                "candidates_excluded_suppressed": 0,
                "candidates_excluded_inactive": 0,
                "excluded_count": 0,
                "available_vacancies_count": 0,
                "candidates_review": [],
                "selected_requirement": None,
            }

        target_req = active_reqs[0]
        if requirement_id:
            for r in active_reqs:
                if str(r["id"]) == str(requirement_id):
                    target_req = r
                    break

        req_filters = {
            "subject": filters.get("subject") or target_req.get("subject", ""),
            "location": filters.get("location") or target_req.get("location", ""),
            "experience_min": filters.get("experience_min"),
            "experience_max": filters.get("experience_max"),
            "alerts_enabled_only": True,
            "active_only": True,
        }

        eval_res = cls.evaluate_audience(
            filters=req_filters,
            dedup_window_days=dedup_window_days,
        )

        req_matched_job = {
            "id": str(target_req["id"]),
            "title": f"{target_req.get('subject', 'Faculty')} Requirement",
            "organization": target_req.get("institution_name", "Academic Institution"),
            "location": target_req.get("location", ""),
            "salary_display": target_req.get("salary", "Competitive"),
            "job_type": "Institutional Requirement",
            "score": 100,
        }
        for c in eval_res["candidates_review"]:
            if not c.get("matched_jobs"):
                c["matched_jobs"] = [req_matched_job]
                c["matched_job_count"] = 1
                ex_reason = c.get("exclusion_reason", "")
                if "No matching" in ex_reason or "No active vacancies" in ex_reason or not ex_reason:
                    c["is_eligible"] = True
                    c["exclusion_reason"] = ""

        eligible_count = sum(1 for c in eval_res["candidates_review"] if c.get("is_eligible"))
        eval_res["eligible_candidates_count"] = eligible_count
        eval_res["candidates_with_matching_jobs"] = eligible_count
        eval_res["no_matching_jobs_count"] = len(eval_res["candidates_review"]) - eligible_count
        eval_res["selected_requirement"] = target_req
        return eval_res
