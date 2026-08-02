from django.contrib import admin

from .models import ActivityLog


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "user",
        "action",
        "module",
        "description",       
        "ip_address",
    )

    list_filter = (
        "action",
        "module",
        "object_type",
        "created_at",
    )

    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "description",
        "module",
        "object_type",
        "ip_address",
    )

    readonly_fields = (
        "user",
        "action",
        "module",
        "description",
        "object_type",
        "object_id",
        "ip_address",
        "created_at",
    )

    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False