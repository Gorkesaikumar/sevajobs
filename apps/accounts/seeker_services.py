"""Business logic for the job-seeker module."""

from __future__ import annotations

import logging
import os
from typing import Optional

from django.db import transaction
from django.db.models import ProtectedError, QuerySet
from rest_framework.exceptions import ValidationError

from .models import JobSeekerProfile, Resume, User

logger = logging.getLogger("apps.accounts")

#: Resume upload constraints.
MAX_RESUME_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_RESUME_EXTENSIONS = {".pdf", ".doc", ".docx", ".rtf", ".odt"}


class ProfileService:
    """Create and update the one-to-one seeker profile."""

    @staticmethod
    def get_or_create(user: User) -> JobSeekerProfile:
        profile, _ = JobSeekerProfile.objects.get_or_create(user=user)
        return profile

    @transaction.atomic
    def update(
        self,
        profile: JobSeekerProfile,
        *,
        user_fields: Optional[dict] = None,
        profile_fields: Optional[dict] = None,
        skills=None,
        qualifications=None,
    ) -> JobSeekerProfile:
        if user_fields:
            user = profile.user
            for attr, value in user_fields.items():
                setattr(user, attr, value)
            user.save(update_fields=list(user_fields.keys()))

        if profile_fields:
            for attr, value in profile_fields.items():
                setattr(profile, attr, value)
            profile.save()

        if skills is not None:
            profile.skills.set(skills)
        if qualifications is not None:
            profile.qualifications.set(qualifications)

        return profile


class ResumeService:
    """Manage a seeker's multiple resume documents."""

    @staticmethod
    def list_for(user: User) -> QuerySet[Resume]:
        return Resume.objects.filter(job_seeker=user).order_by("-is_primary", "-created_at")

    @transaction.atomic
    def upload(self, user: User, *, title: str, file, is_primary: bool = False) -> Resume:
        self._validate_file(file)
        ext = os.path.splitext(file.name)[1].lower().lstrip(".")
        # The very first resume is primary by default.
        first_resume = not Resume.objects.filter(job_seeker=user).exists()
        make_primary = is_primary or first_resume

        resume = Resume.objects.create(
            job_seeker=user,
            title=title,
            file=file,
            is_primary=make_primary,
            file_size=getattr(file, "size", 0) or 0,
            file_type=ext,
        )
        if make_primary:
            self._demote_others(user, keep=resume.pk)
        logger.info("Resume %s uploaded by %s", resume.pk, user.email)
        return resume

    @transaction.atomic
    def set_primary(self, resume: Resume) -> Resume:
        if not resume.is_primary:
            resume.is_primary = True
            resume.save(update_fields=["is_primary"])
        self._demote_others(resume.job_seeker, keep=resume.pk)
        return resume

    def delete(self, resume: Resume) -> None:
        was_primary = resume.is_primary
        owner = resume.job_seeker
        try:
            resume.delete()
        except ProtectedError:
            raise ValidationError(
                {"detail": "This resume is attached to an existing application and cannot be deleted."}
            )
        # Promote another resume to primary if we removed the primary one.
        if was_primary:
            replacement = Resume.objects.filter(job_seeker=owner).order_by("-created_at").first()
            if replacement:
                replacement.is_primary = True
                replacement.save(update_fields=["is_primary"])

    @staticmethod
    def _demote_others(user: User, *, keep) -> None:
        Resume.objects.filter(job_seeker=user, is_primary=True).exclude(pk=keep).update(is_primary=False)

    @staticmethod
    def _validate_file(file) -> None:
        size = getattr(file, "size", 0) or 0
        if size > MAX_RESUME_BYTES:
            raise ValidationError({"file": "Resume must not exceed 5 MB."})
        ext = os.path.splitext(file.name)[1].lower()
        if ext not in ALLOWED_RESUME_EXTENSIONS:
            allowed = ", ".join(sorted(ALLOWED_RESUME_EXTENSIONS))
            raise ValidationError({"file": f"Unsupported file type. Allowed: {allowed}."})
