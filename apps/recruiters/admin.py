from django.contrib import admin
from .models import Company, RecruiterProfile


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ["name", "industry", "size", "is_verified", "created_at"]
    list_filter = ["is_verified", "size", "industry"]
    search_fields = ["name", "email"]
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ["id", "created_at", "updated_at"]
    actions = ["verify_companies"]

    @admin.action(description="Mark selected companies as verified")
    def verify_companies(self, request, queryset):
        queryset.update(is_verified=True)


@admin.register(RecruiterProfile)
class RecruiterProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "company", "designation", "is_verified", "created_at"]
    list_filter = ["is_verified", "is_primary_contact"]
    search_fields = ["user__email", "company__name"]
    readonly_fields = ["id", "created_at", "updated_at"]
