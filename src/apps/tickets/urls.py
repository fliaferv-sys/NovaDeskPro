from django.urls import path

from .views import (
    dashboard_view,
    generate_authorization_form_view,
    ticket_create_view,
    ticket_delete_view,
    ticket_detail_view,
    ticket_conversation_status_view,
    technician_availability_status_view,
    ticket_list_view,
    ticket_update_view,
    validate_access_request_view,
    ticket_attachment_download_view,
    authorization_document_download_view,
    identity_document_download_view,
)

app_name = "tickets"

urlpatterns = [

    path("", ticket_list_view, name="ticket_list"),
    path("nuevo/", ticket_create_view, name="ticket_create"),
    path("<uuid:pk>/", ticket_detail_view, name="ticket_detail"),
    path(
        "<uuid:pk>/conversation-status/",
        ticket_conversation_status_view,
        name="ticket_conversation_status",
    ),
    path("<uuid:pk>/editar/", ticket_update_view, name="ticket_update"),
    path("<uuid:pk>/eliminar/", ticket_delete_view, name="ticket_delete"),
    path("<uuid:pk>/adjuntos/<uuid:attachment_id>/", ticket_attachment_download_view, name="attachment_download"),
    path("<uuid:pk>/autorizaciones/<uuid:document_id>/", authorization_document_download_view, name="authorization_document_download"),
    path("<uuid:pk>/identidad/<uuid:document_id>/", identity_document_download_view, name="identity_document_download"),

    path(
        "<uuid:pk>/validate-access/",
        validate_access_request_view,
        name="validate_access_request",
    ),

    path(
        "<uuid:pk>/generate-authorization-form/",
        generate_authorization_form_view,
        name="generate_authorization_form",
    ),

    path("dashboard/", dashboard_view, name="dashboard"),
    path(
        "dashboard/availability-status/",
        technician_availability_status_view,
        name="technician_availability_status",
    ),
]
