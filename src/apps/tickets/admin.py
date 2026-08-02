from django.contrib import admin

from .models import (
    AccessIdentityDocument,
    AuthorizationDocument,
    GeneratedAuthorizationForm,
    QuickAction,
    SystemAccessRequest,
    Ticket,
    TicketAttachment,
    TicketComment,
)


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = (
        "ticket_number",
        "title",
        "requester",
        "assigned_to",
        "status",
        "priority",
        "created_at",
    )
    list_filter = ("status", "priority", "created_at")
    search_fields = ("ticket_number", "title", "description")
    readonly_fields = ("ticket_number", "created_at", "updated_at")
    autocomplete_fields = ("requester", "assigned_to", "asset")


@admin.register(TicketComment)
class TicketCommentAdmin(admin.ModelAdmin):
    list_display = ("ticket", "author", "message", "created_at")
    list_filter = ("created_at",)
    search_fields = ("message",)
    autocomplete_fields = ("ticket", "author")


@admin.register(TicketAttachment)
class TicketAttachmentAdmin(admin.ModelAdmin):
    list_display = ("ticket", "original_name", "uploaded_by", "created_at")
    list_filter = ("created_at",)
    search_fields = ("original_name",)
    autocomplete_fields = ("ticket", "uploaded_by")


@admin.register(QuickAction)
class QuickActionAdmin(admin.ModelAdmin):
    list_display = ("title", "department", "label", "icon", "is_active", "order")
    list_filter = ("department", "is_active")
    search_fields = ("title", "description", "label")
    list_editable = ("is_active", "order")
    ordering = ("department", "order", "title")


@admin.register(SystemAccessRequest)
class SystemAccessRequestAdmin(admin.ModelAdmin):
    list_display = (
        "ticket", "affected_employee", "operation", "requested_system",
        "authorization_status", "created_at",
    )
    list_filter = ("operation", "authorization_status", "requested_system")
    search_fields = (
        "ticket__ticket_number", "affected_employee",
        "affected_document_number", "employee_number", "requested_email",
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(GeneratedAuthorizationForm)
class GeneratedAuthorizationFormAdmin(admin.ModelAdmin):
    list_display = ("access_request", "version", "generated_by", "created_at")
    readonly_fields = ("created_at",)


@admin.register(AuthorizationDocument)
class AuthorizationDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "access_request", "version", "validation_status",
        "uploaded_by", "created_at",
    )
    list_filter = ("validation_status",)
    readonly_fields = ("created_at", "updated_at", "validated_at")


@admin.register(AccessIdentityDocument)
class AccessIdentityDocumentAdmin(admin.ModelAdmin):
    list_display = ("access_request", "version", "uploaded_by", "created_at")
    readonly_fields = ("created_at",)
