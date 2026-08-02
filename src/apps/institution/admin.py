from django.contrib import admin

from .models import InstitutionSettings


@admin.register(InstitutionSettings)
class InstitutionSettingsAdmin(admin.ModelAdmin):

    list_display = (
        "system_name",
        "institution_name",
        "city",
        "country",
        "default_theme",
        "is_active",
    )

    list_filter = (
        "default_theme",
        "country",
        "is_active",
    )

    search_fields = (
        "system_name",
        "institution_name",
        "institution_short_name",
        "department_name",
        "city",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    fieldsets = (

        (
            "🖥 Sistema",
            {
                "fields": (
                    "system_name",
                    "system_short_name",
                    "system_slogan",
                )
            },
        ),

        (
            "🏢 Institución",
            {
                "fields": (
                    "institution_name",
                    "institution_short_name",
                    "department_name",
                )
            },
        ),

        (
            "🎨 Identidad visual",
            {
                "fields": (
                    "logo",
                    "dark_logo",
                    "compact_logo",
                    "favicon",
                    "login_image",
                    "dashboard_image",
                    "admin_logo",
                    "user_portal_logo",
                    "monitoring_logo",
                    "header_image",
                )
            },
        ),

        (
            "🌙 Apariencia",
            {
                "fields": (
                    "default_theme",
                    "allow_user_theme_change",
                    "primary_color",
                    "secondary_color",
                    "accent_color",
                    "success_color",
                    "warning_color",
                    "danger_color",
                )
            },
        ),

        (
            "🌎 Configuración regional",
            {
                "fields": (
                    "timezone_name",
                    "date_format",
                    "currency_code",
                )
            },
        ),

        (
            "☎ Contacto",
            {
                "fields": (
                    "address",
                    "city",
                    "country",
                    "phone",
                    "email",
                    "website",
                )
            },
        ),

        (
            "📄 Documentos y Reportes",
            {
                "fields": (
                    "director_name",
                    "document_code",
                    "show_logo_in_pdf",
                    "show_header_in_pdf",
                    "footer_text",
                )
            },
        ),

        (
            "⚙ Estado",
            {
                "fields": (
                    "is_active",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )