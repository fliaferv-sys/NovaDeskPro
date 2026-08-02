
from django.urls import path
from .pdf_views import delivery_batch_pdf_view

from .views import (
    custody_movement_create_view,
    custody_movement_detail_view,
    custody_movement_list_view,
    custody_movement_update_view,
    custody_movement_pdf_view,
    send_selected_assets_to_custody_view,
    group_selected_custody_movements_view,

    delivery_batch_create_view,
    delivery_batch_configure_view,
    delivery_batch_detail_view,
    delivery_batch_list_view,
    upload_delivery_batch_document_view,
    delivery_batch_prepare_view,
    delivery_batch_send_to_signature_view,
    delivery_batch_complete_view,

    mark_movement_delivered_view,
    revert_movement,

    marcar_preparado,
    enviar_a_firma,

    upload_delivery_document_view,
    replace_delivery_document_view,
    delete_delivery_document_view,
    delivery_document_download_view,
    delivery_batch_document_download_view,
    movement_private_file_view,
)

app_name = "deliveries"

urlpatterns = [

    # ACTAS
    path("actas/", delivery_batch_list_view, name="delivery_batch_list"),
    path("actas/nueva/", delivery_batch_create_view, name="delivery_batch_create"),
    path("actas/<uuid:pk>/configurar/", delivery_batch_configure_view, name="delivery_batch_configure"),
    path("actas/<uuid:pk>/", delivery_batch_detail_view, name="delivery_batch_detail"),
    path("actas/<uuid:pk>/pdf/", delivery_batch_pdf_view, name="delivery_batch_pdf"),
    path("actas/<uuid:pk>/documentos/adjuntar/", upload_delivery_batch_document_view, name="upload_delivery_batch_document"),
    path("actas/<uuid:pk>/documentos/<uuid:document_id>/archivo/", delivery_batch_document_download_view, name="delivery_batch_document_download"),
    path("actas/<uuid:pk>/preparar/", delivery_batch_prepare_view, name="delivery_batch_prepare"),
    path("actas/<uuid:pk>/enviar-firma/", delivery_batch_send_to_signature_view, name="delivery_batch_send_to_signature"),
    path("actas/<uuid:pk>/completar/", delivery_batch_complete_view, name="delivery_batch_complete"),
    path("agrupar-seleccionados/", group_selected_custody_movements_view, name="group_selected_custody_movements"),

    # MOVIMIENTOS
    path("", custody_movement_list_view, name="custody_movement_list"),
    path("nuevo/", custody_movement_create_view, name="custody_movement_create"),
    path("<uuid:pk>/", custody_movement_detail_view, name="custody_movement_detail"),
    path("<uuid:pk>/editar/", custody_movement_update_view, name="custody_movement_update"),

    # DOCUMENTOS
    path("<uuid:pk>/documentos/adjuntar/", upload_delivery_document_view, name="upload_delivery_document"),
    path("<uuid:pk>/documentos/<uuid:document_id>/reemplazar/", replace_delivery_document_view, name="replace_delivery_document"),
    path("<uuid:pk>/documentos/<uuid:document_id>/eliminar/", delete_delivery_document_view, name="delete_delivery_document"),
    path("<uuid:pk>/documentos/<uuid:document_id>/archivo/", delivery_document_download_view, name="delivery_document_download"),
    path("<uuid:pk>/archivos/<str:file_kind>/", movement_private_file_view, name="movement_private_file"),

    # PDF
    path("<uuid:pk>/pdf/", custody_movement_pdf_view, name="custody_movement_pdf"),

    # FLUJO
    path("<uuid:pk>/preparar/", marcar_preparado, name="marcar_preparado"),
    path("<uuid:pk>/enviar-firma/", enviar_a_firma, name="enviar_a_firma"),
    path("<uuid:pk>/marcar-entregado/", mark_movement_delivered_view, name="mark_movement_delivered"),

    # ACCIONES
    path("enviar-seleccionados/", send_selected_assets_to_custody_view, name="send_selected_assets_to_custody"),
    path("revertir/<uuid:pk>/", revert_movement, name="revert_movement"),
]
