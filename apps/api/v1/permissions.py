"""
Permission classes for the consolidated v1 REST API.

Re-exports the canonical role gates from ``apps.accounts.permissions`` and adds
a couple of resource-level helpers used by the viewsets.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission, SAFE_METHODS

from apps.accounts.permissions import (  # noqa: F401  (re-exported)
    IsAdmin,
    IsJobSeeker,
    IsRecruiter,
    IsEmailVerified,
    IsAdminOrReadOnly,
    HasAnyRole,
)


class IsOwnerOrReadOnly(BasePermission):
    """Object-level: safe methods for anyone, writes only for the owner."""

    owner_field = "user"

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in SAFE_METHODS:
            return True
        owner_id = getattr(obj, f"{self.owner_field}_id", None)
        return owner_id == request.user.id


class IsRecipient(BasePermission):
    """Object-level: only the notification's recipient may access it."""

    def has_object_permission(self, request, view, obj) -> bool:
        return getattr(obj, "recipient_id", None) == request.user.id
