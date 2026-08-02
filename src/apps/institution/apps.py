from django.apps import AppConfig


class InstitutionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.institution"
    label = "institution"
    verbose_name = "Configuración institucional"