from django.contrib import admin
from .models import Department, TicketCategory


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "order", "is_active")
    list_editable = ("order", "is_active")
    search_fields = ("name", "code")
    ordering = ("order", "name")


@admin.register(TicketCategory)
class TicketCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "department", "icon", "is_active", "order")
    list_filter = ("department", "is_active")
    search_fields = ("name", "department__name")
    list_editable = ("is_active", "order")
    ordering = ("department", "order", "name")
