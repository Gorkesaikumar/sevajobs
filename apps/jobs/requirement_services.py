"""
Domain services for Institution Requirement workflow lifecycle, employee assignment,
candidate matching, requirement-to-job conversion, and ATS pipeline integration.
"""

import logging
from django.db import transaction
from django.utils import timezone
from apps.jobs.models import (
    InstitutionRequirement,
    RequirementCandidateMatch,
    RequirementActivityLog,
    RequirementInternalNote,
    Job,
)
from apps.recruiters.models import Company, RecruiterProfile
from apps.accounts.models import User

logger = logging.getLogger(__name__)


class RequirementWorkflowService:
    """
    Centralized state machine manager for InstitutionRequirement lifecycle.
    """

    @classmethod
    def log_activity(cls, requirement, event_type, description, actor=None, metadata=None):
        return RequirementActivityLog.objects.create(
            requirement=requirement,
            actor=actor,
            event_type=event_type,
            description=description,
            metadata=metadata or {},
        )

    @classmethod
    def submit(cls, requirement, actor=None):
        requirement.status = InstitutionRequirement.RequirementStatus.SUBMITTED
        requirement.save(update_fields=["status", "updated_at"])
        cls.log_activity(
            requirement,
            RequirementActivityLog.EventType.SUBMITTED,
            f"Requirement submitted for {requirement.institution_name} ({requirement.req_code}).",
            actor=actor,
        )
        return requirement

    @classmethod
    def assign(cls, requirement, assigned_staff, assigned_by, priority=None):
        previous_staff = requirement.assigned_staff
        requirement.assigned_staff = assigned_staff
        requirement.assigned_by = assigned_by
        requirement.assigned_at = timezone.now()
        requirement.status = InstitutionRequirement.RequirementStatus.ASSIGNED
        if priority:
            requirement.priority = priority
        requirement.save(update_fields=["assigned_staff", "assigned_by", "assigned_at", "status", "priority", "updated_at"])

        if previous_staff and previous_staff != assigned_staff:
            desc = f"Requirement reassigned from {previous_staff.get_full_name() or previous_staff.email} to {assigned_staff.get_full_name() or assigned_staff.email}."
        else:
            desc = f"Requirement assigned to {assigned_staff.get_full_name() or assigned_staff.email}."

        cls.log_activity(
            requirement,
            RequirementActivityLog.EventType.ASSIGNED,
            desc,
            actor=assigned_by,
        )
        return requirement

    @classmethod
    def start_work(cls, requirement, actor):
        requirement.started_by = actor
        requirement.started_at = timezone.now()
        requirement.status = InstitutionRequirement.RequirementStatus.IN_PROGRESS
        requirement.save(update_fields=["started_by", "started_at", "status", "updated_at"])
        cls.log_activity(
            requirement,
            RequirementActivityLog.EventType.WORK_STARTED,
            f"{actor.get_full_name() or actor.email} started working on requirement.",
            actor=actor,
        )
        return requirement

    @classmethod
    def update_matching_status(cls, requirement, match_count=0):
        if match_count > 0:
            requirement.status = InstitutionRequirement.RequirementStatus.CANDIDATES_FOUND
        elif requirement.status == InstitutionRequirement.RequirementStatus.SUBMITTED:
            requirement.status = InstitutionRequirement.RequirementStatus.UNDER_REVIEW
        requirement.save(update_fields=["status", "updated_at"])
        cls.log_activity(
            requirement,
            RequirementActivityLog.EventType.MATCHING_COMPLETED,
            f"Candidate matching completed with {match_count} candidate(s) identified.",
            metadata={"match_count": match_count},
        )
        return requirement

    @classmethod
    def mark_interviewing(cls, requirement, actor=None):
        if requirement.status in [
            InstitutionRequirement.RequirementStatus.SUBMITTED,
            InstitutionRequirement.RequirementStatus.UNDER_REVIEW,
            InstitutionRequirement.RequirementStatus.ASSIGNED,
            InstitutionRequirement.RequirementStatus.IN_PROGRESS,
            InstitutionRequirement.RequirementStatus.CANDIDATES_FOUND,
            InstitutionRequirement.RequirementStatus.JOB_CREATED,
        ]:
            requirement.status = InstitutionRequirement.RequirementStatus.INTERVIEWING
            requirement.save(update_fields=["status", "updated_at"])
            cls.log_activity(
                requirement,
                RequirementActivityLog.EventType.STATUS_CHANGED,
                "Requirement status updated to Interviewing.",
                actor=actor,
            )
        return requirement

    @classmethod
    def update_fulfilled_status(cls, requirement):
        joined_count = requirement.joined_count
        positions = requirement.positions_count

        if joined_count >= positions and requirement.status != InstitutionRequirement.RequirementStatus.FULFILLED:
            requirement.status = InstitutionRequirement.RequirementStatus.FULFILLED
            requirement.fulfilled_at = timezone.now()
            requirement.save(update_fields=["status", "fulfilled_at", "updated_at"])
            cls.log_activity(
                requirement,
                RequirementActivityLog.EventType.STATUS_CHANGED,
                f"Requirement FULFILLED ({joined_count}/{positions} positions joined).",
            )
        elif 0 < joined_count < positions and requirement.status != InstitutionRequirement.RequirementStatus.PARTIALLY_FILLED:
            requirement.status = InstitutionRequirement.RequirementStatus.PARTIALLY_FILLED
            requirement.save(update_fields=["status", "updated_at"])
            cls.log_activity(
                requirement,
                RequirementActivityLog.EventType.STATUS_CHANGED,
                f"Requirement PARTIALLY FILLED ({joined_count}/{positions} positions joined).",
            )
        return requirement

    @classmethod
    def hold(cls, requirement, actor=None, reason=""):
        requirement.status = InstitutionRequirement.RequirementStatus.ON_HOLD
        requirement.save(update_fields=["status", "updated_at"])
        cls.log_activity(
            requirement,
            RequirementActivityLog.EventType.STATUS_CHANGED,
            f"Requirement placed ON HOLD. {reason}".strip(),
            actor=actor,
        )
        return requirement

    @classmethod
    def reject(cls, requirement, actor=None, reason=""):
        requirement.status = InstitutionRequirement.RequirementStatus.REJECTED
        requirement.closed_at = timezone.now()
        requirement.save(update_fields=["status", "closed_at", "updated_at"])
        cls.log_activity(
            requirement,
            RequirementActivityLog.EventType.REJECTED,
            f"Requirement REJECTED. {reason}".strip(),
            actor=actor,
        )
        return requirement

    @classmethod
    def close(cls, requirement, actor=None, reason=""):
        requirement.status = InstitutionRequirement.RequirementStatus.CLOSED
        requirement.closed_at = timezone.now()
        requirement.save(update_fields=["status", "closed_at", "updated_at"])
        cls.log_activity(
            requirement,
            RequirementActivityLog.EventType.CLOSED,
            f"Requirement CLOSED. {reason}".strip(),
            actor=actor,
        )
        return requirement


class RequirementAssignmentService:
    """
    Atomic assignment service with concurrency locking.
    """

    @classmethod
    def assign_employee(cls, requirement_id, staff_user, assigned_by_user, priority="normal", notes=""):
        with transaction.atomic():
            requirement = (
                InstitutionRequirement.objects.select_for_update()
                .get(pk=requirement_id)
            )
            
            # Update workflow
            RequirementWorkflowService.assign(
                requirement=requirement,
                assigned_staff=staff_user,
                assigned_by=assigned_by_user,
                priority=priority,
            )

            if notes.strip():
                RequirementInternalNote.objects.create(
                    requirement=requirement,
                    author=assigned_by_user,
                    body=f"Assignment note: {notes.strip()}",
                )

            # Trigger notification to staff user if notification system available
            try:
                from apps.notifications.services import NotificationService
                NotificationService.notify(
                    recipient=staff_user,
                    notification_type="requirement_assigned",
                    title="New Requirement Assigned",
                    message=f"You have been assigned requirement {requirement.req_code} for {requirement.institution_name}.",
                    actor=assigned_by_user,
                    entity_type="InstitutionRequirement",
                    entity_id=requirement.pk,
                )
            except Exception as e:
                logger.warning("Could not send assignment notification: %s", e)

            return requirement


class RequirementConversionService:
    """
    Idempotently converts an InstitutionRequirement into a formal Job posting draft.
    """

    @classmethod
    def convert_to_job_draft(cls, requirement_id, actor):
        with transaction.atomic():
            requirement = (
                InstitutionRequirement.objects.select_for_update()
                .get(pk=requirement_id)
            )

            if requirement.converted_job_id:
                return requirement.converted_job

            # Determine company
            company = requirement.company
            if not company:
                from django.utils.text import slugify
                import uuid
                comp_slug_base = slugify(requirement.institution_name) or "institution"
                slug = f"{comp_slug_base[:250]}-{str(uuid.uuid4())[:6]}"
                company, _ = Company.objects.get_or_create(
                    name=requirement.institution_name,
                    defaults={
                        "slug": slug[:280],
                    }
                )

            # Determine recruiter profile
            recruiter = requirement.recruiter
            if not recruiter:
                recruiter = RecruiterProfile.objects.filter(user=actor).first()
                if not recruiter:
                    recruiter = RecruiterProfile.objects.filter(company=company).first()
                if not recruiter:
                    recruiter = RecruiterProfile.objects.create(
                        user=actor,
                        company=company,
                        designation="HR / Staff Recruiter",
                        phone=requirement.phone_number,
                    )

            # Create Job draft
            from django.utils.text import slugify
            import uuid
            title = f"{requirement.subject} {requirement.teaching_grade} Faculty"
            job_slug_base = slugify(f"{requirement.institution_name}-{requirement.subject}") or "job"
            slug = f"{job_slug_base[:250]}-{str(uuid.uuid4())[:8]}"

            job = Job.objects.create(
                recruiter=recruiter,
                company=company,
                segment=Job.Segment.TEACHING,
                title=title,
                slug=slug[:280],
                description=f"Hiring {requirement.positions_count} {requirement.subject} ({requirement.teaching_grade}) teacher(s) for {requirement.institution_name}.",
                location=requirement.location or "India",
                city=requirement.city or "",
                district=requirement.district or "",
                state=requirement.state or "",
                vacancies=requirement.positions_count,
                salary_min=requirement.salary_min,
                salary_max=requirement.salary_max,
                min_experience_years=requirement.min_experience_years or 0,
                max_experience_years=requirement.max_experience_years,
                status=Job.Status.DRAFT,
                approval_status=Job.ApprovalStatus.PENDING,
            )

            requirement.converted_job = job
            requirement.converted_at = timezone.now()
            requirement.status = InstitutionRequirement.RequirementStatus.JOB_CREATED
            requirement.save(update_fields=["converted_job", "converted_at", "status", "updated_at"])

            RequirementActivityLog.objects.create(
                requirement=requirement,
                actor=actor,
                event_type=RequirementActivityLog.EventType.JOB_CONVERTED,
                description=f"Converted requirement into draft job '{job.title}' (Job ID: {job.id}).",
                metadata={"job_id": str(job.id)},
            )

            return job


class CandidateStateTransitionError(ValueError):
    """Raised when an invalid candidate state machine transition is attempted."""
    pass


class RequirementPipelineIntegrationService:
    """
    Connects candidate matches to ATS JobApplication status pipeline.
    Enforces canonical state machine transitions, concurrency locking, overfill protection,
    and audit logging.
    """

    @classmethod
    def get_allowed_actions(cls, match, actor=None) -> dict:
        status = match.status
        requirement = match.requirement
        is_fulfilled = requirement.is_fulfilled

        can_shortlist = (status == RequirementCandidateMatch.MatchStatus.MATCHED)
        can_interview = (status == RequirementCandidateMatch.MatchStatus.SHORTLISTED)
        can_join = (status in [RequirementCandidateMatch.MatchStatus.INTERVIEW_SCHEDULED, RequirementCandidateMatch.MatchStatus.SELECTED]) and not is_fulfilled
        can_reject = (status in [
            RequirementCandidateMatch.MatchStatus.MATCHED,
            RequirementCandidateMatch.MatchStatus.SHORTLISTED,
            RequirementCandidateMatch.MatchStatus.INTERVIEW_SCHEDULED,
            RequirementCandidateMatch.MatchStatus.SELECTED,
        ])

        return {
            "can_shortlist": can_shortlist,
            "can_interview": can_interview,
            "can_join": can_join,
            "can_reject": can_reject,
            "is_shortlisted": status in [
                RequirementCandidateMatch.MatchStatus.SHORTLISTED,
                RequirementCandidateMatch.MatchStatus.INTERVIEW_SCHEDULED,
                RequirementCandidateMatch.MatchStatus.SELECTED,
                RequirementCandidateMatch.MatchStatus.JOINED,
            ],
            "is_interviewed": status in [
                RequirementCandidateMatch.MatchStatus.INTERVIEW_SCHEDULED,
                RequirementCandidateMatch.MatchStatus.SELECTED,
                RequirementCandidateMatch.MatchStatus.JOINED,
            ],
            "is_joined": status == RequirementCandidateMatch.MatchStatus.JOINED,
            "is_rejected": status == RequirementCandidateMatch.MatchStatus.REJECTED,
        }

    @classmethod
    def shortlist_candidate(cls, match_or_id, actor):
        match_id = match_or_id.id if hasattr(match_or_id, "id") else match_or_id
        with transaction.atomic():
            match = RequirementCandidateMatch.objects.select_for_update().get(pk=match_id)

            if match.status in [
                RequirementCandidateMatch.MatchStatus.SHORTLISTED,
                RequirementCandidateMatch.MatchStatus.INTERVIEW_SCHEDULED,
                RequirementCandidateMatch.MatchStatus.SELECTED,
                RequirementCandidateMatch.MatchStatus.JOINED,
            ]:
                return match  # Idempotent return

            if match.status != RequirementCandidateMatch.MatchStatus.MATCHED:
                raise CandidateStateTransitionError(f"Cannot shortlist candidate currently in state '{match.get_status_display()}'.")

            match.status = RequirementCandidateMatch.MatchStatus.SHORTLISTED
            match.save(update_fields=["status", "updated_at"])

            RequirementActivityLog.objects.create(
                requirement=match.requirement,
                actor=actor,
                event_type=RequirementActivityLog.EventType.SHORTLISTED,
                description=f"Candidate {match.candidate.get_full_name() or match.candidate.email} shortlisted for {match.requirement.subject}.",
                metadata={"candidate_id": str(match.candidate.id)},
            )

            # Trigger notification
            try:
                from apps.notifications.services import NotificationService
                NotificationService.notify(
                    recipient=match.candidate,
                    notification_type="candidate_shortlisted",
                    title="Shortlisted for Position",
                    message=f"You have been shortlisted for {match.requirement.subject} at {match.requirement.institution_name}.",
                    actor=actor,
                    entity_type="RequirementCandidateMatch",
                    entity_id=match.id,
                )
            except Exception as e:
                logger.warning("Could not send candidate shortlist notification: %s", e)

            return match

    @classmethod
    def schedule_interview(cls, match_or_id, actor, interview_details=None):
        match_id = match_or_id.id if hasattr(match_or_id, "id") else match_or_id
        with transaction.atomic():
            match = RequirementCandidateMatch.objects.select_for_update().get(pk=match_id)

            if match.status == RequirementCandidateMatch.MatchStatus.REJECTED:
                raise CandidateStateTransitionError("Cannot schedule interview for a rejected candidate.")
            if match.status == RequirementCandidateMatch.MatchStatus.JOINED:
                raise CandidateStateTransitionError("Candidate has already joined.")

            if match.status not in [
                RequirementCandidateMatch.MatchStatus.MATCHED,
                RequirementCandidateMatch.MatchStatus.SHORTLISTED,
                RequirementCandidateMatch.MatchStatus.INTERVIEW_SCHEDULED,
            ]:
                raise CandidateStateTransitionError("Candidate must be shortlisted before scheduling an interview.")

            match.status = RequirementCandidateMatch.MatchStatus.INTERVIEW_SCHEDULED
            match.save(update_fields=["status", "updated_at"])

            RequirementWorkflowService.mark_interviewing(match.requirement, actor=actor)

            RequirementActivityLog.objects.create(
                requirement=match.requirement,
                actor=actor,
                event_type=RequirementActivityLog.EventType.INTERVIEW_SCHEDULED,
                description=f"Interview scheduled for candidate {match.candidate.get_full_name() or match.candidate.email}.",
                metadata={"candidate_id": str(match.candidate.id), "details": interview_details or {}},
            )

            try:
                from apps.notifications.services import NotificationService
                details_text = ""
                if interview_details:
                    details_text = f" on {interview_details.get('date', '')} at {interview_details.get('time', '')} ({interview_details.get('mode', 'Online')})."
                NotificationService.notify(
                    recipient=match.candidate,
                    notification_type="interview_scheduled",
                    title="Interview Scheduled",
                    message=f"An interview has been scheduled for {match.requirement.subject} at {match.requirement.institution_name}{details_text}",
                    actor=actor,
                    entity_type="RequirementCandidateMatch",
                    entity_id=match.id,
                )
            except Exception as e:
                logger.warning("Could not send interview notification: %s", e)

            return match

    @classmethod
    def mark_selected(cls, match_or_id, actor):
        match_id = match_or_id.id if hasattr(match_or_id, "id") else match_or_id
        with transaction.atomic():
            match = RequirementCandidateMatch.objects.select_for_update().get(pk=match_id)

            if match.status == RequirementCandidateMatch.MatchStatus.SELECTED:
                return match  # Idempotent

            if match.status not in [
                RequirementCandidateMatch.MatchStatus.SHORTLISTED,
                RequirementCandidateMatch.MatchStatus.INTERVIEW_SCHEDULED,
            ]:
                raise CandidateStateTransitionError("Candidate must be shortlisted or interviewed before selection.")

            match.status = RequirementCandidateMatch.MatchStatus.SELECTED
            match.save(update_fields=["status", "updated_at"])

            RequirementActivityLog.objects.create(
                requirement=match.requirement,
                actor=actor,
                event_type=RequirementActivityLog.EventType.SELECTED,
                description=f"Candidate {match.candidate.get_full_name() or match.candidate.email} selected for position.",
                metadata={"candidate_id": str(match.candidate.id)},
            )
            return match

    @classmethod
    def mark_joined(cls, match_or_id, actor):
        match_id = match_or_id.id if hasattr(match_or_id, "id") else match_or_id
        with transaction.atomic():
            req_id = RequirementCandidateMatch.objects.filter(pk=match_id).values_list("requirement_id", flat=True).first()
            if not req_id:
                raise ValueError("Candidate match not found.")

            requirement = InstitutionRequirement.objects.select_for_update().get(pk=req_id)
            match = RequirementCandidateMatch.objects.select_for_update().get(pk=match_id)

            if match.status == RequirementCandidateMatch.MatchStatus.JOINED:
                return match  # Idempotent return

            if match.status == RequirementCandidateMatch.MatchStatus.REJECTED:
                raise CandidateStateTransitionError("Cannot mark a rejected candidate as joined.")

            if match.status not in [
                RequirementCandidateMatch.MatchStatus.INTERVIEW_SCHEDULED,
                RequirementCandidateMatch.MatchStatus.SELECTED,
            ]:
                raise CandidateStateTransitionError("Candidate must complete the required interview stage before joining.")

            # Concurrency & Overfill Protection
            if requirement.joined_count >= requirement.positions_count:
                raise CandidateStateTransitionError(f"Requirement position limit reached ({requirement.joined_count}/{requirement.positions_count} filled). Cannot mark additional candidates as joined.")

            match.status = RequirementCandidateMatch.MatchStatus.JOINED
            match.save(update_fields=["status", "updated_at"])

            RequirementActivityLog.objects.create(
                requirement=requirement,
                actor=actor,
                event_type=RequirementActivityLog.EventType.JOINED,
                description=f"Candidate {match.candidate.get_full_name() or match.candidate.email} marked as Joined.",
                metadata={"candidate_id": str(match.candidate.id)},
            )

            # Auto update requirement status if positions filled
            RequirementWorkflowService.update_fulfilled_status(requirement)
            return match

    @classmethod
    def reject_candidate(cls, match_or_id, actor, reason=""):
        match_id = match_or_id.id if hasattr(match_or_id, "id") else match_or_id
        with transaction.atomic():
            match = RequirementCandidateMatch.objects.select_for_update().get(pk=match_id)

            if match.status == RequirementCandidateMatch.MatchStatus.REJECTED:
                return match  # Idempotent return

            if match.status == RequirementCandidateMatch.MatchStatus.JOINED:
                raise CandidateStateTransitionError("Cannot reject a candidate who has already joined.")

            match.status = RequirementCandidateMatch.MatchStatus.REJECTED
            match.rejection_reason = reason
            match.save(update_fields=["status", "rejection_reason", "updated_at"])

            RequirementActivityLog.objects.create(
                requirement=match.requirement,
                actor=actor,
                event_type=RequirementActivityLog.EventType.STATUS_CHANGED,
                description=f"Candidate {match.candidate.get_full_name() or match.candidate.email} rejected. Reason: {reason}".strip(),
                metadata={"candidate_id": str(match.candidate.id)},
            )
            return match

