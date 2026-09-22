from django.urls import path
from . import template_views

app_name = "accounts"

urlpatterns = [
    path("login/", template_views.LoginView.as_view(), name="login"),
    path("register/", template_views.RegisterView.as_view(), name="register"),
    path("logout/", template_views.LogoutView.as_view(), name="logout"),
    path("forgot-password/", template_views.ForgotPasswordView.as_view(), name="forgot-password"),
    path("reset-password/", template_views.ResetPasswordView.as_view(), name="reset-password-query"),
    path("reset-password/<str:token>/", template_views.ResetPasswordView.as_view(), name="reset-password"),
    path("verify-email-required/", template_views.VerifyEmailRequiredView.as_view(), name="verify-email-required"),
    path("resend-verification/", template_views.ResendVerificationView.as_view(), name="resend-verification"),
    path("verify-email/", template_views.VerifyEmailView.as_view(), name="verify-email-query"),
    path("verify-email/<str:token>/", template_views.VerifyEmailView.as_view(), name="verify-email"),
    path("otp-verify/", template_views.OTPVerificationView.as_view(), name="otp-verify"),
]
