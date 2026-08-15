from django.urls import path

from . import views


app_name = "reports"

urlpatterns = [
    path("", views.reports_index_view, name="index"),
    path("tickets/", views.ticket_report_view, name="tickets"),
    path("inventario/", views.inventory_report_view, name="inventory"),
    path("impresion/", views.printing_report_view, name="printing"),
]
