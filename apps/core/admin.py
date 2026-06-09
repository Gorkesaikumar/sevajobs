from django.contrib import admin
from .models import ActivityLog


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "action", "entity_type", "entity_id", "user", "ip_address"]
    list_filter = ["action", "entity_type"]
    search_fields = ["entity_id", "description", "user__email"]
    readonly_fields = [
        "id", "user", "action", "entity_type", "entity_id",
        "description", "metadata", "ip_address", "user_agent", "created_at",
    ]
    ordering = ["-created_at"]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
