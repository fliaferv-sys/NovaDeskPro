"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.core.pwa import service_worker, web_app_manifest
from apps.core.health import health_check


urlpatterns = [
    path("health/", health_check, name="health_check"),
    path("manifest.webmanifest", web_app_manifest, name="web_app_manifest"),
    path("service-worker.js", service_worker, name="service_worker"),
    path("admin/", admin.site.urls),

    path("", include("apps.accounts.urls")),

    path(
        "monitoring/",
        include("apps.monitoring.urls"),
    ),

    path(
        "notificaciones/",
        include("apps.notifications.urls"),
    ),

    path(
        "dashboard/",
        include("apps.dashboard.urls"),
    ),

    path(
        "tickets/",
        include("apps.tickets.urls"),
    ),

    path(
        "inventario/",
        include("apps.inventory.urls"),
    ),

    path(
        "entregas/",
        include("apps.deliveries.urls"),
    ),

    path(
        "psline/",
        include("apps.printing.urls"),
    ),
]


# ==========================================================
# ARCHIVOS MEDIA EN DESARROLLO
# ==========================================================

if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )
