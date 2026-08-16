from django.urls import path

from .preference_views import (
    reset_dashboard_preference_view,
    save_dashboard_preference_view,
)
from .views import (
    executive_dashboard_view,
    department_dashboard_view,  # ⬅️ NUEVA IMPORTACIÓN
    resolve_technician_request_view,
    technician_control_view,
)


app_name = "dashboard"


urlpatterns = [
    path(
        "",
        executive_dashboard_view,
        name="executive_dashboard",
    ),

    path(
        "departamento/",  # ⬅️ NUEVA URL
        department_dashboard_view,
        name="department_dashboard",
    ),
    path(
        "control-tecnicos/",
        technician_control_view,
        name="technician_control",
    ),
    path(
        "control-tecnicos/solicitudes/<int:pk>/resolver/",
        resolve_technician_request_view,
        name="resolve_technician_request",
    ),

    path(
        "preferencias/guardar/",
        save_dashboard_preference_view,
        name="save_preference",
    ),

    path(
        "preferencias/restaurar/",
        reset_dashboard_preference_view,
        name="reset_preference",
    ),
]
