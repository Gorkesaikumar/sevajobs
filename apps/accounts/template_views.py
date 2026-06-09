"""Template views for session-based authentication."""

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect

from .models import User


class LoginView(View):
    template_name = "pages/login.html"

    def get(self, request):
        if request.user.is_authenticated:
            return redirect(self._dashboard_url(request.user))
        return render(request, self.template_name)

    @method_decorator(csrf_protect)
    def post(self, request):
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")
        remember = request.POST.get("remember_me")

        user = authenticate(request, email=email, password=password)
        if user is not None:
            if not user.is_active:
                messages.error(request, "Your account has been deactivated. Please contact support.")
                return render(request, self.template_name)
            login(request, user)
            if not remember:
                request.session.set_expiry(0)
            messages.success(request, f"Welcome back, {user.first_name or 'there'}!")
            next_url = request.GET.get("next") or request.POST.get("next")
            return redirect(next_url or self._dashboard_url(user))
        else:
            messages.error(request, "Invalid email or password. Please try again.")
            return render(request, self.template_name, {"email": email})

    @staticmethod
    def _dashboard_url(user):
        if user.is_admin_role:
            return "/dashboard/admin/"
        elif user.is_recruiter:
            return "/dashboard/recruiter/"
        return "/dashboard/seeker/"


class RegisterView(View):
    template_name = "pages/register.html"

    def get(self, request):
        if request.user.is_authenticated:
            return redirect("/")
        role = request.GET.get("role", "job_seeker")
        return render(request, self.template_name, {"selected_role": role})

    @method_decorator(csrf_protect)
    def post(self, request):
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        email = request.POST.get("email", "").strip().lower()
        phone = request.POST.get("phone", "").strip()
        password = request.POST.get("password", "")
        password2 = request.POST.get("password2", "")
        role = request.POST.get("role", "job_seeker")

        # Validation
        errors = []
        if not all([first_name, email, password, password2]):
            errors.append("All required fields must be filled.")
        if password != password2:
            errors.append("Passwords do not match.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if User.objects.filter(email=email).exists():
            errors.append("An account with this email already exists.")

        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, self.template_name, {
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "phone": phone,
                "selected_role": role,
            })

        user = User.objects.create_user(
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            role=role,
        )
        login(request, user)
        messages.success(request, "Welcome to SevaJobs! Let's set up your profile.")
        return redirect(LoginView._dashboard_url(user))


class LogoutView(View):
    def get(self, request):
        logout(request)
        messages.info(request, "You have been logged out.")
        return redirect("/")

    def post(self, request):
        return self.get(request)


class ForgotPasswordView(View):
    template_name = "pages/forgot_password.html"

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        email = request.POST.get("email", "").strip().lower()
        # Always show success to prevent email enumeration
        messages.success(request, "If an account exists with this email, you'll receive a password reset link shortly.")
        return render(request, self.template_name)


class ResetPasswordView(View):
    template_name = "pages/reset_password.html"

    def get(self, request, token=None):
        return render(request, self.template_name, {"token": token})

    def post(self, request, token=None):
        password = request.POST.get("password", "")
        password2 = request.POST.get("password2", "")
        if password != password2:
            messages.error(request, "Passwords do not match.")
            return render(request, self.template_name, {"token": token})
        if len(password) < 8:
            messages.error(request, "Password must be at least 8 characters.")
            return render(request, self.template_name, {"token": token})
        messages.success(request, "Your password has been reset. You can now log in.")
        return redirect("accounts:login")


class VerifyEmailView(View):
    template_name = "pages/verify_email.html"

    def get(self, request, token=None):
        return render(request, self.template_name, {"success": True})


class OTPVerificationView(View):
    template_name = "pages/otp_verification.html"

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        otp = "".join([request.POST.get(f"otp{i}", "") for i in range(1, 7)])
        messages.success(request, "OTP verified successfully!")
        return redirect("accounts:login")
