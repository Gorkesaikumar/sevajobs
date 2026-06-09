"""Authentication endpoints — mounted at /api/v1/auth/."""

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView, TokenBlacklistView

from apps.accounts.views import (
    RegisterView,
    EmailLoginView,
    PhoneLoginView,
    VerifyEmailView,
    ResendVerificationView,
    PasswordResetRequestView,
    PasswordResetConfirmView,
)

urlpatterns = [
    # Registration & login
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("login/", EmailLoginView.as_view(), name="auth-login"),
    path("login/phone/", PhoneLoginView.as_view(), name="auth-login-phone"),
    path("refresh/", TokenRefreshView.as_view(), name="auth-refresh"),
    path("logout/", TokenBlacklistView.as_view(), name="auth-logout"),
    # Email verification
    path("verify-email/", VerifyEmailView.as_view(), name="auth-verify-email"),
    path("verify-email/resend/", ResendVerificationView.as_view(), name="auth-verify-email-resend"),
    # Password reset
    path("password-reset/", PasswordResetRequestView.as_view(), name="auth-password-reset"),
    path("password-reset/confirm/", PasswordResetConfirmView.as_view(), name="auth-password-reset-confirm"),
]
