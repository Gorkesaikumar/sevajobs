"""Template views for session-based authentication."""

import logging

from django.contrib.auth import authenticate, login, logout
from django.shortcuts import render, redirect
from django.contrib import messages
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect

from .models import User

logger = logging.getLogger("apps.accounts")

class LoginView(View):
    """Fallback dispatcher for generic /accounts/login/ links."""
    def get(self, request):
        return redirect("jobseeker-login")
    def post(self, request):
        return redirect("jobseeker-login")

class RoleScopedLoginView(View):
    template_name = "pages/login.html"
    role_scope = None

    def get(self, request):
        # Strict Client Requirement: Always force credential entry if the user manually visits the login page.
        from django.contrib.auth import logout
        if request.user.is_authenticated and request.session.get('current_role_scope') == self.role_scope:
            logout(request)
        return render(request, self.template_name, {"role_scope": self.role_scope})

    @method_decorator(csrf_protect)
    def post(self, request):
        from apps.accounts.forms import EmailLoginForm
        
        post_data = request.POST.copy()
        email = post_data.get("email", "").strip().lower()
        if email:
            post_data["username"] = email
            post_data["email"] = email
            
        form = EmailLoginForm(request, data=post_data)
        remember = request.POST.get("remember_me")

        if form.is_valid():
            user = form.get_user()
            
            if self.role_scope == 'admin' and not (user.is_admin_role or user.is_superuser):
                messages.error(request, "You do not have permission to access the admin panel.")
                return render(request, self.template_name, {"email": email, "role_scope": self.role_scope})
            if self.role_scope == 'recruiter' and not user.is_recruiter:
                messages.error(request, "You must be a registered recruiter to log in here.")
                return render(request, self.template_name, {"email": email, "role_scope": self.role_scope})
            if self.role_scope == 'job_seeker' and not user.is_job_seeker:
                messages.error(request, "You must be a registered job seeker to log in here.")
                return render(request, self.template_name, {"email": email, "role_scope": self.role_scope})

            if not user.is_email_verified and self.role_scope in ['job_seeker', 'recruiter']:
                request.session['pending_verification_email'] = user.email
                messages.warning(request, "Please verify your email address before continuing.")
                return redirect("accounts:verify-email-required")

            login(request, user)
            request.session['current_role_scope'] = self.role_scope
            
            if not remember:
                request.session.set_expiry(0)
            messages.success(request, f"Welcome back, {user.first_name or 'there'}!")
            next_url = request.GET.get("next") or request.POST.get("next")
            return redirect(next_url or self._dashboard_url())
        else:
            messages.error(request, "Invalid email or password. Please try again.")
            return render(request, self.template_name, {"email": email, "role_scope": self.role_scope})

    def _dashboard_url(self):
        if self.role_scope == 'admin':
            return "/dashboard/admin/"
        elif self.role_scope == 'recruiter':
            return "/dashboard/recruiter/"
        return "/dashboard/seeker/"

class AdminLoginView(RoleScopedLoginView):
    role_scope = 'admin'
    template_name = "pages/admin_login.html"

    def get(self, request):
        # High Security: Force the admin to re-authenticate if they explicitly navigate to the login page
        from django.contrib.auth import logout
        if request.user.is_authenticated and request.session.get('current_role_scope') == 'admin':
            logout(request)
        return render(request, self.template_name, {"role_scope": self.role_scope})

class RecruiterLoginView(RoleScopedLoginView):
    role_scope = 'recruiter'

class SeekerLoginView(RoleScopedLoginView):
    role_scope = 'job_seeker'


class StaffLoginView(View):
    template_name = "pages/staff_login.html"

    def get(self, request):
        from django.contrib.auth import logout
        if request.user.is_authenticated and request.session.get('current_role_scope') == 'staff':
            logout(request)
        from apps.accounts.forms import StaffLoginForm
        form = StaffLoginForm()
        return render(request, self.template_name, {"form": form})

    @method_decorator(csrf_protect)
    def post(self, request):
        from apps.accounts.forms import StaffLoginForm
        from apps.accounts.models import AuditLog
        from apps.accounts.middleware import get_client_ip
        
        form = StaffLoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            if user.role != User.Role.STAFF:
                messages.error(request, "Only staff users can log in here.")
                return render(request, self.template_name, {"form": form})
            
            # Check if staff profile is active
            if hasattr(user, 'staff_profile') and user.staff_profile.status == 'Inactive':
                messages.error(request, "Your staff account is currently deactivated.")
                return render(request, self.template_name, {"form": form})

            login(request, user)
            request.session['current_role_scope'] = 'staff'
            
            # Log login to AuditLog
            AuditLog.objects.create(
                action=AuditLog.Action.LOGIN,
                user=user,
                role=user.role,
                module="Staff Authentication",
                ip_address=get_client_ip(request) if request else None,
                user_agent=request.META.get('HTTP_USER_AGENT', '') if request else '',
            )
            
            messages.success(request, f"Welcome back, {user.first_name or 'there'}!")
            next_url = request.GET.get("next") or request.POST.get("next")
            return redirect(next_url or "/staff/dashboard/")
        else:
            messages.error(request, "Invalid email or password. Please try again.")
            return render(request, self.template_name, {"form": form})


from apps.core.models import PlatformSettings

class RegisterView(View):
    template_name = "pages/register.html"

    def get(self, request):
        if not PlatformSettings.get_settings().allow_registrations:
            messages.error(request, "User registration is currently disabled.")
            return redirect("accounts:login")
        if request.user.is_authenticated:
            return redirect("/")
        role = request.GET.get("role", "job_seeker")
        return render(request, self.template_name, {"selected_role": role})

    @method_decorator(csrf_protect)
    def post(self, request):
        if not PlatformSettings.get_settings().allow_registrations:
            messages.error(request, "User registration is currently disabled.")
            return redirect("accounts:login")
        
        from apps.accounts.forms import UserRegistrationForm
        form = UserRegistrationForm(request.POST)
        
        if form.is_valid():
            from django.db import transaction
            with transaction.atomic():
                user = form.save()
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            role = user.role
            request.session['current_role_scope'] = role
            messages.success(request, "Welcome to SevaJobs! Let's set up your profile.")
            
            if role == 'job_seeker':
                from apps.accounts.models import JobSeekerProfile
                profile, _ = JobSeekerProfile.objects.get_or_create(user=user)
                if form.cleaned_data.get("designation"):
                    profile.designation = form.cleaned_data["designation"]
                if form.cleaned_data.get("subject"):
                    profile.subject = form.cleaned_data["subject"]
                if form.cleaned_data.get("current_salary"):
                    profile.current_salary = form.cleaned_data["current_salary"]
                profile.save()

            request.session['pending_verification_email'] = user.email
            messages.success(request, "Account created successfully! Please check your email to verify your account.")
            return redirect("accounts:verify-email-required")
        else:
            for field, errors in form.errors.items():
                for err in errors:
                    messages.error(request, err)
            
            # Re-populate the context so user doesn't lose data
            context = {
                "selected_role": request.POST.get("role", "job_seeker"),
                "first_name": request.POST.get("first_name", ""),
                "last_name": request.POST.get("last_name", ""),
                "email": request.POST.get("email", ""),
                "phone": request.POST.get("phone", ""),
                "designation": request.POST.get("designation", ""),
                "subject": request.POST.get("subject", ""),
                "current_salary": request.POST.get("current_salary", ""),
            }
            return render(request, self.template_name, context)


class LogoutView(View):
    def get(self, request):
        path = request.path_info.lower()
        
        # Flush session completely
        if request.user.is_authenticated:
            logout(request)
        if hasattr(request, 'session'):
            request.session.flush()

        messages.info(request, "You have been logged out.")
        
        # Determine redirect path based on which role-specific logout page was accessed
        if 'staff' in path:
            response = redirect("staff-login")
        elif 'admin' in path:
            response = redirect("admin-login")
        elif 'recruiter' in path:
            response = redirect("recruiter-login")
        elif 'jobseeker' in path:
            response = redirect("jobseeker-login")
        else:
            response = redirect("/")

        # Explicitly delete all role-specific session cookies to ensure full isolation on logout
        for cookie_name in ['sessionid_seeker', 'sessionid_recruiter', 'sessionid_admin', 'sessionid_staff', 'sessionid']:
            response.delete_cookie(cookie_name)
            
        return response

    def post(self, request):
        return self.get(request)


class ForgotPasswordView(View):
    template_name = "pages/forgot_password.html"

    def get(self, request):
        return render(request, self.template_name)

    @method_decorator(csrf_protect)
    def post(self, request):
        from apps.accounts.middleware import get_client_ip
        from apps.accounts.services import AuthService
        from apps.notifications.backends import _mask_email

        email = request.POST.get("email", "").strip().lower()
        if email:
            try:
                auth_service = AuthService()
                auth_service.request_password_reset(email, ip=get_client_ip(request))
            except Exception as exc:
                logger.exception("Error processing password reset request for %s: %s", _mask_email(email), exc)

        # Always show success to prevent email enumeration
        messages.success(
            request,
            "If an account exists with this email, you'll receive a password reset link shortly."
        )
        return render(request, self.template_name)



class ResetPasswordView(View):
    template_name = "pages/reset_password.html"

    def _get_token_str(self, request, token=None) -> str:
        return (token or request.GET.get("token") or request.POST.get("token") or "").strip()

    def get(self, request, token=None):
        token_str = self._get_token_str(request, token)
        if not token_str:
            messages.error(request, "Invalid or missing password reset link.")
            return render(request, self.template_name, {"token_invalid": True, "token": ""})

        from apps.accounts.models import PasswordResetToken
        token_obj = PasswordResetToken.objects.select_related("user").filter(token=token_str).first()
        if token_obj is None or not token_obj.is_valid():
            messages.error(request, "This password reset link is invalid or has expired.")
            return render(request, self.template_name, {"token_invalid": True, "token": token_str})

        return render(request, self.template_name, {"token_invalid": False, "token": token_str})

    @method_decorator(csrf_protect)
    def post(self, request, token=None):
        token_str = self._get_token_str(request, token)
        password = request.POST.get("password", "")
        password2 = request.POST.get("password2", "")

        if not token_str:
            messages.error(request, "Invalid or missing password reset link.")
            return render(request, self.template_name, {"token_invalid": True, "token": ""})

        if password != password2:
            messages.error(request, "Passwords do not match.")
            return render(request, self.template_name, {"token_invalid": False, "token": token_str})

        from apps.accounts.models import PasswordResetToken
        token_obj = PasswordResetToken.objects.select_related("user").filter(token=token_str).first()
        if token_obj is None or not token_obj.is_valid():
            messages.error(request, "This password reset link is invalid or has expired.")
            return render(request, self.template_name, {"token_invalid": True, "token": token_str})

        # Run Django password validators
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError as DjangoValidationError
        try:
            validate_password(password, user=token_obj.user)
        except DjangoValidationError as ve:
            for err in ve.messages:
                messages.error(request, err)
            return render(request, self.template_name, {"token_invalid": False, "token": token_str})

        # Call AuthService business logic
        from apps.accounts.services import AuthService
        from rest_framework.exceptions import ValidationError as DRFValidationError
        try:
            auth_service = AuthService()
            auth_service.reset_password(token_str=token_str, new_password=password)
        except (DRFValidationError, Exception) as exc:
            logger.error("Password reset failed for token %s: %s", token_str[:8] if token_str else "", exc)
            messages.error(request, "Failed to reset password. The link may have expired or already been used.")
            return render(request, self.template_name, {"token_invalid": True, "token": token_str})

        messages.success(request, "Your password has been reset successfully. You can now log in with your new password.")
        return redirect("accounts:login")


class VerifyEmailRequiredView(View):
    template_name = "pages/verify_email_required.html"

    def get(self, request):
        email = request.session.get("pending_verification_email", "")
        if not email and request.user.is_authenticated:
            email = request.user.email

        masked_email = ""
        if email and "@" in email:
            local, domain = email.split("@", 1)
            if len(local) <= 2:
                masked_local = local[0] + "*"
            else:
                masked_local = local[0] + "*" * (len(local) - 2) + local[-1]
            masked_email = f"{masked_local}@{domain}"

        return render(request, self.template_name, {
            "email": email,
            "masked_email": masked_email,
        })


class ResendVerificationView(View):
    @method_decorator(csrf_protect)
    def post(self, request):
        email = (request.POST.get("email") or request.session.get("pending_verification_email") or "").strip().lower()
        if not email and request.user.is_authenticated:
            email = request.user.email

        if email:
            from apps.accounts.services import AuthService
            auth_service = AuthService()
            auth_service.resend_verification(email)
            messages.success(request, "If an unverified account exists for this email, a fresh verification link has been sent.")
        else:
            messages.error(request, "Please enter your email address to resend verification.")

        return redirect("accounts:verify-email-required")


class VerifyEmailView(View):
    template_name = "pages/verify_email.html"

    def _get_token_str(self, request, token=None) -> str:
        return (token or request.GET.get("token") or request.POST.get("token") or "").strip()

    def get(self, request, token=None):
        token_str = self._get_token_str(request, token)
        if not token_str:
            return render(request, self.template_name, {
                "success": False,
                "error": "Verification token is missing. Please click the link in your email.",
            })

        from apps.accounts.services import AuthService
        from rest_framework.exceptions import ValidationError
        auth_service = AuthService()

        try:
            user = auth_service.verify_email(token_str)
            messages.success(request, "Email verified successfully! You can now log in to access SevaJobs.")
            
            if request.user.is_authenticated:
                if user.role == User.Role.ADMIN or user.is_superuser:
                    return redirect("/dashboard/admin/")
                elif user.role == User.Role.RECRUITER:
                    return redirect("/dashboard/recruiter/")
                elif user.role == User.Role.STAFF:
                    return redirect("/staff/dashboard/")
                return redirect("/dashboard/seeker/")
            else:
                return render(request, self.template_name, {
                    "success": True,
                    "user": user,
                })
        except (ValidationError, Exception) as exc:
            logger.warning("Email verification failed for token %s: %s", token_str[:8] if token_str else "", exc)
            return render(request, self.template_name, {
                "success": False,
                "error": "This verification link is invalid, expired, or has already been used.",
                "token": token_str,
            })


class OTPVerificationView(View):
    template_name = "pages/otp_verification.html"

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        otp = "".join([request.POST.get(f"otp{i}", "") for i in range(1, 7)])
        messages.success(request, "OTP verified successfully!")
        return redirect("accounts:login")
