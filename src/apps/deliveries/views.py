from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.views.decorators.http import require_POST
from django.core.exceptions import PermissionDenied
from django.db import transaction

from django.shortcuts import get_object_or_404, redirect, render
from django.http import FileResponse, Http404
from django.urls import reverse
from django.utils import timezone

from .constants import ACTA_CERRADA_ERROR

from apps.activity.models import ActivityLog
from apps.activity.services import register_activity
from apps.inventory.models import Asset


from .forms import (
    AssetCustodyMovementForm,
    DeliveryBatchForm,
    DeliveryBatchDocumentForm,
    DeliveryDocumentForm,
)

from .models import (
    AssetCustodyMovement,
    DeliveryBatch,
    DeliveryBatchDocument,
    DeliveryDocument,
)


@login_required
@permission_required(
    ("deliveries.view_assetcustodymovement", "deliveries.view_deliverydocument"),
    raise_exception=True,
)
def delivery_document_download_view(request, pk, document_id):
    document = get_object_or_404(DeliveryDocument, pk=document_id, movement_id=pk)
    return FileResponse(
        document.file.open("rb"),
        filename=document.original_name,
        content_type="application/octet-stream",
    )


@login_required
@permission_required(
    ("deliveries.view_deliverybatch", "deliveries.view_deliverybatchdocument"),
    raise_exception=True,
)
def delivery_batch_document_download_view(request, pk, document_id):
    document = get_object_or_404(
        DeliveryBatchDocument, pk=document_id, delivery_batch_id=pk
    )
    return FileResponse(
        document.file.open("rb"),
        filename=document.file.name.rsplit("/", 1)[-1],
        content_type="application/octet-stream",
    )


@login_required
@permission_required("deliveries.view_assetcustodymovement", raise_exception=True)
def movement_private_file_view(request, pk, file_kind):
    movement = get_object_or_404(AssetCustodyMovement, pk=pk)
    field_name = {
        "acta": "signed_document",
        "firma-director": "director_signature",
        "firma-responsable": "responsible_signature",
        "firma-receptor": "recipient_signature",
    }.get(file_kind)
    if not field_name:
        raise Http404
    stored_file = getattr(movement, field_name)
    if not stored_file:
        raise Http404
    return FileResponse(
        stored_file.open("rb"),
        filename=stored_file.name.rsplit("/", 1)[-1],
    )

# ==========================================================
# 🔒 HELPER BLOQUEO GLOBAL
# ==========================================================

def validar_acta_no_cerrada(movement):
    if movement.delivery_batch and movement.delivery_batch.status == "DELIVERED":
        raise PermissionDenied(ACTA_CERRADA_ERROR)

# ==========================================================
def require_movement_status(movement, expected_status):
    if movement.status != expected_status:
        raise PermissionDenied("La transicion de estado solicitada no es valida.")

# ==========================================================
# ESTADOS ACTIVOS
# ==========================================================

def get_active_delivery_statuses():
    return [
        AssetCustodyMovement.MovementStatus.IN_DELIVERY_PROCESS,
        AssetCustodyMovement.MovementStatus.PREPARED,
        AssetCustodyMovement.MovementStatus.PENDING_SIGNATURE,
    ]


def can_edit_movement_documents(movement):
    return movement.status in get_active_delivery_statuses() and not (
        movement.delivery_batch
        and movement.delivery_batch.status == DeliveryBatch.BatchStatus.DELIVERED
    )

# ==========================================================
# UPDATE ASSET
# ==========================================================

def update_asset_custody(movement):

    if movement.status != AssetCustodyMovement.MovementStatus.DELIVERED:
        return

    asset = movement.asset

    if movement.movement_type in {
        AssetCustodyMovement.MovementType.DELIVERY,
        AssetCustodyMovement.MovementType.REASSIGNMENT,
    }:
        asset.assigned_user = movement.recipient

    elif movement.movement_type == AssetCustodyMovement.MovementType.RETURN:
        asset.assigned_user = None

    if movement.department:
        asset.department = movement.department

    if movement.location:
        asset.location = movement.location

    if movement.destination_branch_id:
        asset.branch = movement.destination_branch

    asset.save()

# ==========================================================
# LISTADO
# ==========================================================

@login_required
@permission_required("deliveries.view_assetcustodymovement", raise_exception=True)
def custody_movement_list_view(request):

    active_statuses = get_active_delivery_statuses()
    status_filter = request.GET.get("estado", "por_agrupar")
    allowed_filters = {
        "por_agrupar", "agrupados", "preparados", "firma", "entregados", "cancelados", "todos"
    }
    if status_filter not in allowed_filters:
        status_filter = "por_agrupar"

    all_movements = (
        AssetCustodyMovement.objects
        .select_related(
            "asset",
            "asset__assigned_user",
            "asset__branch",
            "asset__acquisition_batch",
            "recipient",
            "previous_custodian",
            "delivery_responsible",
            "created_by",
            "delivery_batch",
        )
        .prefetch_related(
            "delivery_documents",
            "delivery_batch__audit_documents",
        )
        .order_by("-movement_date", "-created_at")
    )

    if status_filter == "por_agrupar":
        movements = all_movements.filter(
            status=AssetCustodyMovement.MovementStatus.IN_DELIVERY_PROCESS,
            delivery_batch__isnull=True,
        )
    elif status_filter == "agrupados":
        movements = all_movements.filter(
            status=AssetCustodyMovement.MovementStatus.IN_DELIVERY_PROCESS,
            delivery_batch__status=DeliveryBatch.BatchStatus.DRAFT,
        ).order_by(
            "-delivery_batch__created_at",
            "delivery_batch_id",
            "asset__internal_code",
        )
    elif status_filter == "preparados":
        movements = all_movements.filter(
            status=AssetCustodyMovement.MovementStatus.PREPARED,
        ).order_by(
            "-delivery_batch__created_at",
            "delivery_batch_id",
            "asset__internal_code",
        )
    elif status_filter == "firma":
        movements = all_movements.filter(
            status=AssetCustodyMovement.MovementStatus.PENDING_SIGNATURE
        ).order_by(
            "-delivery_batch__created_at",
            "delivery_batch_id",
            "asset__internal_code",
        )
    elif status_filter == "entregados":
        movements = all_movements.filter(
            status=AssetCustodyMovement.MovementStatus.DELIVERED
        )
    elif status_filter == "cancelados":
        movements = all_movements.filter(
            status=AssetCustodyMovement.MovementStatus.CANCELLED
        )
    elif status_filter == "todos":
        movements = all_movements
    else:
        movements = all_movements.filter(status__in=active_statuses)

    movements = list(movements)
    for movement in movements:
        movement.batch_configured = bool(
            movement.delivery_batch_id
            and movement.delivery_batch.recipient_id
            and movement.delivery_batch.delivery_responsible_id
            and movement.delivery_batch.authorizing_director_id
            and movement.delivery_batch.destination_branch_id
            and movement.delivery_batch.department
            and movement.delivery_batch.location
        )
        if movement.delivery_batch_id:
            verified_types = {
                document.document_type
                for document in movement.delivery_batch.audit_documents.all()
                if document.signatures_verified
            }
            movement.delivery_form_uploaded = (
                DeliveryBatchDocument.DocumentType.INTERNAL_DELIVERY in verified_types
            )
            movement.patrimonial_form_uploaded = (
                DeliveryBatchDocument.DocumentType.PATRIMONIAL_MOVEMENT in verified_types
            )
        else:
            uploaded_types = {
                document.document_type
                for document in movement.delivery_documents.all()
            }
            movement.delivery_form_uploaded = (
                DeliveryDocument.DocumentType.DELIVERY_FORM in uploaded_types
            )
            movement.patrimonial_form_uploaded = (
                DeliveryDocument.DocumentType.PATRIMONIAL_FORM in uploaded_types
            )

    total_equipos = all_movements.filter(
        status=AssetCustodyMovement.MovementStatus.IN_DELIVERY_PROCESS,
        delivery_batch__isnull=True,
    ).count()

    equipos_agrupados = all_movements.filter(
        status=AssetCustodyMovement.MovementStatus.IN_DELIVERY_PROCESS,
        delivery_batch__status=DeliveryBatch.BatchStatus.DRAFT,
    ).count()

    equipos_preparados = all_movements.filter(
        status=AssetCustodyMovement.MovementStatus.PREPARED,
    ).count()

    pendiente_firma = all_movements.filter(
        status=AssetCustodyMovement.MovementStatus.PENDING_SIGNATURE
    ).count()

    equipos_entregados = all_movements.filter(
        status=AssetCustodyMovement.MovementStatus.DELIVERED
    ).count()
    equipos_cancelados = all_movements.filter(
        status=AssetCustodyMovement.MovementStatus.CANCELLED
    ).count()

    return render(
        request,
        "deliveries/custody_movement_list.html",
        {
            "movements": movements,
            "can_manage_deliveries": request.user.has_perms(
                (
                    "deliveries.change_assetcustodymovement",
                    "deliveries.change_deliverybatch",
                )
            ),
            "can_group_movements": request.user.has_perms(
                (
                    "deliveries.change_assetcustodymovement",
                    "deliveries.add_deliverybatch",
                )
            ),
            "can_add_movement": request.user.has_perm(
                "deliveries.add_assetcustodymovement"
            ),
            "can_view_batches": request.user.has_perm("deliveries.view_deliverybatch"),

            "total_equipos": total_equipos,
            "equipos_preparados": equipos_preparados,
            "equipos_agrupados": equipos_agrupados,
            "pendiente_firma": pendiente_firma,
            "equipos_entregados": equipos_entregados,
            "equipos_cancelados": equipos_cancelados,
            "status_filter": status_filter,
        },
    )

# ==========================================================
# DETALLE MOVIMIENTO
# ==========================================================

@login_required
@permission_required("deliveries.view_assetcustodymovement", raise_exception=True)
def custody_movement_detail_view(request, pk):

    movement = get_object_or_404(
        AssetCustodyMovement.objects
        .select_related(
            "asset",
            "recipient",
            "delivery_responsible",
            "authorizing_director",
            "delivery_batch",
        )
        .prefetch_related(
            "delivery_documents",
            "delivery_batch__audit_documents__uploaded_by",
        ),
        pk=pk,
    )

    is_locked = (
        movement.status in {
            AssetCustodyMovement.MovementStatus.DELIVERED,
            AssetCustodyMovement.MovementStatus.CANCELLED,
        }
        or (
            movement.delivery_batch
            and movement.delivery_batch.status == DeliveryBatch.BatchStatus.DELIVERED
        )
    )

    uses_batch_documents = movement.delivery_batch_id is not None
    if uses_batch_documents:
        documents = movement.delivery_batch.audit_documents.all()
        delivery_form_uploaded = documents.filter(
            document_type=DeliveryBatchDocument.DocumentType.INTERNAL_DELIVERY,
            signatures_verified=True,
        ).exists()
        patrimonial_form_uploaded = documents.filter(
            document_type=DeliveryBatchDocument.DocumentType.PATRIMONIAL_MOVEMENT,
            signatures_verified=True,
        ).exists()
    else:
        documents = movement.delivery_documents.all()
        delivery_form_uploaded = documents.filter(
            document_type=DeliveryDocument.DocumentType.DELIVERY_FORM,
        ).exists()
        patrimonial_form_uploaded = documents.filter(
            document_type=DeliveryDocument.DocumentType.PATRIMONIAL_FORM,
        ).exists()
    document_form = DeliveryDocumentForm()
    uploaded_required_types = {
        document.document_type
        for document in documents
        if document.document_type in {
            DeliveryDocument.DocumentType.DELIVERY_FORM,
            DeliveryDocument.DocumentType.PATRIMONIAL_FORM,
        }
    }
    document_form.fields["document_type"].choices = [
        ("", "---------"),
        *[
            (value, label)
            for value, label in DeliveryDocument.DocumentType.choices
            if value not in uploaded_required_types
        ],
    ]
    documents_complete = delivery_form_uploaded and patrimonial_form_uploaded

    return render(
        request,
        "deliveries/custody_movement_detail.html",
        {
            "movement": movement,
            "documents": documents,
            "uses_batch_documents": uses_batch_documents,
            "document_form": document_form,
            "delivery_form_uploaded": delivery_form_uploaded,
            "patrimonial_form_uploaded": patrimonial_form_uploaded,
            "documents_complete": documents_complete,
            "director_authorized": (
                documents_complete if uses_batch_documents else bool(movement.director_signature)
            ),
            "responsible_signed": (
                documents_complete if uses_batch_documents else bool(movement.responsible_signature)
            ),
            "recipient_signed": (
                documents_complete if uses_batch_documents else bool(movement.recipient_signature)
            ),
            "can_manage_deliveries": request.user.has_perm(
                "deliveries.change_assetcustodymovement"
            ),
            "can_delete_documents": request.user.has_perm(
                "deliveries.delete_deliverydocument"
            ),
            "can_replace_documents": request.user.has_perm(
                "deliveries.change_deliverydocument"
            ),
            "can_view_documents": request.user.has_perm(
                "deliveries.view_deliverybatchdocument"
                if uses_batch_documents
                else "deliveries.view_deliverydocument"
            ),
            "is_locked": is_locked,
            "can_upload_documents": (
                not uses_batch_documents
                and
                request.user.has_perm("deliveries.add_deliverydocument")
                and can_edit_movement_documents(movement)
            ),
        },
    )

# ==========================================================
# EDITAR MOVIMIENTO
# ==========================================================

@login_required
@permission_required("deliveries.change_assetcustodymovement", raise_exception=True)
def custody_movement_update_view(request, pk):

    movement = get_object_or_404(AssetCustodyMovement, pk=pk)

    validar_acta_no_cerrada(movement)

    if request.method == "POST":
        form = AssetCustodyMovementForm(
            request.POST,
            request.FILES,
            instance=movement,
            current_user=request.user,
        )

        if form.is_valid():
            movement = form.save()
            update_asset_custody(movement)

            messages.success(request, "Movimiento actualizado.")
            return redirect("deliveries:custody_movement_detail", pk=pk)

    else:
        form = AssetCustodyMovementForm(
            instance=movement,
            current_user=request.user,
        )

    return render(
        request,
        "deliveries/custody_movement_form.html",
        {"form": form, "editing": True},
    )

# ==========================================================
# DOCUMENTOS
# ==========================================================

@login_required
@permission_required("deliveries.add_deliverydocument", raise_exception=True)
@require_POST
def upload_delivery_document_view(request, pk):

    movement = get_object_or_404(AssetCustodyMovement, pk=pk)

    validar_acta_no_cerrada(movement)

    if not can_edit_movement_documents(movement):
        messages.error(
            request,
            "La documentación de una entrega finalizada o cancelada no puede modificarse.",
        )
        return redirect("deliveries:custody_movement_detail", pk=pk)

    form = DeliveryDocumentForm(request.POST, request.FILES)

    if form.is_valid():
        doc = form.save(commit=False)
        doc.movement = movement
        doc.uploaded_by = request.user
        doc.save()

        messages.success(request, "Documento subido.")
    else:
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)

    return redirect("deliveries:custody_movement_detail", pk=pk)

@login_required
@permission_required("deliveries.change_deliverydocument", raise_exception=True)
@require_POST
def replace_delivery_document_view(request, pk, document_id):

    movement = get_object_or_404(AssetCustodyMovement, pk=pk)
    document = get_object_or_404(
        DeliveryDocument,
        pk=document_id,
        movement=movement,
    )

    validar_acta_no_cerrada(movement)

    if not can_edit_movement_documents(movement):
        messages.error(request, "La documentación de este movimiento está bloqueada.")
        return redirect("deliveries:custody_movement_detail", pk=pk)

    form = DeliveryDocumentForm(
        request.POST,
        request.FILES,
        instance=document,
    )
    if form.is_valid():
        document = form.save(commit=False)
        document.uploaded_by = request.user
        document.save()
        messages.success(request, "Documento reemplazado.")
    else:
        messages.error(request, "No se pudo reemplazar el documento.")

    return redirect("deliveries:custody_movement_detail", pk=pk)

@login_required
@permission_required("deliveries.delete_deliverydocument", raise_exception=True)
@require_POST
def delete_delivery_document_view(request, pk, document_id):

    movement = get_object_or_404(AssetCustodyMovement, pk=pk)
    document = get_object_or_404(
        DeliveryDocument,
        pk=document_id,
        movement=movement,
    )

    validar_acta_no_cerrada(movement)

    if not can_edit_movement_documents(movement):
        messages.error(request, "La documentación de este movimiento está bloqueada.")
        return redirect("deliveries:custody_movement_detail", pk=pk)

    document.delete()
    messages.success(request, "Documento eliminado.")

    return redirect("deliveries:custody_movement_detail", pk=pk)

# ==========================================================
# ENTREGAR
# ==========================================================

@login_required
@permission_required("deliveries.change_assetcustodymovement", raise_exception=True)
@require_POST
@transaction.atomic
def mark_movement_delivered_view(request, pk):

    movement = get_object_or_404(AssetCustodyMovement, pk=pk)

    validar_acta_no_cerrada(movement)
    require_movement_status(
        movement,
        AssetCustodyMovement.MovementStatus.PENDING_SIGNATURE,
    )
    required_document_types = {
        DeliveryDocument.DocumentType.DELIVERY_FORM,
        DeliveryDocument.DocumentType.PATRIMONIAL_FORM,
    }
    uploaded_document_types = set(
        movement.delivery_documents.filter(
            document_type__in=required_document_types,
        ).values_list("document_type", flat=True)
    )
    if uploaded_document_types != required_document_types:
        missing_labels = [
            label
            for document_type, label in DeliveryDocument.DocumentType.choices
            if document_type in required_document_types
            and document_type not in uploaded_document_types
        ]
        messages.error(
            request,
            "No se puede marcar el equipo como entregado. Falta adjuntar: "
            + ", ".join(missing_labels)
            + ".",
        )
        return redirect("deliveries:custody_movement_detail", pk=pk)

    if not movement.recipient:
        messages.error(
            request,
            "No se puede marcar el equipo como entregado sin asignar un receptor.",
        )
        return redirect("deliveries:custody_movement_detail", pk=pk)

    movement.status = AssetCustodyMovement.MovementStatus.DELIVERED
    movement.save()

    update_asset_custody(movement)

    if movement.delivery_batch:

        batch = movement.delivery_batch

        total = batch.movements.count()
        entregados = batch.movements.filter(
            status=AssetCustodyMovement.MovementStatus.DELIVERED
        ).count()

        if total == entregados:
            batch.status = "DELIVERED"
            batch.save()

            messages.success(request, "Acta cerrada automáticamente.")

    messages.success(request, "Equipo entregado.")

    return redirect("deliveries:custody_movement_detail", pk=pk)
    # ==========================================================
# 🔧 MARCAR COMO PREPARADO
# ==========================================================

@login_required
@permission_required("deliveries.change_assetcustodymovement", raise_exception=True)
@require_POST
def marcar_preparado(request, pk):

    movement = get_object_or_404(AssetCustodyMovement, pk=pk)

    validar_acta_no_cerrada(movement)
    require_movement_status(
        movement,
        AssetCustodyMovement.MovementStatus.IN_DELIVERY_PROCESS,
    )

    if (
        not movement.recipient
        or not movement.destination_branch
        or not movement.department
        or not movement.location
    ):
        messages.error(
            request,
            "Debe completar receptor, sede, departamento y ubicación antes de preparar la entrega.",
        )
        return redirect("deliveries:custody_movement_detail", pk=pk)

    movement.status = AssetCustodyMovement.MovementStatus.PREPARED
    movement.save()

    messages.success(request, "Equipo marcado como preparado.")
    return redirect("deliveries:custody_movement_detail", pk=pk)


# ==========================================================
# ✍️ ENVIAR A FIRMA
# ==========================================================

@login_required
@permission_required("deliveries.change_assetcustodymovement", raise_exception=True)
@require_POST
def enviar_a_firma(request, pk):

    movement = get_object_or_404(AssetCustodyMovement, pk=pk)

    validar_acta_no_cerrada(movement)
    require_movement_status(
        movement,
        AssetCustodyMovement.MovementStatus.PREPARED,
    )

    movement.status = AssetCustodyMovement.MovementStatus.PENDING_SIGNATURE
    movement.save()

    messages.success(request, "Equipo enviado a firma.")
    return redirect("deliveries:custody_movement_detail", pk=pk)



# ==========================================================
# REVERTIR
# ==========================================================

@login_required
@permission_required("deliveries.change_assetcustodymovement", raise_exception=True)
@require_POST
def revert_movement(request, pk):

    movement = get_object_or_404(AssetCustodyMovement, pk=pk)

    validar_acta_no_cerrada(movement)

    movement.status = AssetCustodyMovement.MovementStatus.CANCELLED
    movement.save()

    messages.warning(request, "Movimiento cancelado.")
    return redirect("deliveries:custody_movement_detail", pk=pk)

# ==========================================================
# ACTAS AGRUPADAS
# ==========================================================

@login_required
@permission_required("deliveries.view_deliverybatch", raise_exception=True)
def delivery_batch_list_view(request):

    batches = DeliveryBatch.objects.all().order_by("-created_at")

    return render(
        request,
        "deliveries/delivery_batch_list.html",
        {
            "batches": batches,
            "can_manage_deliveries": request.user.has_perms(
                (
                    "deliveries.change_deliverybatch",
                    "deliveries.change_assetcustodymovement",
                )
            ),
            "can_add_batch": request.user.has_perm("deliveries.add_deliverybatch"),
            "can_view_movements": request.user.has_perm(
                "deliveries.view_assetcustodymovement"
            ),
        },
    )

@login_required
@permission_required("deliveries.view_deliverybatch", raise_exception=True)
def delivery_batch_detail_view(request, pk):

    delivery_batch = get_object_or_404(
        DeliveryBatch.objects.prefetch_related(
            "movements__asset",
            "audit_documents__uploaded_by",
        ),
        pk=pk,
    )

    movements = delivery_batch.movements.all()

    is_locked = delivery_batch.status == "DELIVERED"
    batch_documents = delivery_batch.audit_documents.all()
    required_document_types = {
        DeliveryBatchDocument.DocumentType.INTERNAL_DELIVERY,
        DeliveryBatchDocument.DocumentType.PATRIMONIAL_MOVEMENT,
    }
    verified_document_types = {
        document.document_type
        for document in batch_documents
        if document.signatures_verified
    }
    documents_complete = required_document_types <= verified_document_types
    batch_configured = bool(
        delivery_batch.recipient_id
        and delivery_batch.delivery_responsible_id
        and delivery_batch.authorizing_director_id
        and delivery_batch.destination_branch_id
        and delivery_batch.department
        and delivery_batch.location
    )
    uploaded_required_types = {
        document.document_type
        for document in batch_documents
        if document.document_type in required_document_types
    }
    internal_delivery_uploaded = (
        DeliveryBatchDocument.DocumentType.INTERNAL_DELIVERY in uploaded_required_types
    )
    patrimonial_movement_uploaded = (
        DeliveryBatchDocument.DocumentType.PATRIMONIAL_MOVEMENT in uploaded_required_types
    )
    missing_document_labels = [
        label
        for document_type, label in DeliveryBatchDocument.DocumentType.choices
        if document_type in required_document_types
        and document_type not in uploaded_required_types
    ]
    unverified_document_labels = [
        document.get_document_type_display()
        for document in batch_documents
        if document.document_type in required_document_types
        and not document.signatures_verified
    ]
    document_form = DeliveryBatchDocumentForm()
    document_form.fields["document_type"].choices = [
        ("", "---------"),
        *[
            (value, label)
            for value, label in DeliveryBatchDocument.DocumentType.choices
            if value not in {
                document.document_type
                for document in batch_documents
                if document.document_type in required_document_types
            }
        ],
    ]

    return render(
        request,
        "deliveries/delivery_batch_detail.html",
        {
            "delivery_batch": delivery_batch,
            "movements": movements,
            "asset_count": movements.count(),
            "is_locked": is_locked,
            "can_manage_deliveries": request.user.has_perms(
                (
                    "deliveries.change_deliverybatch",
                    "deliveries.change_assetcustodymovement",
                )
            ),
            "can_upload_batch_documents": request.user.has_perm(
                "deliveries.add_deliverybatchdocument"
            ),
            "can_view_batch_documents": request.user.has_perm(
                "deliveries.view_deliverybatchdocument"
            ),
            "batch_documents": batch_documents,
            "batch_document_form": document_form,
            "documents_complete": documents_complete,
            "batch_configured": batch_configured,
            "missing_document_labels": missing_document_labels,
            "unverified_document_labels": unverified_document_labels,
            "internal_delivery_uploaded": internal_delivery_uploaded,
            "patrimonial_movement_uploaded": patrimonial_movement_uploaded,
        },
    )


@login_required
@permission_required("deliveries.add_deliverybatchdocument", raise_exception=True)
@require_POST
def upload_delivery_batch_document_view(request, pk):
    batch = get_object_or_404(DeliveryBatch, pk=pk)
    if batch.status in {DeliveryBatch.BatchStatus.DELIVERED, DeliveryBatch.BatchStatus.CANCELLED}:
        raise PermissionDenied("El acta está cerrada y su documentación no puede modificarse.")
    if batch.status != DeliveryBatch.BatchStatus.PENDING_SIGNATURE:
        messages.error(
            request,
            "La documentación podrá cargarse después de la autorización del Director DTI.",
        )
        return redirect("deliveries:delivery_batch_detail", pk=pk)

    form = DeliveryBatchDocumentForm(request.POST, request.FILES)
    if form.is_valid():
        document = form.save(commit=False)
        document.delivery_batch = batch
        document.uploaded_by = request.user
        document.save()
        messages.success(request, "Documento del acta registrado para auditoría.")
    else:
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)
    return redirect("deliveries:delivery_batch_detail", pk=pk)


@login_required
@permission_required(
    ("deliveries.change_deliverybatch", "deliveries.change_assetcustodymovement"),
    raise_exception=True,
)
@require_POST
@transaction.atomic
def delivery_batch_prepare_view(request, pk):
    batch = get_object_or_404(DeliveryBatch.objects.prefetch_related("movements"), pk=pk)
    if batch.status != DeliveryBatch.BatchStatus.DRAFT:
        raise PermissionDenied("Solo un acta en borrador puede marcarse como preparada.")
    if not batch.recipient or not batch.delivery_responsible or not batch.authorizing_director or not batch.destination_branch or not batch.department or not batch.location:
        messages.error(
            request,
            "No se pudo confirmar la preparación. Complete receptor, responsable, Director DTI, sede, departamento y ubicación.",
        )
        return redirect("deliveries:delivery_batch_configure", pk=pk)
    if not batch.movements.exists():
        messages.error(request, "El acta no contiene equipos.")
        return redirect("deliveries:delivery_batch_detail", pk=pk)

    batch.status = DeliveryBatch.BatchStatus.PREPARED
    batch.save(update_fields=["status", "updated_at"])
    batch.movements.update(status=AssetCustodyMovement.MovementStatus.PREPARED)
    messages.success(request, "Equipos marcados como preparados. El acta espera autorización del Director DTI.")
    return redirect("deliveries:delivery_batch_detail", pk=pk)


@login_required
@permission_required(
    ("deliveries.change_deliverybatch", "deliveries.change_assetcustodymovement"),
    raise_exception=True,
)
@require_POST
@transaction.atomic
def delivery_batch_send_to_signature_view(request, pk):
    batch = get_object_or_404(DeliveryBatch, pk=pk)
    if batch.status != DeliveryBatch.BatchStatus.PREPARED:
        raise PermissionDenied("El acta debe estar preparada antes de la autorización.")
    if not batch.recipient or not batch.delivery_responsible or not batch.authorizing_director or not batch.destination_branch or not batch.department or not batch.location:
        messages.error(request, "Complete receptor, responsable, Director DTI, sede, departamento y ubicación.")
        return redirect("deliveries:delivery_batch_detail", pk=pk)
    if not batch.movements.exists():
        messages.error(request, "El acta no contiene equipos.")
        return redirect("deliveries:delivery_batch_detail", pk=pk)

    batch.status = DeliveryBatch.BatchStatus.PENDING_SIGNATURE
    batch.save(update_fields=["status", "updated_at"])
    batch.movements.update(status=AssetCustodyMovement.MovementStatus.PENDING_SIGNATURE)
    messages.success(request, "Entrega autorizada por el Director DTI. Adjunte los documentos firmados.")
    return redirect("deliveries:delivery_batch_detail", pk=pk)


@login_required
@permission_required(
    ("deliveries.change_deliverybatch", "deliveries.change_assetcustodymovement"),
    raise_exception=True,
)
@require_POST
@transaction.atomic
def delivery_batch_complete_view(request, pk):
    batch = get_object_or_404(
        DeliveryBatch.objects.prefetch_related("movements__asset", "audit_documents"),
        pk=pk,
    )
    if batch.status != DeliveryBatch.BatchStatus.PENDING_SIGNATURE:
        raise PermissionDenied("El acta debe estar pendiente de firma para completar la entrega.")

    required_types = {
        DeliveryBatchDocument.DocumentType.INTERNAL_DELIVERY,
        DeliveryBatchDocument.DocumentType.PATRIMONIAL_MOVEMENT,
    }
    verified_types = set(
        batch.audit_documents.filter(
            signatures_verified=True,
            document_type__in=required_types,
        ).values_list("document_type", flat=True)
    )
    if verified_types != required_types:
        uploaded_documents = {
            document.document_type: document
            for document in batch.audit_documents.all()
            if document.document_type in required_types
        }
        missing_labels = [
            label
            for document_type, label in DeliveryBatchDocument.DocumentType.choices
            if document_type in required_types and document_type not in uploaded_documents
        ]
        unverified_labels = [
            document.get_document_type_display()
            for document in uploaded_documents.values()
            if not document.signatures_verified
        ]
        problems = []
        if missing_labels:
            problems.append("Falta adjuntar: " + ", ".join(missing_labels))
        if unverified_labels:
            problems.append("Falta confirmar las firmas de: " + ", ".join(unverified_labels))
        messages.error(request, ". ".join(problems) + ".")
        detail_url = reverse("deliveries:delivery_batch_detail", kwargs={"pk": pk})
        return redirect(f"{detail_url}#batch-documentation")

    for movement in batch.movements.all():
        movement.recipient = batch.recipient
        movement.recipient_employee_number = batch.recipient_employee_number
        movement.recipient_position = batch.recipient_position
        movement.recipient_area = batch.recipient_area
        movement.recipient_unit = batch.recipient_unit
        movement.recipient_section = batch.recipient_section
        movement.delivery_responsible = batch.delivery_responsible
        movement.authorizing_director = batch.authorizing_director
        movement.department = batch.department
        movement.destination_branch = batch.destination_branch
        movement.location = batch.location
        movement.status = AssetCustodyMovement.MovementStatus.DELIVERED
        movement.save()
        update_asset_custody(movement)

    batch.status = DeliveryBatch.BatchStatus.DELIVERED
    batch.save(update_fields=["status", "updated_at"])
    messages.success(request, "Entrega completada e inventario actualizado.")
    return redirect("deliveries:delivery_batch_detail", pk=pk)

# ==========================================================
# CREAR ACTA AGRUPADA (NECESARIA PARA URLS)
# ==========================================================

@login_required
@permission_required(
    ("deliveries.add_deliverybatch", "deliveries.add_assetcustodymovement"),
    raise_exception=True,
)
@transaction.atomic
def delivery_batch_create_view(request):

    selected_asset_ids = (
        request.POST.getlist("assets")
        if request.method == "POST"
        else request.session.get("delivery_asset_ids", [])
    )
    if not selected_asset_ids:
        messages.warning(request, "Seleccione primero los equipos desde Inventario.")
        return redirect("inventory:asset_list")

    selected_assets = Asset.objects.filter(id__in=selected_asset_ids).order_by(
        "asset_type", "brand", "model", "internal_code"
    )
    batch_issues = []
    selected_batches = {
        asset.acquisition_batch
        for asset in selected_assets.select_related("acquisition_batch")
        if asset.acquisition_batch
    }
    for acquisition_batch in selected_batches:
        issues = []
        if acquisition_batch.status not in {
            acquisition_batch.Status.VALIDATED,
            acquisition_batch.Status.CLOSED,
        }:
            issues.append("El lote no está validado.")
        if not acquisition_batch.audit_documents.filter(verified=True).exists():
            issues.append("Falta documentación verificada.")
        if not acquisition_batch.quantity_matches:
            issues.append(
                f"Cantidad esperada: {acquisition_batch.expected_quantity}; "
                f"registrada: {acquisition_batch.registered_quantity}."
            )
        if issues:
            batch_issues.append({"batch": acquisition_batch, "issues": issues})

    if request.method == "POST":
        form = DeliveryBatchForm(
            request.POST,
            request.FILES,
            current_user=request.user,
            staged_asset_ids=selected_asset_ids,
        )

        if form.is_valid():
            assets = list(form.cleaned_data["assets"])
            batch = form.save(commit=False)
            batch.created_by = request.user
            batch.status = DeliveryBatch.BatchStatus.DRAFT
            batch.save()

            for asset in assets:
                movement = AssetCustodyMovement.objects.filter(
                    asset=asset,
                    delivery_batch__isnull=True,
                    status=AssetCustodyMovement.MovementStatus.IN_DELIVERY_PROCESS,
                ).first()
                if movement is None:
                    movement = AssetCustodyMovement(
                        asset=asset,
                        movement_type=AssetCustodyMovement.MovementType.DELIVERY,
                        status=AssetCustodyMovement.MovementStatus.IN_DELIVERY_PROCESS,
                        created_by=request.user,
                    )
                movement.delivery_batch = batch
                movement.recipient = batch.recipient
                movement.recipient_employee_number = batch.recipient_employee_number
                movement.recipient_position = batch.recipient_position
                movement.recipient_area = batch.recipient_area
                movement.recipient_unit = batch.recipient_unit
                movement.recipient_section = batch.recipient_section
                movement.delivery_responsible = batch.delivery_responsible
                movement.authorizing_director = batch.authorizing_director
                movement.department = batch.department
                movement.destination_branch = batch.destination_branch
                movement.location = batch.location
                movement.movement_date = batch.delivery_date
                movement.observations = batch.observations
                movement.save()

            request.session.pop("delivery_asset_ids", None)

            messages.success(
                request,
                f"Acta creada con {len(assets)} equipo(s).",
            )
            return redirect("deliveries:delivery_batch_detail", pk=batch.pk)

    else:
        initial_asset_ids = request.session.get("delivery_asset_ids", [])
        form = DeliveryBatchForm(
            current_user=request.user,
            initial={"assets": initial_asset_ids},
            staged_asset_ids=initial_asset_ids,
        )

    return render(
        request,
        "deliveries/delivery_batch_form.html",
        {
            "form": form,
            "selected_assets": selected_assets,
            "batch_issues": batch_issues,
        },
    )

# ==========================================================
# CREAR MOVIMIENTO (NECESARIA PARA URLS)
# ==========================================================

@login_required
@permission_required("deliveries.add_assetcustodymovement", raise_exception=True)
@transaction.atomic
def custody_movement_create_view(request):

    if request.method == "POST":
        form = AssetCustodyMovementForm(
            request.POST,
            request.FILES,
            current_user=request.user,
        )

        if form.is_valid():
            movement = form.save(commit=False)
            movement.created_by = request.user
            movement.save()
            update_asset_custody(movement)

            messages.success(request, "Movimiento creado correctamente.")
            return redirect("deliveries:custody_movement_detail", pk=movement.pk)

    else:
        form = AssetCustodyMovementForm(
            current_user=request.user,
        )

    return render(
        request,
        "deliveries/custody_movement_form.html",
        {
            "form": form,
            "editing": False,
        },
    )

from django.http import HttpResponse
from .pdf_generator import generate_delivery_batch_pdf

@login_required
@permission_required(
    ("deliveries.view_assetcustodymovement", "deliveries.view_deliverybatch"),
    raise_exception=True,
)
def custody_movement_pdf_view(request, pk):
    movement = get_object_or_404(AssetCustodyMovement, pk=pk)

    if not movement.delivery_batch:
        return HttpResponse("Este movimiento no pertenece a un acta.", status=400)

    batch = movement.delivery_batch  # 👈 ESTA LÍNEA ES LA CLAVE

    pdf_buffer = generate_delivery_batch_pdf(batch)

    response = HttpResponse(
        pdf_buffer.getvalue(),
        content_type="application/pdf"
    )

    response["Content-Disposition"] = f'inline; filename="acta_{batch.batch_number}.pdf"'

    return response



@require_POST
@login_required
@permission_required("deliveries.add_assetcustodymovement", raise_exception=True)
@transaction.atomic
def send_selected_assets_to_custody_view(request):
    asset_ids = request.POST.getlist("selected_assets")

    if not asset_ids:
        messages.warning(request, "No seleccionaste equipos.")
        return redirect("inventory:asset_list")

    active_statuses = get_active_delivery_statuses()
    eligible_assets = Asset.objects.filter(
        pk__in=asset_ids,
        assigned_user__isnull=True,
    ).exclude(custody_movements__status__in=active_statuses).distinct()

    created_count = 0
    for asset in eligible_assets:
        AssetCustodyMovement.objects.create(
            asset=asset,
            movement_type=AssetCustodyMovement.MovementType.DELIVERY,
            status=AssetCustodyMovement.MovementStatus.IN_DELIVERY_PROCESS,
            delivery_responsible=request.user,
            created_by=request.user,
        )
        created_count += 1

    omitted_count = len(set(asset_ids)) - created_count
    if created_count:
        messages.success(
            request,
            f"{created_count} equipo(s) enviados a Equipos para Entrega.",
        )
    if omitted_count:
        messages.warning(
            request,
            f"{omitted_count} equipo(s) no se enviaron porque ya están asignados o tienen una entrega activa.",
        )
    return redirect("deliveries:custody_movement_list")


@require_POST
@login_required
@permission_required(
    ("deliveries.change_assetcustodymovement", "deliveries.add_deliverybatch"),
    raise_exception=True,
)
@transaction.atomic
def group_selected_custody_movements_view(request):
    asset_ids = request.POST.getlist("selected_ids")
    staged_asset_ids = list(
        AssetCustodyMovement.objects.filter(
            asset_id__in=asset_ids,
            delivery_batch__isnull=True,
            status=AssetCustodyMovement.MovementStatus.IN_DELIVERY_PROCESS,
        ).values_list("asset_id", flat=True)
    )
    if not staged_asset_ids:
        messages.warning(request, "Seleccione equipos en proceso que todavía no pertenezcan a un acta.")
        return redirect("deliveries:custody_movement_list")

    batch = DeliveryBatch.objects.create(
        status=DeliveryBatch.BatchStatus.DRAFT,
        delivery_responsible=request.user,
        created_by=request.user,
    )
    AssetCustodyMovement.objects.filter(
        asset_id__in=staged_asset_ids,
        delivery_batch__isnull=True,
        status=AssetCustodyMovement.MovementStatus.IN_DELIVERY_PROCESS,
    ).update(delivery_batch=batch)
    messages.success(
        request,
        f"Acta {batch.batch_number} creada con {len(staged_asset_ids)} equipo(s). Configure el grupo desde la tarjeta Agrupados por Configurar.",
    )
    return redirect(
        f'{reverse("deliveries:custody_movement_list")}?estado=agrupados'
    )


@login_required
@permission_required(
    ("deliveries.change_deliverybatch", "deliveries.change_assetcustodymovement"),
    raise_exception=True,
)
@transaction.atomic
def delivery_batch_configure_view(request, pk):
    batch = get_object_or_404(
        DeliveryBatch.objects.prefetch_related("movements__asset"),
        pk=pk,
        status=DeliveryBatch.BatchStatus.DRAFT,
    )
    selected_assets = Asset.objects.filter(
        custody_movements__delivery_batch=batch
    ).distinct().order_by("asset_type", "brand", "model", "internal_code")
    selected_asset_ids = list(selected_assets.values_list("pk", flat=True))

    if request.method == "POST":
        form = DeliveryBatchForm(
            request.POST,
            request.FILES,
            instance=batch,
            current_user=request.user,
            staged_asset_ids=selected_asset_ids,
        )
        if form.is_valid():
            batch = form.save()
            batch.movements.update(
                recipient=batch.recipient,
                recipient_employee_number=batch.recipient_employee_number,
                recipient_position=batch.recipient_position,
                recipient_area=batch.recipient_area,
                recipient_unit=batch.recipient_unit,
                recipient_section=batch.recipient_section,
                delivery_responsible=batch.delivery_responsible,
                authorizing_director=batch.authorizing_director,
                department=batch.department,
                destination_branch=batch.destination_branch,
                location=batch.location,
                movement_date=batch.delivery_date,
                observations=batch.observations,
            )
            messages.success(
                request,
                f"Acta {batch.batch_number} configurada. Ya puede confirmar los equipos preparados.",
            )
            return redirect(
                f'{reverse("deliveries:custody_movement_list")}?estado=agrupados'
            )
    else:
        form = DeliveryBatchForm(
            instance=batch,
            current_user=request.user,
            staged_asset_ids=selected_asset_ids,
            initial={"assets": selected_asset_ids},
        )

    return render(
        request,
        "deliveries/delivery_batch_form.html",
        {
            "form": form,
            "selected_assets": selected_assets,
            "batch_issues": [],
            "editing": True,
            "delivery_batch": batch,
        },
    )
