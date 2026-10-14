"""
SevaJobs — Candidate Matching Engine (CandidateMatchingService).
Evaluates candidate profiles against an InstitutionRequirement using a weighted
scoring algorithm and generates structured match explanations.
"""

from django.db.models import Q
from apps.accounts.models import User
from apps.jobs.models import InstitutionRequirement, RequirementCandidateMatch


class CandidateMatchingService:
    """
    Domain service responsible for ranking candidates for a specific InstitutionRequirement.
    Weighted scoring criteria:
      - Subject specialization: 35%
      - Teaching Grade / Category: 25%
      - Qualification level: 15%
      - Location (City / State / Address): 15%
      - Experience years: 10%
    """

    def calculate_match(self, requirement: InstitutionRequirement, candidate: User) -> tuple[int, str, list[str]]:
        score = 0
        reasons = []

        seeker_profile = getattr(candidate, "job_seeker_profile", None)
        teacher_profile = getattr(candidate, "teacher_profile", None)

        # 1. Subject Specialization (35 points)
        req_sub = (requirement.subject or "").strip().lower()
        seeker_sub = (getattr(seeker_profile, "subject", "") or "").strip().lower()
        teacher_sub = (getattr(teacher_profile, "subject_specialization", "") or "").strip().lower()
        headline = (getattr(seeker_profile, "headline", "") or "").strip().lower()

        if req_sub and (req_sub in seeker_sub or req_sub in teacher_sub or req_sub in headline or seeker_sub in req_sub or teacher_sub in req_sub):
            score += 35
            subj_display = getattr(teacher_profile, "subject_specialization", "") or getattr(seeker_profile, "subject", "") or requirement.subject
            reasons.append(f"✓ Subject: {subj_display}")

        # 2. Teaching Grade / Designation (25 points)
        req_grade = (requirement.teaching_grade or "").strip().lower()
        teacher_pos = (getattr(teacher_profile, "applying_position", "") or "").strip().lower()
        designation = (getattr(seeker_profile, "designation", "") or "").strip().lower()

        if req_grade and (req_grade in teacher_pos or req_grade in designation or teacher_pos in req_grade or designation in req_grade):
            score += 25
            grade_display = getattr(teacher_profile, "get_applying_position_display", lambda: "")() or getattr(seeker_profile, "designation", "") or requirement.teaching_grade
            reasons.append(f"✓ Grade: {grade_display}")

        # 3. Qualification (15 points)
        req_qual = (requirement.qualification or "").strip().lower()
        cand_quals = []
        if seeker_profile and seeker_profile.qualifications.exists():
            cand_quals.extend([q.name.lower() for q in seeker_profile.qualifications.all()])
        if teacher_profile and hasattr(teacher_profile, "education_details"):
            cand_quals.extend([ed.institution_name.lower() + " " + ed.qualification.lower() for ed in teacher_profile.education_details.all()])

        if req_qual and any(req_qual in q_name or q_name in req_qual for q_name in cand_quals):
            score += 15
            reasons.append(f"✓ Qualification: {requirement.qualification}")
        elif req_qual and seeker_profile and (req_qual in (seeker_profile.summary or "").lower()):
            score += 10
            reasons.append(f"✓ Qualification mentioned")

        # 4. Location (15 points)
        req_loc = (requirement.location or "").strip().lower()
        seeker_loc = (getattr(seeker_profile, "current_location", "") or "").strip().lower()
        pref_loc = (getattr(seeker_profile, "preferred_location", "") or "").strip().lower()
        city = (getattr(seeker_profile, "city", "") or getattr(teacher_profile, "city", "") or "").strip().lower()
        state = (getattr(seeker_profile, "state", "") or getattr(teacher_profile, "state", "") or "").strip().lower()

        if req_loc and (req_loc in seeker_loc or req_loc in pref_loc or req_loc in city or req_loc in state or city in req_loc):
            score += 15
            loc_display = getattr(seeker_profile, "city", "") or getattr(teacher_profile, "city", "") or requirement.location
            reasons.append(f"✓ Location: {loc_display}")

        # 5. Experience Years (10 points)
        cand_exp = getattr(seeker_profile, "experience_years", 0) or float(getattr(teacher_profile, "total_experience_years", 0) or 0)
        req_min = requirement.min_experience_years
        req_max = requirement.max_experience_years or 99

        if req_min <= cand_exp <= req_max:
            score += 10
            reasons.append(f"✓ Experience: {int(cand_exp)} Years")
        elif cand_exp >= req_min:
            score += 5
            reasons.append(f"✓ Experience: {int(cand_exp)} Years")

        # Determine Match Label
        if score >= 75:
            label = "Strong Match"
        elif score >= 55:
            label = "Good Match"
        else:
            label = "Partial Match"

        return score, label, reasons

    @classmethod
    def match_and_store(cls, requirement: InstitutionRequirement, limit: int = 50) -> list[RequirementCandidateMatch]:
        """
        Runs candidate matching for the given requirement and persists top matches in RequirementCandidateMatch.
        Returns list of created/updated RequirementCandidateMatch records.
        """
        service = cls()
        candidates = User.objects.filter(
            role=User.Role.JOB_SEEKER,
            is_active=True
        ).select_related("job_seeker_profile").prefetch_related("job_seeker_profile__qualifications")

        scored_candidates = []
        for cand in candidates:
            score, label, reasons = service.calculate_match(requirement, cand)
            if score >= 30: # Include candidates with at least 30% relevance
                scored_candidates.append((cand, score, label, reasons))

        # Sort by match score descending
        scored_candidates.sort(key=lambda x: x[1], reverse=True)

        saved_matches = []
        for cand, score, label, reasons in scored_candidates[:limit]:
            match_obj, _ = RequirementCandidateMatch.objects.update_or_create(
                requirement=requirement,
                candidate=cand,
                defaults={
                    "match_score": score,
                    "match_label": label,
                    "match_reasons": reasons,
                    "status": RequirementCandidateMatch.MatchStatus.MATCHED
                }
            )
            saved_matches.append(match_obj)

        return saved_matches

    @classmethod
    def find_and_store_matches(cls, requirement: InstitutionRequirement, limit: int = 50) -> list[RequirementCandidateMatch]:
        return cls.match_and_store(requirement, limit=limit)

    @classmethod
    def match_requirement(cls, requirement: InstitutionRequirement, limit: int = 50):
        """
        Class method wrapper that runs candidate matching and returns stored RequirementCandidateMatch queryset.
        """
        cls.match_and_store(requirement, limit=limit)
        return RequirementCandidateMatch.objects.filter(requirement=requirement).select_related(
            "candidate", "candidate__job_seeker_profile"
        )

