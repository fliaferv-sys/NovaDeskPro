# ==========================================================
# CONTEXT PROCESSOR INSTITUCIONAL
# NOVADESK PRO — SPRINT 19.5
# ==========================================================

from .models import InstitutionSettings


def institution_settings(request):
    """
    Hace que la configuración institucional activa esté
    disponible automáticamente en todas las plantillas.

    Uso en templates:
        {{ institution.system_name }}
        {{ institution.logo.url }}
        {{ institution.primary_color }}
    """

    institution = InstitutionSettings.get_active()

    return {
        "institution": institution,
    }