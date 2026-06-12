"""Project-wide DRF permission classes."""

from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsJobSeeker(BasePermission):
    """Grants access only to users with the job_seeker role."""

    def has_permission(self, request, view) -> bool:
        if not (request.user and request.user.is_authenticated):
            return False
        if hasattr(request.auth, 'get') and request.auth.get("role") != "job_seeker":
            # For JWT tokens, enforce role claim
            return False
        return request.user.role == "job_seeker"


class IsRecruiter(BasePermission):
    """Grants access only to users with the recruiter role."""

    def has_permission(self, request, view) -> bool:
        if not (request.user and request.user.is_authenticated):
            return False
        if hasattr(request.auth, 'get') and request.auth.get("role") != "recruiter":
            # For JWT tokens, enforce role claim
            return False
        return request.user.role == "recruiter"


class IsAdmin(BasePermission):
    """Grants access only to staff / superusers."""

    def has_permission(self, request, view) -> bool:
        if not (request.user and request.user.is_authenticated):
            return False
        if hasattr(request.auth, 'get') and request.auth.get("role") != "admin":
            # For JWT tokens, enforce role claim
            return False
        return getattr(request.user, "is_admin_role", False) or request.user.is_superuser


class IsOwnerOrReadOnly(BasePermission):
    """Object-level: owner can write, others read-only."""

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in SAFE_METHODS:
            return True
        return obj.user == request.user


class IsOwner(BasePermission):
    """Object-level: only the owner has any access."""

    def has_object_permission(self, request, view, obj) -> bool:
        return obj.user == request.user


class IsRecruiterOwner(BasePermission):
    """Object-level: only the recruiter who created the object may access it."""

    def has_object_permission(self, request, view, obj) -> bool:
        return hasattr(obj, "recruiter") and obj.recruiter.user == request.user


class ReadOnly(BasePermission):
    """Allows only safe (read) HTTP methods."""

    def has_permission(self, request, view) -> bool:
        return request.method in SAFE_METHODS
