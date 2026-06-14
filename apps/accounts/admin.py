from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import (
    User,
    JobSeekerProfile,
    Resume,
    EmailVerificationToken,
    PasswordResetToken,
)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ["email", "full_name", "role", "is_active", "is_email_verified", "date_joined"]
    list_filter = ["role", "is_active", "is_staff", "is_email_verified"]
    search_fields = ["email", "first_name", "last_name"]
    ordering = ["-date_joined"]
    readonly_fields = ["id", "date_joined", "last_login", "created_at", "updated_at"]

    fieldsets = (
        (None, {"fields": ("id", "email", "password")}),
        ("Personal Info", {"fields": ("first_name", "last_name", "phone", "avatar")}),
        ("Role & Status", {"fields": ("role", "is_active", "is_email_verified", "is_staff", "is_superuser")}),
        ("Timestamps", {"fields": ("date_joined", "last_login", "created_at", "updated_at")}),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "first_name", "last_name", "role", "password1", "password2"),
        }),
    )


@admin.register(JobSeekerProfile)
class JobSeekerProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "designation", "subject", "current_salary", "experience_years", "availability", "is_open_to_work"]
    list_filter = ["availability", "is_open_to_work", "gender"]
    search_fields = ["user__email", "user__phone", "user__first_name", "user__last_name", "headline", "designation", "subject"]
    readonly_fields = ["id", "created_at", "updated_at"]
    filter_horizontal = ["skills", "qualifications"]


@admin.register(Resume)
class ResumeAdmin(admin.ModelAdmin):
    list_display = ["title", "job_seeker", "is_primary", "file_type", "created_at"]
    list_filter = ["is_primary", "file_type"]
    search_fields = ["title", "job_seeker__email"]
    readonly_fields = ["id", "created_at", "updated_at"]


class _BaseTokenAdmin(admin.ModelAdmin):
    list_display = ["user", "expires_at", "used_at", "created_at"]
    search_fields = ["user__email"]
    readonly_fields = ["id", "user", "token", "expires_at", "used_at", "created_at", "updated_at"]
    ordering = ["-created_at"]

    def has_add_permission(self, request) -> bool:
        return False


@admin.register(EmailVerificationToken)
class EmailVerificationTokenAdmin(_BaseTokenAdmin):
    pass


@admin.register(PasswordResetToken)
class PasswordResetTokenAdmin(_BaseTokenAdmin):
    list_display = ["user", "requested_ip", "expires_at", "used_at", "created_at"]
