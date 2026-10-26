from django.urls import path

from .views import (
    psline_dashboard,
    printing_device_detail,
    printing_devices_by_model,
    register_ticket_consumable,
)

from .inventory_users import manage_device_user

app_name = "printing"

urlpatterns = [
    path("equipo/<uuid:pk>/usuarios/", manage_device_user, name="manage_device_user"),
    path(
        "",
        psline_dashboard,
        name="dashboard",
    ),
    path(
        "equipos/",
        printing_devices_by_model,
        name="devices_by_model",
    ),
    path(
        "equipo/<uuid:pk>/",
        printing_device_detail,
        name="device_detail",
    ),
    path(
        "tickets/<uuid:ticket_pk>/registrar-consumible/",
        register_ticket_consumable,
        name="register_ticket_consumable",
    ),
]
