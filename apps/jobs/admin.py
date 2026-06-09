from django.contrib import admin
from .models import Job, JobCategory, Skill, Qualification, JobApprovalHistory
from .services import JobService


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
    filter_horizontal = ["skills_required", "preferred_qualifications"]
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
