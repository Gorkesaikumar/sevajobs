"""
Django forms for the server-rendered authentication flows.

These back the Bootstrap-5 templates via crispy-forms and mirror the validation
performed by the DRF serializers, so both API and template clients enforce the
same rules.
"""

from __future__ import annotations

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.core.validators import RegexValidator
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from .models import User

phone_validator = RegexValidator(
    regex=r"^\+?[1-9]\d{7,14}$",
    message="Enter a valid phone number in E.164 format, e.g. +919876543210.",
)


class _CrispyForm(forms.Form):
    """Base form wiring crispy-forms with a default submit button."""

    submit_label = "Submit"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.add_input(Submit("submit", self.submit_label, css_class="btn btn-primary w-100"))


class UserRegistrationForm(forms.ModelForm):
    """Registration form with password confirmation and strength validation."""

    submit_label = "Create account"

    password1 = forms.CharField(label="Password", strip=False, widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm password", strip=False, widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ["email", "first_name", "last_name", "phone", "role"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Admins cannot self-register through the public form.
        self.fields["role"].choices = [
            (User.Role.JOB_SEEKER, "Job Seeker"),
            (User.Role.RECRUITER, "Recruiter"),
        ]
        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.add_input(Submit("submit", self.submit_label, css_class="btn btn-primary w-100"))

    def clean_email(self) -> str:
        email = self.cleaned_data["email"].lower().strip()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email

    def clean_password2(self) -> str:
        p1 = self.cleaned_data.get("password1")
        p2 = self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("The two password fields do not match.")
        password_validation.validate_password(p2)
        return p2

    def save(self, commit: bool = True) -> User:
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class EmailLoginForm(AuthenticationForm):
    """Email + password login (re-labels the default username field)."""

    username = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"autofocus": True}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.add_input(Submit("submit", "Log in", css_class="btn btn-primary w-100"))


class PhoneLoginForm(_CrispyForm):
    """Phone + password login."""

    submit_label = "Log in"

    phone = forms.CharField(label="Phone", validators=[phone_validator])
    password = forms.CharField(strip=False, widget=forms.PasswordInput)

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        phone = cleaned.get("phone")
        password = cleaned.get("password")
        if phone and password:
            user = User.objects.filter(phone=phone).first()
            if user is None or not user.check_password(password):
                raise forms.ValidationError("Invalid phone number or password.")
            if not user.is_active:
                raise forms.ValidationError("This account is inactive.")
            self.user_cache = user
        return cleaned

    def get_user(self) -> User | None:
        return self.user_cache


class PasswordResetRequestForm(_CrispyForm):
    """Collects the email address to send a reset link to."""

    submit_label = "Send reset link"
    email = forms.EmailField(label="Email")


class SetNewPasswordForm(_CrispyForm):
    """Sets a new password after a valid reset token."""

    submit_label = "Set new password"
    new_password1 = forms.CharField(label="New password", strip=False, widget=forms.PasswordInput)
    new_password2 = forms.CharField(label="Confirm new password", strip=False, widget=forms.PasswordInput)

    def clean_new_password2(self) -> str:
        p1 = self.cleaned_data.get("new_password1")
        p2 = self.cleaned_data.get("new_password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("The two password fields do not match.")
        password_validation.validate_password(p2)
        return p2


class ChangePasswordForm(_CrispyForm):
    """Authenticated password change."""

    submit_label = "Change password"
    old_password = forms.CharField(label="Current password", strip=False, widget=forms.PasswordInput)
    new_password1 = forms.CharField(label="New password", strip=False, widget=forms.PasswordInput)
    new_password2 = forms.CharField(label="Confirm new password", strip=False, widget=forms.PasswordInput)

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_old_password(self) -> str:
        old = self.cleaned_data["old_password"]
        if not self.user.check_password(old):
            raise forms.ValidationError("Your current password is incorrect.")
        return old

    def clean_new_password2(self) -> str:
        p1 = self.cleaned_data.get("new_password1")
        p2 = self.cleaned_data.get("new_password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("The two password fields do not match.")
        password_validation.validate_password(p2, self.user)
        return p2
