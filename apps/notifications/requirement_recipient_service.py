"""
Domain service for filtering and calculating eligible candidate recipients
scoped strictly to an InstitutionRequirement lifecycle workflow.
"""

from __future__ import annotations

import logging
from typing import Sequence, Dict, Any, List
from django.db.models import Q, Count
from apps.jobs.models import RequirementCandidateMatch, InstitutionRequirement
from apps.notifications.models import EmailSuppression

logger = logging.getLogger("apps.notifications")


class RequirementRecipientService:
    """
    Evaluates and retrieves eligible candidate email recipients for a Teaching Requirement.
    Applies lifecycle status filtering, account activity validation, and suppression checking.
    """

    # Lifecycle status mappings for UI choices
    STATUS_MAP = {
        "shortlisted": RequirementCandidateMatch.MatchStatus.SHORTLISTED,
        "interview_scheduled": RequirementCandidateMatch.MatchStatus.INTERVIEW_SCHEDULED,
        "selected": RequirementCandidateMatch.MatchStatus.SELECTED,
        "rejected": RequirementCandidateMatch.MatchStatus.REJECTED,
        "joined": RequirementCandidateMatch.MatchStatus.JOINED,
        "matched": RequirementCandidateMatch.MatchStatus.MATCHED,
    }

    @classmethod
    def get_status_counts(cls, requirement_id: str) -> Dict[str, int]:
        """
        Compute live counts for all candidate lifecycle categories for this requirement.
        Applies account activity and suppression exclusions at the database level.
        """
        suppressed_emails = EmailSuppression.objects.values("email")

        base_qs = RequirementCandidateMatch.objects.filter(
            requirement_id=requirement_id,
            candidate__is_active=True,
            candidate__is_deleted=False,
            candidate__email__isnull=False,
        ).exclude(candidate__email__in=suppressed_emails)

        counts = base_qs.aggregate(
            total_eligible=Count("candidate_id", distinct=True),
            shortlisted=Count("candidate_id", filter=Q(status=RequirementCandidateMatch.MatchStatus.SHORTLISTED), distinct=True),
            interview_scheduled=Count("candidate_id", filter=Q(status=RequirementCandidateMatch.MatchStatus.INTERVIEW_SCHEDULED), distinct=True),
            selected=Count("candidate_id", filter=Q(status=RequirementCandidateMatch.MatchStatus.SELECTED), distinct=True),
            rejected=Count("candidate_id", filter=Q(status=RequirementCandidateMatch.MatchStatus.REJECTED), distinct=True),
            joined=Count("candidate_id", filter=Q(status=RequirementCandidateMatch.MatchStatus.JOINED), distinct=True),
            matched=Count("candidate_id", filter=Q(status=RequirementCandidateMatch.MatchStatus.MATCHED), distinct=True),
        )

        total_matched_raw = RequirementCandidateMatch.objects.filter(requirement_id=requirement_id).count()

        return {
            "total_matched": total_matched_raw,
            "total_eligible": counts.get("total_eligible") or 0,
            "shortlisted": counts.get("shortlisted") or 0,
            "interview_scheduled": counts.get("interview_scheduled") or 0,
            "selected": counts.get("selected") or 0,
            "rejected": counts.get("rejected") or 0,
            "joined": counts.get("joined") or 0,
            "matched_only": counts.get("matched") or 0,
        }

    @classmethod
    def get_eligible_candidates(
        cls,
        requirement_id: str,
        selected_statuses: Sequence[str] | None = None,
        candidate_ids: Sequence[str] | None = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch distinct, eligible candidate matches with related profiles pre-fetched.
        
        :param requirement_id: UUID of InstitutionRequirement
        :param selected_statuses: Optional list of status strings (e.g. ['shortlisted', 'selected', 'all'])
        :param candidate_ids: Optional explicit list of candidate User IDs
        :return: List of structured dicts with candidate and match details
        """
        suppressed_emails = EmailSuppression.objects.values("email")

        qs = RequirementCandidateMatch.objects.filter(
            requirement_id=requirement_id,
            candidate__is_active=True,
            candidate__is_deleted=False,
            candidate__email__isnull=False,
        ).exclude(
            candidate__email__in=suppressed_emails
        ).select_related(
            "candidate",
            "candidate__job_seeker_profile",
            "requirement",
        ).order_by("-match_score", "-created_at")

        # Apply lifecycle status filters if not "all"
        if selected_statuses and "all" not in selected_statuses:
            valid_statuses = [
                cls.STATUS_MAP.get(s, s) for s in selected_statuses if s in cls.STATUS_MAP or s in RequirementCandidateMatch.MatchStatus.values
            ]
            if valid_statuses:
                qs = qs.filter(status__in=valid_statuses)
            else:
                return []

        # Apply specific candidate ID filtering if supplied
        if candidate_ids:
            clean_ids = [str(cid).strip() for cid in candidate_ids if str(cid).strip()]
            if clean_ids:
                qs = qs.filter(candidate_id__in=clean_ids)

        # Deduplicate candidates by normalized email address
        seen_emails = set()
        recipients = []

        for match in qs:
            email = match.candidate.email.strip().lower()
            if not email or "@" not in email:
                continue
            if email in seen_emails:
                continue
            seen_emails.add(email)

            full_name = match.candidate.get_full_name() or match.candidate.first_name or email.split("@")[0]
            recipients.append({
                "candidate": match.candidate,
                "candidate_id": str(match.candidate.id),
                "match": match,
                "match_id": str(match.id),
                "email": email,
                "full_name": full_name,
                "status": match.status,
                "status_display": match.get_status_display(),
                "match_score": match.match_score,
            })

        return recipients
