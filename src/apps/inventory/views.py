from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)

from apps.deliveries.models import AssetCustodyMovement
from apps.accounts.access import (
    can_manage_deliveries,
    can_manage_inventory,
    can_register_intervention,
    roles_required,
)


from .forms import (
    AssetForm,
    AssetTechnicalHistoryForm,
)
from .models import Asset


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
