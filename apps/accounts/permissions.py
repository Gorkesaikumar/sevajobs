"""
Role-based and account-state DRF permission classes for the auth module.

These are the canonical authentication/authorization gates. App-specific
object-level checks (ownership, etc.) live in ``apps.core.permissions``.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission, SAFE_METHODS

from .models import User


class _AuthenticatedBase(BasePermission):
    """Common helper: require an authenticated, active user."""

    def _is_active_user(self, request) -> bool:
        user = getattr(request, "user", None)
        return bool(user and user.is_authenticated and user.is_active)


class IsAdmin(_AuthenticatedBase):
    """Allow only users whose role is ``admin`` (or Django staff/superuser)."""

    message = "Administrator privileges are required."

    def has_permission(self, request, view) -> bool:
        return self._is_active_user(request) and (
            request.user.role == User.Role.ADMIN or request.user.is_staff
        )


class IsJobSeeker(_AuthenticatedBase):
    """Allow only users whose role is ``job_seeker``."""

    message = "Only job seekers may perform this action."

    def has_permission(self, request, view) -> bool:
        return self._is_active_user(request) and request.user.role == User.Role.JOB_SEEKER


class IsRecruiter(_AuthenticatedBase):
    """Allow only users whose role is ``recruiter``."""

    message = "Only recruiters may perform this action."

    def has_permission(self, request, view) -> bool:
        return self._is_active_user(request) and request.user.role == User.Role.RECRUITER


class IsEmailVerified(_AuthenticatedBase):
    """Allow only users who have verified their email address."""

    message = "Please verify your email address to continue."

    def has_permission(self, request, view) -> bool:
        return self._is_active_user(request) and request.user.is_email_verified


class IsSelf(BasePermission):
    """Object-level: the object *is* the requesting user (or owned via ``user``)."""

    message = "You may only act on your own account."

    def has_object_permission(self, request, view, obj) -> bool:
        if obj == request.user:
            return True
        return getattr(obj, "user_id", None) == request.user.id


class HasAnyRole(BasePermission):
    """
    Generic role gate driven by a ``required_roles`` attribute on the view.

    Example::

        class MyView(APIView):
            permission_classes = [HasAnyRole]
            required_roles = (User.Role.RECRUITER, User.Role.ADMIN)
    """

    message = "Your account role is not permitted to access this resource."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated and user.is_active):
            return False
        required = getattr(view, "required_roles", ())
        return not required or user.role in required


class IsAdminOrReadOnly(BasePermission):
    """Write access for admins; read access for everyone."""

    def has_permission(self, request, view) -> bool:
        if request.method in SAFE_METHODS:
            return True
        user = getattr(request, "user", None)
        return bool(
            user and user.is_authenticated and (user.role == User.Role.ADMIN or user.is_staff)
        )
