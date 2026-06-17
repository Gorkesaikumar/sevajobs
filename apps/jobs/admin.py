from django.contrib import admin
from .models import (
    Job, JobCategory, Skill, Qualification, JobApprovalHistory,
    JobContactVisibility, ContactVisibilityConfig,
)
from .services import JobService
from .visibility_services import ContactVisibilityService


@admin.register(ContactVisibilityConfig)
class ContactVisibilityConfigAdmin(admin.ModelAdmin):
    list_display = ["default_visibility_days", "is_globally_disabled", "updated_by", "updated_at"]
    readonly_fields = ["id", "updated_by", "created_at", "updated_at"]

    def has_add_permission(self, request) -> bool:
        # Singleton — only one row allowed.
        return not ContactVisibilityConfig.objects.exists()

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(JobContactVisibility)
class JobContactVisibilityAdmin(admin.ModelAdmin):
    list_display = ["job", "state", "expires_at", "overridden_by", "last_changed_at"]
    list_filter = ["state"]
    search_fields = ["job__title"]
    readonly_fields = ["id", "job", "last_changed_at", "created_at", "updated_at"]
    actions = ["force_show_action", "force_hide_action", "reset_to_auto_action"]

    @admin.action(description="Force show recruiter contact")
    def force_show_action(self, request, queryset):
        svc = ContactVisibilityService()
        for vis in queryset.select_related("job"):
            svc.force_show(vis.job, request.user, reason="Bulk admin action.")

    @admin.action(description="Force hide recruiter contact")
    def force_hide_action(self, request, queryset):
        svc = ContactVisibilityService()
        for vis in queryset.select_related("job"):
            svc.force_hide(vis.job, request.user, reason="Bulk admin action.")

    @admin.action(description="Reset to AUTO (clear override)")
    def reset_to_auto_action(self, request, queryset):
        svc = ContactVisibilityService()
        for vis in queryset.select_related("job"):
            svc.reset_to_auto(vis.job, request.user)


@admin.register(JobApprovalHistory)
class JobApprovalHistoryAdmin(admin.ModelAdmin):
    list_display = ["job", "action", "actor", "created_at"]
    list_filter = ["action"]
    search_fields = ["job__title", "actor__email", "comment"]
    readonly_fields = ["id", "job", "action", "actor", "comment", "created_at", "updated_at"]
    ordering = ["-created_at"]

    def has_add_permission(self, request) -> bool:
        return False


@admin.register(JobCategory)
class JobCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "parent", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "category", "is_active"]
    list_filter = ["category", "is_active"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Qualification)
class QualificationAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "level", "is_active"]
    list_filter = ["level", "is_active"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = [
        "title", "company", "status", "approval_status", "is_featured",
        "deadline", "views_count", "created_at",
    ]
    list_filter = ["status", "approval_status", "is_featured", "job_type", "experience_level", "is_remote"]
    search_fields = ["title", "location", "company__name"]
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = [
        "id", "views_count", "applications_count", "published_at",
        "reviewed_by", "reviewed_at", "created_at", "updated_at",
    ]
    filter_horizontal = ["preferred_qualifications"]
    autocomplete_fields = ["company", "recruiter", "category", "minimum_qualification"]
    actions = ["approve_jobs", "reject_jobs", "feature_jobs", "expire_jobs"]

    @admin.action(description="Approve & publish selected jobs")
    def approve_jobs(self, request, queryset):
        svc = JobService()
        for job in queryset:
            svc.approve_job(job, request.user)

    @admin.action(description="Reject selected jobs")
    def reject_jobs(self, request, queryset):
        svc = JobService()
        for job in queryset:
            svc.reject_job(job, request.user, reason="Rejected via admin bulk action.")

    @admin.action(description="Mark selected jobs as featured")
    def feature_jobs(self, request, queryset):
        queryset.update(is_featured=True)

    @admin.action(description="Expire selected jobs")
    def expire_jobs(self, request, queryset):
        queryset.update(status=Job.Status.EXPIRED)
