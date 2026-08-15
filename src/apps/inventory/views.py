from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)

from apps.deliveries.models import AssetCustodyMovement
from apps.accounts.models import User
from apps.accounts.access import (
    can_manage_deliveries,
    can_manage_inventory,
    can_register_intervention,
    roles_required,
)


from .forms import (
    AssetForm,
    AssetTechnicalHistoryForm,
    StockCategoryForm,
    StockEntryForm,
    StockEntryDocumentForm,
    StockEntryLineForm,
    StockEntryOperationForm,
    StockDeliveryForm,
    StockDeliveryLineForm,
    StockDeliverySignedDocumentForm,
    TicketStockUsageForm,
    TicketStockUsageLineForm,
    StockExitForm,
    StockProductForm,
    StockTransferForm,
)
from django.utils import timezone
from .models import (
    Asset,
    StockBalance,
    StockCategory,
    StockMovement,
    StockProduct,
    StockEntryDocument,
    StockEntryLine,
    StockEntryOperation,
    StockDelivery,
    StockDeliveryLine,
    TicketStockUsage,
    TicketStockUsageLine,
)
from .services.stock import (
    register_stock_entry,
    register_stock_exit,
    transfer_stock,
    confirm_stock_entry,
    prepare_stock_delivery,
    complete_stock_delivery,
    confirm_ticket_stock_usage,
)
from .stock_delivery_pdf import generate_stock_delivery_pdf


# ==========================================================
# PERMISOS DEL MÓDULO INVENTARIO
# ==========================================================




# ==========================================================
# LISTADO DE ACTIVOS
# ==========================================================

@login_required
@roles_required("ADMIN", "SUPERVISOR", "AUDITOR", "TECHNICIAN")
def asset_list_view(request):
    assets = (
        Asset.objects
        .select_related(
            "assigned_user",
            "branch",
            "acquisition_batch",
        )
        .prefetch_related("custody_movements")
        .all()
    )

    active_custody_statuses = [
        AssetCustodyMovement.MovementStatus.IN_DELIVERY_PROCESS,
        AssetCustodyMovement.MovementStatus.PREPARED,
        AssetCustodyMovement.MovementStatus.PENDING_SIGNATURE,
    ]

    assets_in_custody_process = set(
        AssetCustodyMovement.objects.filter(
            status__in=active_custody_statuses,
            movement_type=(
                AssetCustodyMovement
                .MovementType
                .DELIVERY
            ),
        ).values_list(
            "asset_id",
            flat=True,
        )
    )

    search = request.GET.get("q", "").strip()
    asset_type = request.GET.get("tipo", "").strip()
    brand = request.GET.get("marca", "").strip()
    model = request.GET.get("modelo", "").strip()
    batch = request.GET.get("lote", "").strip()
    branch = request.GET.get("sede", "").strip()
    assignment = request.GET.get("asignacion", "").strip()
    operational_status = request.GET.get("estado_tecnico", "").strip()

    if search:
        assets = assets.filter(
            Q(internal_code__icontains=search)
            | Q(patrimonial_code__icontains=search)
            | Q(serial_number__icontains=search)
            | Q(hostname__icontains=search)
            | Q(assigned_user__first_name__icontains=search)
            | Q(assigned_user__last_name__icontains=search)
            | Q(assigned_user__email__icontains=search)
        )
    if asset_type:
        assets = assets.filter(asset_type=asset_type)
    if brand:
        assets = assets.filter(brand__iexact=brand)
    if model:
        assets = assets.filter(model__iexact=model)
    if batch:
        assets = assets.filter(acquisition_batch_id=batch)
    if branch:
        assets = assets.filter(branch_id=branch)
    if operational_status:
        assets = assets.filter(operational_status=operational_status)
    if assignment == "AVAILABLE":
        assets = assets.filter(assigned_user__isnull=True).exclude(
            pk__in=assets_in_custody_process
        )
    elif assignment == "IN_PROCESS":
        assets = assets.filter(pk__in=assets_in_custody_process)
    elif assignment == "ASSIGNED":
        assets = assets.filter(assigned_user__isnull=False).exclude(
            pk__in=assets_in_custody_process
        )

    return render(
        request,
        "inventory/asset_list.html",
        {
            "assets": assets,
            "assets_in_custody_process": (
                assets_in_custody_process
            ),
            "asset_type_choices": Asset.AssetType.choices,
            "operational_status_choices": Asset.OperationalStatus.choices,
            "brand_choices": Asset.objects.exclude(brand="").values_list(
                "brand", flat=True
            ).distinct().order_by("brand"),
            "model_choices": Asset.objects.exclude(model="").values_list(
                "model", flat=True
            ).distinct().order_by("model"),
            "batch_choices": Asset.objects.filter(
                acquisition_batch__isnull=False
            ).values_list(
                "acquisition_batch_id", "acquisition_batch__code"
            ).distinct().order_by("acquisition_batch__code"),
            "branch_choices": Asset.objects.filter(branch__isnull=False).values_list(
                "branch_id", "branch__name"
            ).distinct().order_by("branch__name"),
            "active_filters": request.GET,
        },
    )

# ==========================================================
# CREAR ACTIVO
# ==========================================================

@login_required
def asset_create_view(request):
    if not can_manage_inventory(request.user):
        raise PermissionDenied(
            "No tiene permisos para registrar activos."
        )

    if request.method == "POST":
        form = AssetForm(request.POST)

        if form.is_valid():
            asset = form.save()

            return redirect(
                "inventory:asset_detail",
                pk=asset.pk,
            )

    else:
        form = AssetForm()

    return render(
        request,
        "inventory/asset_form.html",
        {
            "form": form,
            "editing": False,
        },
    )


# ==========================================================
# DETALLE DEL ACTIVO
# ==========================================================

@login_required
@roles_required("ADMIN", "SUPERVISOR", "AUDITOR", "TECHNICIAN")
def asset_detail_view(request, pk):
    asset = get_object_or_404(
        Asset.objects.select_related(
            "assigned_user",
            "acquisition_batch"
        ),
        pk=pk,
    )
   
    # ------------------------------------------------------
    # TICKETS RELACIONADOS
    # ------------------------------------------------------

    tickets = (
        asset.tickets
        .select_related(
            "requester",
            "assigned_to",
        )
        .order_by("-created_at")
    )

    # ------------------------------------------------------
    # HISTORIAL TÉCNICO
    # ------------------------------------------------------

    interventions = (
        asset.technical_history
        .select_related(
            "technician",
            "ticket",
        )
        .order_by("-intervention_date")
    )

    total_intervention_cost = sum(
        intervention.cost
        for intervention in interventions
    )

    # ------------------------------------------------------
    # HISTORIAL DE CUSTODIA
    # ------------------------------------------------------

    custody_movements = (
        asset.custody_movements
        .select_related(
            "previous_custodian",
            "recipient",
            "delivery_responsible",
            "authorizing_director",
            "created_by",
        )
        .order_by(
            "-movement_date",
            "-created_at",
        )
    )

    custody_movement_count = custody_movements.count()

    last_custody_movement = custody_movements.first()

    delivered_custody_movements = custody_movements.filter(
        status=(
            AssetCustodyMovement
            .MovementStatus
            .DELIVERED
        )
    ).count()

    pending_custody_movements = custody_movements.filter(
        status=(
            AssetCustodyMovement
            .MovementStatus
            .PENDING_SIGNATURE
        )
    ).count()

    return render(
        request,
        "inventory/asset_detail.html",
        {
            "asset": asset,
            
            # Tickets
            "tickets": tickets,

            # Intervenciones técnicas
            "interventions": interventions,
            "total_intervention_cost": (
                total_intervention_cost
            ),

            # Custodia
            "custody_movements": custody_movements,
            "custody_movement_count": (
                custody_movement_count
            ),
            "last_custody_movement": (
                last_custody_movement
            ),
            "completed_custody_movements": (
                delivered_custody_movements
            ),
            "pending_custody_movements": (
                pending_custody_movements
            ),

            # Permisos
            "can_register_intervention": (
                can_register_intervention(
                    request.user
                )
            ),
            "can_manage_deliveries": (
                can_manage_deliveries(
                    request.user
                )
            ),
        },
    )


# ==========================================================
# EDITAR ACTIVO
# ==========================================================

@login_required
def asset_update_view(request, pk):
    if not can_manage_inventory(request.user):
        raise PermissionDenied(
            "No tiene permisos para editar activos."
        )

    asset = get_object_or_404(
        Asset,
        pk=pk,
    )

    if request.method == "POST":
        form = AssetForm(
            request.POST,
            instance=asset,
        )

        if form.is_valid():
            form.save()

            return redirect(
                "inventory:asset_detail",
                pk=asset.pk,
            )

    else:
        form = AssetForm(
            instance=asset,
        )

    return render(
        request,
        "inventory/asset_form.html",
        {
            "form": form,
            "editing": True,
            "asset": asset,
        },
    )


# ==========================================================
# REGISTRAR INTERVENCIÓN TÉCNICA
# SPRINT 13
# ==========================================================

@login_required
def technical_history_create_view(request, asset_pk):
    if not can_register_intervention(request.user):
        raise PermissionDenied(
            "No tiene permisos para registrar "
            "intervenciones técnicas."
        )

    asset = get_object_or_404(
        Asset.objects.select_related(
            "assigned_user",
            "acquisition_batch",
        ),
        pk=asset_pk,
    )

    if request.method == "POST":
        form = AssetTechnicalHistoryForm(
            request.POST,
            asset=asset,
        )

        # El activo se asigna antes de validar para comprobar
        # que el ticket seleccionado pertenece al equipo.
        form.instance.asset = asset

        if form.is_valid():
            intervention = form.save(
                commit=False
            )

            intervention.asset = asset
            intervention.save()

            return redirect(
                "inventory:asset_detail",
                pk=asset.pk,
            )

    else:
        initial = {}

        # Si el usuario autenticado es técnico,
        # queda seleccionado automáticamente.
        if request.user.role == "TECHNICIAN":
            initial["technician"] = request.user

        # Permite abrir el formulario desde un ticket
        # y dejarlo preseleccionado.
        ticket_id = request.GET.get("ticket")

        if ticket_id:
            related_ticket = (
                asset.tickets
                .filter(pk=ticket_id)
                .first()
            )

            if related_ticket:
                initial["ticket"] = related_ticket

        form = AssetTechnicalHistoryForm(
            asset=asset,
            initial=initial,
        )

        form.instance.asset = asset

    return render(
        request,
        "inventory/technical_history_form.html",
        {
            "asset": asset,
            "form": form,
            "editing": False,
        },
    )


@login_required
def my_asset_list(request):
    """Vista para mostrar los equipos asignados al usuario actual."""
    
    # ==========================================================
    # SOLO EQUIPOS ASIGNADOS AL USUARIO ACTUAL
    # ==========================================================
    
    assets = Asset.objects.filter(
        assigned_user=request.user,
    ).exclude(
        operational_status=Asset.OperationalStatus.RETIRED,
    ).select_related(
        "branch", "physical_location"
    ).order_by(
        'operational_status',
        'asset_type',
        'brand',
    )

    # Estadísticas
    total_count = assets.count()
    operative_count = assets.filter(
        operational_status=Asset.OperationalStatus.OPERATIONAL
    ).count()
    maintenance_count = assets.filter(
        operational_status__in=[
            Asset.OperationalStatus.MAINTENANCE,
            Asset.OperationalStatus.OBSERVATION,
        ]
    ).count()

    context = {
        'assets': assets,
        'total_count': total_count,
        'operative_count': operative_count,
        'maintenance_count': maintenance_count,
    }

    return render(request, 'inventory/my_asset_list.html', context)


def _add_service_errors(form, error):
    if hasattr(error, "message_dict"):
        for field, errors in error.message_dict.items():
            target = field if field in form.fields else None
            for message in errors:
                form.add_error(target, message)
    else:
        form.add_error(None, error)


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def stock_product_list_view(request):
    products = StockProduct.objects.select_related("category").annotate(
        stock_total=Coalesce(Sum("balances__quantity"), 0)
    )
    search = request.GET.get("q", "").strip()
    category = request.GET.get("category", "").strip()
    active = request.GET.get("active", "").strip()
    branch = request.GET.get("branch", "").strip()
    availability = request.GET.get("availability", "").strip()

    if search:
        products = products.filter(
            Q(name__icontains=search)
            | Q(reference_code__icontains=search)
            | Q(brand__icontains=search)
            | Q(model__icontains=search)
        )
    if category:
        products = products.filter(category_id=category)
    if active in {"true", "false"}:
        products = products.filter(is_active=(active == "true"))
    if branch:
        products = products.filter(balances__branch_id=branch).distinct()
    if availability == "out":
        products = products.filter(stock_total=0)
    elif availability == "low":
        products = products.filter(
            stock_total__gt=0,
            stock_total__lte=F("minimum_stock"),
        )
    elif availability == "available":
        products = products.filter(stock_total__gt=F("minimum_stock"))

    return render(
        request,
        "inventory/stock_product_list.html",
        {
            "products": products,
            "categories": StockCategory.objects.order_by("name"),
            "branches": Asset._meta.get_field("branch").remote_field.model.objects.filter(
                is_active=True
            ),
            "filters": request.GET,
        },
    )


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def stock_product_detail_view(request, pk):
    product = get_object_or_404(
        StockProduct.objects.select_related("category", "default_location"), pk=pk
    )
    balances = product.balances.select_related(
        "branch", "organizational_location"
    ).order_by("branch__name", "organizational_location__name")
    movements = product.stock_movements.select_related(
        "balance__branch",
        "balance__organizational_location",
        "performed_by",
    ).order_by("-movement_date", "-created_at")[:50]
    total_stock = balances.aggregate(total=Coalesce(Sum("quantity"), 0))["total"]
    return render(
        request,
        "inventory/stock_product_detail.html",
        {
            "product": product,
            "balances": balances,
            "movements": movements,
            "total_stock": total_stock,
        },
    )


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def stock_product_create_view(request):
    form = StockProductForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        product = form.save()
        messages.success(request, "Producto de stock registrado.")
        return redirect("inventory:stock_product_detail", pk=product.pk)
    return render(
        request,
        "inventory/stock_product_form.html",
        {"form": form, "editing": False},
    )


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def stock_product_update_view(request, pk):
    product = get_object_or_404(StockProduct, pk=pk)
    form = StockProductForm(request.POST or None, instance=product)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Producto actualizado.")
        return redirect("inventory:stock_product_detail", pk=product.pk)
    return render(
        request,
        "inventory/stock_product_form.html",
        {"form": form, "editing": True, "product": product},
    )


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def stock_category_list_view(request):
    return render(
        request,
        "inventory/stock_category_list.html",
        {"categories": StockCategory.objects.annotate(product_count=Count("products"))},
    )


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def stock_category_create_view(request):
    form = StockCategoryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Categoría registrada.")
        return redirect("inventory:stock_category_list")
    return render(
        request,
        "inventory/stock_category_form.html",
        {"form": form, "editing": False},
    )


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def stock_category_update_view(request, pk):
    category = get_object_or_404(StockCategory, pk=pk)
    form = StockCategoryForm(request.POST or None, instance=category)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Categoría actualizada.")
        return redirect("inventory:stock_category_list")
    return render(
        request,
        "inventory/stock_category_form.html",
        {"form": form, "editing": True, "category": category},
    )


def _stock_operation_view(request, *, form_class, service, title):
    form = form_class(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            service(
                product=data["product"],
                branch=data["branch"],
                organizational_location=data["organizational_location"],
                quantity=data["quantity"],
                reason=data["reason"],
                performed_by=request.user,
                observation=data["observation"],
                document_reference=data["document_reference"],
            )
        except ValidationError as error:
            _add_service_errors(form, error)
        else:
            messages.success(request, f"{title} registrada correctamente.")
            return redirect("inventory:stock_product_detail", pk=data["product"].pk)
    return render(
        request,
        "inventory/stock_operation_form.html",
        {"form": form, "title": title},
    )


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def stock_entry_view(request):
    return _stock_operation_view(
        request,
        form_class=StockEntryForm,
        service=register_stock_entry,
        title="Entrada de stock",
    )


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def stock_exit_view(request):
    return _stock_operation_view(
        request,
        form_class=StockExitForm,
        service=register_stock_exit,
        title="Salida de stock",
    )


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def stock_transfer_view(request):
    form = StockTransferForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            transfer_stock(
                product=data["product"],
                source_branch=data["source_branch"],
                source_location=data["source_location"],
                destination_branch=data["destination_branch"],
                destination_location=data["destination_location"],
                quantity=data["quantity"],
                performed_by=request.user,
                observation=data["observation"],
                document_reference=data["document_reference"],
            )
        except ValidationError as error:
            _add_service_errors(form, error)
        else:
            messages.success(request, "Transferencia registrada correctamente.")
            return redirect("inventory:stock_product_detail", pk=data["product"].pk)
    return render(
        request,
        "inventory/stock_transfer_form.html",
        {"form": form},
    )


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def documented_stock_entry_list_view(request):
    entries = StockEntryOperation.objects.select_related("created_by").annotate(line_count=Count("lines"))
    search = request.GET.get("q", "").strip()
    if search:
        entries = entries.filter(Q(number__icontains=search) | Q(invoice_number__icontains=search) | Q(purchase_order_number__icontains=search) | Q(delivery_note_number__icontains=search) | Q(supplier__icontains=search))
    for field in ("status", "reason"):
        value = request.GET.get(field, "").strip()
        if value:
            entries = entries.filter(**{field: value})
    supplier = request.GET.get("supplier", "").strip()
    if supplier:
        entries = entries.filter(supplier__icontains=supplier)
    if request.GET.get("date_from"):
        entries = entries.filter(entry_date__gte=request.GET["date_from"])
    if request.GET.get("date_to"):
        entries = entries.filter(entry_date__lte=request.GET["date_to"])
    return render(request, "inventory/stock_entry_list.html", {"entries": entries, "statuses": StockEntryOperation.Status.choices, "reasons": StockEntryOperationForm().fields["reason"].choices, "filters": request.GET})


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def documented_stock_entry_create_view(request):
    form = StockEntryOperationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        entry = form.save(commit=False)
        entry.created_by = request.user
        entry.save()
        messages.success(request, "Entrada documentada creada como borrador.")
        return redirect("inventory:documented_stock_entry_detail", pk=entry.pk)
    return render(request, "inventory/stock_entry_form.html", {"form": form, "editing": False})


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def documented_stock_entry_update_view(request, pk):
    entry = get_object_or_404(StockEntryOperation, pk=pk)
    if entry.status != StockEntryOperation.Status.DRAFT:
        raise PermissionDenied("Solo pueden editarse entradas en borrador.")
    form = StockEntryOperationForm(request.POST or None, instance=entry)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Borrador actualizado.")
        return redirect("inventory:documented_stock_entry_detail", pk=entry.pk)
    return render(request, "inventory/stock_entry_form.html", {"form": form, "editing": True, "entry": entry})


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def documented_stock_entry_detail_view(request, pk):
    entry = get_object_or_404(StockEntryOperation.objects.select_related("created_by", "confirmed_by"), pk=pk)
    return render(request, "inventory/stock_entry_detail.html", {"entry": entry, "lines": entry.lines.select_related("product", "branch", "organizational_location", "movement"), "documents": entry.documents.select_related("uploaded_by")})


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def documented_stock_entry_add_line_view(request, pk):
    entry = get_object_or_404(StockEntryOperation, pk=pk, status=StockEntryOperation.Status.DRAFT)
    form = StockEntryLineForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        line = form.save(commit=False)
        line.entry = entry
        line.save()
        messages.success(request, "Producto agregado.")
        return redirect("inventory:documented_stock_entry_detail", pk=entry.pk)
    return render(request, "inventory/stock_entry_line_form.html", {"form": form, "entry": entry})


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def documented_stock_entry_delete_line_view(request, pk, line_pk):
    entry = get_object_or_404(StockEntryOperation, pk=pk, status=StockEntryOperation.Status.DRAFT)
    line = get_object_or_404(StockEntryLine, pk=line_pk, entry=entry)
    if request.method != "POST":
        raise PermissionDenied("La eliminación requiere POST.")
    line.delete()
    messages.success(request, "Línea eliminada.")
    return redirect("inventory:documented_stock_entry_detail", pk=entry.pk)


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def documented_stock_entry_add_document_view(request, pk):
    entry = get_object_or_404(StockEntryOperation, pk=pk, status=StockEntryOperation.Status.DRAFT)
    form = StockEntryDocumentForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        document = form.save(commit=False)
        document.entry = entry
        document.uploaded_by = request.user
        document.save()
        messages.success(request, "Documento adjuntado.")
        return redirect("inventory:documented_stock_entry_detail", pk=entry.pk)
    return render(request, "inventory/stock_entry_document_form.html", {"form": form, "entry": entry})


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def documented_stock_entry_document_download_view(request, pk, document_pk):
    document = get_object_or_404(StockEntryDocument, pk=document_pk, entry_id=pk)
    return FileResponse(document.file.open("rb"), as_attachment=True, filename=document.file.name.rsplit("/", 1)[-1])


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def documented_stock_entry_confirm_view(request, pk):
    if request.method != "POST":
        raise PermissionDenied("La confirmación requiere POST.")
    entry = get_object_or_404(StockEntryOperation, pk=pk)
    try:
        confirm_stock_entry(entry=entry, confirmed_by=request.user)
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
    else:
        messages.success(request, "Entrada confirmada y stock actualizado.")
    return redirect("inventory:documented_stock_entry_detail", pk=entry.pk)


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def documented_stock_entry_cancel_view(request, pk):
    if request.method != "POST":
        raise PermissionDenied("La cancelación requiere POST.")
    entry = get_object_or_404(StockEntryOperation, pk=pk, status=StockEntryOperation.Status.DRAFT)
    entry.status = StockEntryOperation.Status.CANCELLED
    entry.save(update_fields=["status", "updated_at"])
    messages.success(request, "Borrador cancelado sin afectar el stock.")
    return redirect("inventory:documented_stock_entry_detail", pk=entry.pk)


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def stock_movement_list_view(request):
    movements = StockMovement.objects.select_related(
        "product__category", "balance__branch",
        "balance__organizational_location", "performed_by",
    )
    search = request.GET.get("q", "").strip()
    filters = {
        "product_id": request.GET.get("product", "").strip(),
        "product__category_id": request.GET.get("category", "").strip(),
        "direction": request.GET.get("direction", "").strip(),
        "reason": request.GET.get("reason", "").strip(),
        "balance__branch_id": request.GET.get("branch", "").strip(),
        "balance__organizational_location_id": request.GET.get("location", "").strip(),
        "performed_by_id": request.GET.get("user", "").strip(),
        "movement_date__date__gte": request.GET.get("date_from", "").strip(),
        "movement_date__date__lte": request.GET.get("date_to", "").strip(),
    }
    if search:
        movements = movements.filter(
            Q(product__reference_code__icontains=search)
            | Q(product__name__icontains=search)
            | Q(product__brand__icontains=search)
            | Q(product__model__icontains=search)
        )
    for lookup, value in filters.items():
        if value:
            movements = movements.filter(**{lookup: value})
    return render(request, "inventory/stock_movement_list.html", {
        "movements": movements.order_by("-movement_date", "-created_at"),
        "products": StockProduct.objects.order_by("name"),
        "categories": StockCategory.objects.order_by("name"),
        "branches": Asset._meta.get_field("branch").remote_field.model.objects.filter(is_active=True),
        "locations": StockBalance.objects.values_list("organizational_location_id", "organizational_location__name").distinct().order_by("organizational_location__name"),
        "users": User.objects.filter(is_active=True).order_by("first_name", "last_name"),
        "direction_choices": StockMovement.Direction.choices,
        "reason_choices": StockMovement.Reason.choices,
        "filters": request.GET,
    })


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def stock_delivery_list_view(request):
    deliveries = StockDelivery.objects.select_related("recipient", "department", "branch", "created_by").annotate(line_count=Count("lines"))
    search = request.GET.get("q", "").strip()
    if search:
        deliveries = deliveries.filter(Q(number__icontains=search) | Q(recipient_name__icontains=search) | Q(department_name__icontains=search))
    for field in ("status", "department", "recipient", "branch"):
        value = request.GET.get(field, "").strip()
        if value:
            deliveries = deliveries.filter(**{f"{field}_id" if field != "status" else field: value})
    if request.GET.get("date"):
        deliveries = deliveries.filter(delivery_date=request.GET["date"])
    return render(request, "inventory/stock_delivery_list.html", {"deliveries": deliveries, "statuses": StockDelivery.Status.choices, "filters": request.GET})


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def stock_delivery_create_view(request):
    form = StockDeliveryForm(request.POST or None, initial={"delivery_responsible": request.user})
    if request.method == "POST" and form.is_valid():
        delivery = form.save(commit=False)
        delivery.created_by = request.user
        delivery.save()
        return redirect("inventory:stock_delivery_detail", pk=delivery.pk)
    return render(request, "inventory/stock_delivery_form.html", {"form": form, "editing": False})


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def stock_delivery_update_view(request, pk):
    delivery = get_object_or_404(StockDelivery, pk=pk)
    if delivery.status != StockDelivery.Status.DRAFT:
        raise PermissionDenied("Solo puede editarse una entrega en borrador.")
    form = StockDeliveryForm(request.POST or None, instance=delivery)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("inventory:stock_delivery_detail", pk=delivery.pk)
    return render(request, "inventory/stock_delivery_form.html", {"form": form, "editing": True, "delivery": delivery})


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def stock_delivery_detail_view(request, pk):
    delivery = get_object_or_404(StockDelivery.objects.select_related("recipient", "department", "branch", "location", "delivery_responsible", "authorized_by", "created_by", "completed_by"), pk=pk)
    return render(request, "inventory/stock_delivery_detail.html", {"delivery": delivery, "lines": delivery.lines.select_related("product", "source_branch", "source_location", "movement")})


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def stock_delivery_add_line_view(request, pk):
    delivery = get_object_or_404(StockDelivery, pk=pk, status=StockDelivery.Status.DRAFT)
    form = StockDeliveryLineForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        line = form.save(commit=False)
        line.delivery = delivery
        line.save()
        return redirect("inventory:stock_delivery_detail", pk=delivery.pk)
    return render(request, "inventory/stock_delivery_line_form.html", {"form": form, "delivery": delivery})


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def stock_delivery_delete_line_view(request, pk, line_pk):
    if request.method != "POST":
        raise PermissionDenied("La eliminación requiere POST.")
    delivery = get_object_or_404(StockDelivery, pk=pk, status=StockDelivery.Status.DRAFT)
    get_object_or_404(StockDeliveryLine, pk=line_pk, delivery=delivery).delete()
    return redirect("inventory:stock_delivery_detail", pk=delivery.pk)


def _delivery_state_action(request, pk, service, success):
    if request.method != "POST":
        raise PermissionDenied("La acción requiere POST.")
    delivery = get_object_or_404(StockDelivery, pk=pk)
    try:
        service(delivery=delivery, **({"completed_by": request.user} if service is complete_stock_delivery else {}))
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
    else:
        messages.success(request, success)
    return redirect("inventory:stock_delivery_detail", pk=delivery.pk)


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def stock_delivery_prepare_view(request, pk):
    return _delivery_state_action(request, pk, prepare_stock_delivery, "Entrega preparada.")


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def stock_delivery_complete_view(request, pk):
    return _delivery_state_action(request, pk, complete_stock_delivery, "Entrega completada y stock descontado.")


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def stock_delivery_cancel_view(request, pk):
    if request.method != "POST":
        raise PermissionDenied("La cancelación requiere POST.")
    delivery = get_object_or_404(StockDelivery, pk=pk, status__in=[StockDelivery.Status.DRAFT, StockDelivery.Status.PREPARED, StockDelivery.Status.PENDING_SIGNATURE])
    StockDelivery.objects.filter(pk=delivery.pk).update(status=StockDelivery.Status.CANCELLED)
    return redirect("inventory:stock_delivery_detail", pk=delivery.pk)


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def stock_delivery_pdf_view(request, pk):
    delivery = get_object_or_404(StockDelivery, pk=pk, status__in=[StockDelivery.Status.PREPARED, StockDelivery.Status.PENDING_SIGNATURE, StockDelivery.Status.COMPLETED])
    return FileResponse(generate_stock_delivery_pdf(delivery), content_type="application/pdf", filename=f"{delivery.number}.pdf")


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def stock_delivery_signed_document_upload_view(request, pk):
    delivery = get_object_or_404(StockDelivery, pk=pk, status__in=[StockDelivery.Status.PREPARED, StockDelivery.Status.PENDING_SIGNATURE, StockDelivery.Status.COMPLETED])
    if delivery.signed_document:
        raise PermissionDenied("La entrega ya posee un acta firmada; no puede reemplazarse silenciosamente.")
    form = StockDeliverySignedDocumentForm(request.POST or None, request.FILES or None, instance=delivery)
    if request.method == "POST" and form.is_valid():
        uploaded = form.cleaned_data["signed_document"]
        field = StockDelivery._meta.get_field("signed_document")
        name = field.storage.save(field.generate_filename(delivery, uploaded.name), uploaded)
        StockDelivery.objects.filter(pk=delivery.pk).update(signed_document=name, signed_document_verified=form.cleaned_data["signed_document_verified"], signed_document_uploaded_by=request.user, signed_document_uploaded_at=timezone.now())
        return redirect("inventory:stock_delivery_detail", pk=delivery.pk)
    return render(request, "inventory/stock_delivery_signed_form.html", {"form": form, "delivery": delivery})


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def stock_delivery_signed_document_download_view(request, pk):
    delivery = get_object_or_404(StockDelivery, pk=pk)
    if not delivery.signed_document:
        raise PermissionDenied("La entrega no posee un acta firmada.")
    return FileResponse(delivery.signed_document.open("rb"), as_attachment=True, filename=delivery.signed_document.name.rsplit("/", 1)[-1])


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def ticket_stock_usage_list_view(request):
    usages = TicketStockUsage.objects.select_related("ticket", "registered_by", "confirmed_by").annotate(line_count=Count("lines"))
    search = request.GET.get("q", "").strip()
    if search:
        usages = usages.filter(Q(ticket__ticket_number__icontains=search) | Q(ticket_number__icontains=search) | Q(ticket__title__icontains=search))
    if request.GET.get("status"):
        usages = usages.filter(status=request.GET["status"])
    return render(request, "inventory/ticket_stock_usage_list.html", {"usages": usages, "statuses": TicketStockUsage.Status.choices, "filters": request.GET})


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def ticket_stock_usage_create_view(request):
    form = TicketStockUsageForm(request.POST or None, initial={"ticket": request.GET.get("ticket")})
    if request.method == "POST" and form.is_valid():
        usage = form.save(commit=False)
        usage.registered_by = request.user
        usage.save()
        return redirect("inventory:ticket_stock_usage_detail", pk=usage.pk)
    return render(request, "inventory/ticket_stock_usage_form.html", {"form": form, "editing": False})


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def ticket_stock_usage_update_view(request, pk):
    usage = get_object_or_404(TicketStockUsage, pk=pk)
    if usage.status != TicketStockUsage.Status.DRAFT:
        raise PermissionDenied("Solo puede editarse un consumo en borrador.")
    form = TicketStockUsageForm(request.POST or None, instance=usage)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("inventory:ticket_stock_usage_detail", pk=usage.pk)
    return render(request, "inventory/ticket_stock_usage_form.html", {"form": form, "editing": True, "usage": usage})


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def ticket_stock_usage_detail_view(request, pk):
    usage = get_object_or_404(TicketStockUsage.objects.select_related("ticket", "registered_by", "confirmed_by"), pk=pk)
    return render(request, "inventory/ticket_stock_usage_detail.html", {"usage": usage, "lines": usage.lines.select_related("product", "source_branch", "source_location", "stock_movement")})


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def ticket_stock_usage_add_line_view(request, pk):
    usage = get_object_or_404(TicketStockUsage, pk=pk, status=TicketStockUsage.Status.DRAFT)
    form = TicketStockUsageLineForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        line = form.save(commit=False)
        line.usage = usage
        line.save()
        return redirect("inventory:ticket_stock_usage_detail", pk=usage.pk)
    return render(request, "inventory/ticket_stock_usage_line_form.html", {"form": form, "usage": usage})


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def ticket_stock_usage_delete_line_view(request, pk, line_pk):
    if request.method != "POST":
        raise PermissionDenied("La eliminación requiere POST.")
    usage = get_object_or_404(TicketStockUsage, pk=pk, status=TicketStockUsage.Status.DRAFT)
    get_object_or_404(TicketStockUsageLine, pk=line_pk, usage=usage).delete()
    return redirect("inventory:ticket_stock_usage_detail", pk=usage.pk)


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def ticket_stock_usage_confirm_view(request, pk):
    if request.method != "POST":
        raise PermissionDenied("La confirmación requiere POST.")
    usage = get_object_or_404(TicketStockUsage, pk=pk)
    try:
        confirm_ticket_stock_usage(usage=usage, confirmed_by=request.user)
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
    else:
        messages.success(request, "Consumo confirmado y stock descontado.")
    return redirect("inventory:ticket_stock_usage_detail", pk=usage.pk)


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def ticket_stock_usage_cancel_view(request, pk):
    if request.method != "POST":
        raise PermissionDenied("La cancelación requiere POST.")
    usage = get_object_or_404(TicketStockUsage, pk=pk, status=TicketStockUsage.Status.DRAFT)
    usage.status = TicketStockUsage.Status.CANCELLED
    usage.save(update_fields=["status", "updated_at"])
    return redirect("inventory:ticket_stock_usage_detail", pk=usage.pk)
