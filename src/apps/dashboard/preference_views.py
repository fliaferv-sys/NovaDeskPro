# ==========================================================
# PREFERENCIAS DEL DASHBOARD
# NOVADESK PRO
# SPRINT 18
# ==========================================================

import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .models import DashboardPreference


# ==========================================================
# GUARDAR PREFERENCIAS
# ==========================================================

@login_required
@require_POST
def save_dashboard_preference_view(request):
    """
    Guarda la distribución de widgets y los tipos de gráficos
    del usuario autenticado.
    """

    try:
        payload = json.loads(
            request.body.decode("utf-8")
        )

    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
    ):
        return JsonResponse(
            {
                "success": False,
                "message": (
                    "Los datos recibidos no tienen "
                    "un formato JSON válido."
                ),
            },
            status=400,
        )

    layout = payload.get(
        "layout",
        [],
    )

    chart_types = payload.get(
        "chart_types",
        {},
    )

    if not isinstance(layout, list):
        return JsonResponse(
            {
                "success": False,
                "message": (
                    "La distribución del dashboard "
                    "debe ser una lista."
                ),
            },
            status=400,
        )

    if not isinstance(chart_types, dict):
        return JsonResponse(
            {
                "success": False,
                "message": (
                    "Los tipos de gráficos deben "
                    "tener formato de objeto."
                ),
            },
            status=400,
        )

    preference, created = (
        DashboardPreference.objects.update_or_create(
            user=request.user,
            defaults={
                "layout": layout,
                "chart_types": chart_types,
            },
        )
    )

    return JsonResponse(
        {
            "success": True,
            "created": created,
            "message": (
                "El diseño del dashboard fue "
                "guardado correctamente."
            ),
            "updated_at": (
                preference.updated_at.isoformat()
            ),
        }
    )


# ==========================================================
# RESTAURAR PREFERENCIAS
# ==========================================================

@login_required
@require_POST
def reset_dashboard_preference_view(request):
    """
    Elimina la configuración personalizada del usuario
    y permite volver al diseño original.
    """

    deleted_count, _ = (
        DashboardPreference.objects.filter(
            user=request.user
        ).delete()
    )

    return JsonResponse(
        {
            "success": True,
            "deleted": deleted_count > 0,
            "message": (
                "El dashboard fue restaurado "
                "a su diseño original."
            ),
        }
    )