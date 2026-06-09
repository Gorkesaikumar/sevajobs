from django.contrib import admin
from .models import Advertisement


@admin.register(Advertisement)
class AdvertisementAdmin(admin.ModelAdmin):
    list_display = ["title", "recruiter", "placement", "status", "starts_at", "ends_at", "impressions", "clicks"]
    list_filter = ["status", "placement"]
    search_fields = ["title", "recruiter__company_name"]
    readonly_fields = ["id", "impressions", "clicks", "created_at", "updated_at"]
    actions = ["approve_ads"]

    @admin.action(description="Approve selected advertisements")
    def approve_ads(self, request, queryset):
        queryset.update(status=Advertisement.Status.ACTIVE)
