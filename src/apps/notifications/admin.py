from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "recipient",
        "notification_type",
        "level",
        "is_read",
        "is_active",
        "created_at",
    )

    list_filter = (
        "notification_type",
        "level",
        "is_read",
        "is_active",
        "created_at",
    )

    search_fields = (
        "title",
        "message",
        "recipient__username",
        "recipient__email",
        "object_type",
        "object_id",
        "unique_key",
    )

    autocomplete_fields = (
        "recipient",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
        "read_at",
    )

    ordering = (
        "-created_at",
    )

    fieldsets = (
        (
            "Destinatario",
            {
                "fields": (
                    "recipient",
                )
            },
        ),
        (
            "Contenido",
            {
                "fields": (
                    "notification_type",
                    "level",
                    "title",
                    "message",
                    "link",
                )
            },
        ),
        (
            "Objeto relacionado",
            {
                "fields": (
                    "object_type",
                    "object_id",
                    "unique_key",
                )
            },
        ),
        (
            "Estado",
            {
                "fields": (
                    "is_read",
                    "is_active",
                    "read_at",
                )
            },
        ),
        (
            "Auditoría",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    actions = (
        "mark_selected_as_read",
        "mark_selected_as_unread",
        "deactivate_selected",
        "activate_selected",
    )

    @admin.action(description="Marcar seleccionadas como leídas")
    def mark_selected_as_read(self, request, queryset):
        for notification in queryset:
            notification.mark_as_read()

    @admin.action(description="Marcar seleccionadas como no leídas")
    def mark_selected_as_unread(self, request, queryset):
        for notification in queryset:
            notification.mark_as_unread()

    @admin.action(description="Desactivar notificaciones seleccionadas")
    def deactivate_selected(self, request, queryset):
        queryset.update(is_active=False)

    @admin.action(description="Activar notificaciones seleccionadas")
    def activate_selected(self, request, queryset):
        queryset.update(is_active=True)