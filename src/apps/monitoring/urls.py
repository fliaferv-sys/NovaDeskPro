from django.urls import path

from .views import (
    device_detail,
    ip_history_list,
    monitoring_dashboard,
    receive_heartbeat,
)


app_name = "monitoring"


urlpatterns = [
    path(
        "",
        monitoring_dashboard,
        name="dashboard",
    ),
    path(
        "historial-ip/",
        ip_history_list,
        name="ip_history",
    ),
    path(
        "equipo/<uuid:pk>/",
        device_detail,
        name="device_detail",
    ),
    path(
        "api/heartbeat/",
        receive_heartbeat,
        name="receive_heartbeat",
    ),
]