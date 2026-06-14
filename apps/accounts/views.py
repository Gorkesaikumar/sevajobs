"""API views for the authentication module."""

from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from drf_spectacular.utils import extend_schema

from .serializers import (
    RegisterSerializer,
    EmailTokenObtainPairSerializer,
    PhoneLoginSerializer,
    EmailVerificationConfirmSerializer,
    ResendVerificationSerializer,
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer,
    ChangePasswordSerializer,
    UserProfileSerializer,
)
from .services import UserService, AuthService

_users = UserService()
_auth = AuthService()


def _client_ip(request) -> str | None:
    """Best-effort client IP, honouring a single proxy hop."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class _SensitiveAnonThrottle(AnonRateThrottle):
    """Tighter throttle for unauthenticated, abuse-prone endpoints."""

    scope = "auth_sensitive"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
from apps.core.models import PlatformSettings

@extend_schema(tags=["auth"])
class RegisterView(APIView):
    """POST /api/v1/auth/register/ — create a job-seeker or recruiter account."""

    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer

    def post(self, request):
        if not PlatformSettings.get_settings().allow_registrations:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Registration is currently disabled.")
            
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        data.pop("confirm_password", None)
        user = _users.register(**data)
        _auth.send_verification_email(user)
        return Response(
            {
                "user": UserProfileSerializer(user).data,
                "detail": "Registration successful. Please check your email to verify your account.",
            },
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
@extend_schema(tags=["auth"])
class EmailLoginView(TokenObtainPairView):
    """POST /api/v1/auth/login/ — obtain JWT pair using email + password."""

    permission_classes = [AllowAny]
    serializer_class = EmailTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == status.HTTP_200_OK:
            user_data = response.data.get("user")
            if user_data:
                from .models import User

                user = User.objects.filter(id=user_data["id"]).first()
                if user:
                    _users.record_login_ip(user, _client_ip(request))
        return response


@extend_schema(tags=["auth"])
class PhoneLoginView(APIView):
    """POST /api/v1/auth/login/phone/ — obtain JWT pair using phone + password."""

    permission_classes = [AllowAny]
    serializer_class = PhoneLoginSerializer

    def post(self, request):
        serializer = PhoneLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _users.record_login_ip(serializer.user, _client_ip(request))
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------
@extend_schema(tags=["auth"])
class VerifyEmailView(APIView):
    """POST /api/v1/auth/verify-email/ — confirm an email via token."""

    permission_classes = [AllowAny]
    serializer_class = EmailVerificationConfirmSerializer

    def post(self, request):
        serializer = EmailVerificationConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _auth.verify_email(serializer.validated_data["token"])
        return Response({"detail": "Email verified successfully."})


@extend_schema(tags=["auth"])
class ResendVerificationView(APIView):
    """POST /api/v1/auth/verify-email/resend/ — re-send the verification email."""

    permission_classes = [AllowAny]
    throttle_classes = [_SensitiveAnonThrottle]
    serializer_class = ResendVerificationSerializer

    def post(self, request):
        serializer = ResendVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _auth.resend_verification(serializer.validated_data["email"])
        return Response({"detail": "If the account exists and is unverified, an email has been sent."})


# ---------------------------------------------------------------------------
# Password reset (forgot password)
# ---------------------------------------------------------------------------
@extend_schema(tags=["auth"])
class PasswordResetRequestView(APIView):
    """POST /api/v1/auth/password-reset/ — request a reset link."""

    permission_classes = [AllowAny]
    throttle_classes = [_SensitiveAnonThrottle]
    serializer_class = PasswordResetRequestSerializer

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _auth.request_password_reset(serializer.validated_data["email"], ip=_client_ip(request))
        return Response({"detail": "If an account exists for that email, a reset link has been sent."})


@extend_schema(tags=["auth"])
class PasswordResetConfirmView(APIView):
    """POST /api/v1/auth/password-reset/confirm/ — set a new password via token."""

    permission_classes = [AllowAny]
    throttle_classes = [_SensitiveAnonThrottle]
    serializer_class = PasswordResetConfirmSerializer

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _auth.reset_password(
            serializer.validated_data["token"],
            serializer.validated_data["new_password"],
        )
        return Response({"detail": "Password has been reset. You may now log in."})


# ---------------------------------------------------------------------------
# Authenticated account management
# ---------------------------------------------------------------------------
@extend_schema(tags=["accounts"])
class ChangePasswordView(APIView):
    """POST /api/v1/accounts/change-password/ — change password while logged in."""

    permission_classes = [IsAuthenticated]
    serializer_class = ChangePasswordSerializer

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _users.change_password(
            user=request.user,
            old_password=serializer.validated_data["old_password"],
            new_password=serializer.validated_data["new_password"],
        )
        return Response({"detail": "Password updated successfully."})


@extend_schema(tags=["accounts"])
class MeView(APIView):
    """GET/PATCH /api/v1/accounts/me/ — read or update the current profile."""

    permission_classes = [IsAuthenticated]
    serializer_class = UserProfileSerializer

    def get(self, request):
        return Response(UserProfileSerializer(request.user).data)

    def patch(self, request):
        serializer = UserProfileSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        user = _users.update_profile(request.user, **serializer.validated_data)
        return Response(UserProfileSerializer(user).data)
