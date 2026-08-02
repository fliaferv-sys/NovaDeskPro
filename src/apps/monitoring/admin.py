from django.contrib import admin
from django.utils.html import format_html

from .models import DeviceHeartbeat, DeviceIPHistory


@admin.register(DeviceHeartbeat)
class DeviceHeartbeatAdmin(admin.ModelAdmin):
    list_display = (
        "computer_name",
        "asset",
        "logged_user",
        "ip_address",
        "mac_address",
        "estado_equipo",
        "last_seen",
        "agent_version",
    )

    list_filter = (
        "operating_system",
        "agent_version",
        "last_seen",
    )

    search_fields = (
        "computer_name",
        "logged_user",
        "ip_address",
        "mac_address",
        "operating_system",
        "processor",
        "asset__internal_code",
        "asset__patrimonial_code",
        "asset__serial_number",
        "asset__brand",
        "asset__model",
    )

    autocomplete_fields = (
        "asset",
        "updated_by",
    )

    ordering = (
        "computer_name",
    )

    readonly_fields = (
        "first_seen",
        "updated_at",
    )

    fieldsets = (
        (
            "Activo y conexión",
            {
                "fields": (
                    "asset",
                    "computer_name",
                    "logged_user",
                    "ip_address",
                    "mac_address",
                    "last_seen",
                )
            },
        ),
        (
            "Información técnica",
            {
                "fields": (
                    "operating_system",
                    "processor",
                    "ram_total_gb",
                    "disk_total_gb",
                    "disk_free_gb",
                    "agent_version",
                )
            },
        ),
        (
            "Registro",
            {
                "fields": (
                    "updated_by",
                    "notes",
                )
            },
        ),
        (
            "Auditoría",
            {
                "fields": (
                    "first_seen",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    @admin.display(description="Estado")
    def estado_equipo(self, obj):
        if obj.is_online:
            return format_html(
                '<strong style="color:#198754;">{}</strong>',
                "EN LÍNEA",
            )

        return format_html(
            '<strong style="color:#dc3545;">{}</strong>',
            "FUERA DE LÍNEA",
        )

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)

@admin.register(DeviceIPHistory)
class DeviceIPHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "ip_address",
        "computer_name",
        "activo",
        "logged_user",
        "mac_address",
        "first_seen",
        "last_seen",
        "detection_count",
    )

    list_filter = (
        "first_seen",
        "last_seen",
    )

    search_fields = (
        "ip_address",
        "computer_name",
        "logged_user",
        "mac_address",
        "device__asset__internal_code",
        "device__asset__patrimonial_code",
    )

    readonly_fields = (
        "device",
        "ip_address",
        "computer_name",
        "logged_user",
        "mac_address",
        "first_seen",
        "last_seen",
        "detection_count",
    )

    ordering = (
        "-last_seen",
    )

    @admin.display(description="Activo")
    def activo(self, obj):
        return obj.device.asset.internal_code

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False        