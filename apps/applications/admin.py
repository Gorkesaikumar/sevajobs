from django.contrib import admin
from .models import JobApplication, ApplicationStatusHistory, SavedJob


class ApplicationStatusHistoryInline(admin.TabularInline):
    model = ApplicationStatusHistory
    extra = 0
    readonly_fields = ["from_status", "to_status", "changed_by", "note", "created_at"]
    can_delete = False


@admin.register(JobApplication)
class JobApplicationAdmin(admin.ModelAdmin):
    list_display = ["applicant", "job", "status", "applied_at"]
    list_filter = ["status"]
    search_fields = ["applicant__email", "job__title"]
    readonly_fields = ["id", "applied_at", "created_at", "updated_at"]
    autocomplete_fields = ["job", "applicant", "resume"]
    inlines = [ApplicationStatusHistoryInline]


@admin.register(SavedJob)
class SavedJobAdmin(admin.ModelAdmin):
    list_display = ["user", "job", "created_at"]
    search_fields = ["user__email", "job__title"]
    readonly_fields = ["id", "created_at", "updated_at"]
    autocomplete_fields = ["user", "job"]
