# ==========================================================
# DASHBOARD EJECUTIVO
# SPRINT 17
# ==========================================================

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Count, Exists, OuterRef, Q
from django.db.models.functions import TruncMonth
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import (
    TechnicianAvailabilityRequest,
    TechnicianWorkday,
    User,
)
from apps.accounts.services import resolve_technician_availability_request
from apps.deliveries.models import AssetCustodyMovement
from apps.inventory.models import Asset
from apps.tickets.models import Ticket
from apps.accounts.access import roles_required
from .models import DashboardPreference
from apps.core.models import Department
from apps.tickets.models import Ticket


@login_required
@roles_required("ADMIN", "SUPERVISOR", "AUDITOR")
def executive_dashboard_view(request):
    today = timezone.localdate()
    warranty_limit = today + timedelta(days=30)

    # ======================================================
    # PREFERENCIAS PERSONALIZADAS DEL DASHBOARD
    # ======================================================

    dashboard_preference = (
        DashboardPreference.objects.filter(
            user=request.user
        ).first()
    )

    saved_dashboard_layout = (
        dashboard_preference.layout
        if dashboard_preference
        else []
    )

    saved_dashboard_chart_types = (
        dashboard_preference.chart_types
        if dashboard_preference
        else {}
    )

    # ======================================================
    # INDICADORES DE TICKETS
    # ======================================================

    total_tickets = Ticket.objects.count()

    open_tickets = Ticket.objects.filter(
        status="OPEN"
    ).count()

    in_progress_tickets = Ticket.objects.filter(
        status="IN_PROGRESS"
    ).count()

    closed_tickets = Ticket.objects.filter(
        status="CLOSED"
    ).count()

    critical_tickets = (
        Ticket.objects
        .filter(priority="CRITICAL")
        .exclude(status="CLOSED")
        .count()
    )

    # ======================================================
    # INDICADORES DE INVENTARIO
    # ======================================================

    total_assets = Asset.objects.count()

    operational_assets = Asset.objects.filter(
        operational_status="OPERATIONAL"
    ).count()

    maintenance_assets = Asset.objects.filter(
        operational_status="MAINTENANCE"
    ).count()

    out_of_service_assets = Asset.objects.filter(
        operational_status="OUT_OF_SERVICE"
    ).count()

    warranty_expiring_assets = Asset.objects.filter(
        warranty_expiration__isnull=False,
        warranty_expiration__gte=today,
        warranty_expiration__lte=warranty_limit,
    ).count()

    expired_warranty_assets = Asset.objects.filter(
        warranty_expiration__isnull=False,
        warranty_expiration__lt=today,
    ).count()

    # ======================================================
    # INDICADORES DE CUSTODIA
    # ======================================================

    total_movements = (
        AssetCustodyMovement.objects.count()
    )

    completed_movements = (
        AssetCustodyMovement.objects
        .filter(
            status=(
                AssetCustodyMovement
                .MovementStatus
                .DELIVERED
            )
        )
        .count()
    )

    pending_signature_movements = (
        AssetCustodyMovement.objects
        .filter(
            status=(
                AssetCustodyMovement
                .MovementStatus
                .PENDING_SIGNATURE
            )
        )
        .count()
    )

    delivered_assets = Asset.objects.filter(
        assigned_user__isnull=False
    ).count()

    available_assets = Asset.objects.filter(
        assigned_user__isnull=True
    ).count()

    # ======================================================
    # GRÁFICO: TICKETS POR ESTADO
    # ======================================================

    ticket_status_data = (
        Ticket.objects
        .values("status")
        .annotate(total=Count("id"))
        .order_by("status")
    )

    ticket_status_labels = []
    ticket_status_values = []

    status_display = dict(
        Ticket._meta.get_field("status").choices
    )

    for item in ticket_status_data:
        ticket_status_labels.append(
            str(
                status_display.get(
                    item["status"],
                    item["status"],
                )
            )
        )

        ticket_status_values.append(
            item["total"]
        )

    # ======================================================
    # GRÁFICO: ACTIVOS POR ESTADO OPERATIVO
    # ======================================================

    asset_status_data = (
        Asset.objects
        .values("operational_status")
        .annotate(total=Count("id"))
        .order_by("operational_status")
    )

    asset_status_labels = []
    asset_status_values = []

    operational_display = dict(
        Asset._meta.get_field(
            "operational_status"
        ).choices
    )

    for item in asset_status_data:
        asset_status_labels.append(
            str(
                operational_display.get(
                    item["operational_status"],
                    item["operational_status"],
                )
            )
        )

        asset_status_values.append(
            item["total"]
        )

    # ======================================================
    # GRÁFICO: ACTIVOS POR DEPARTAMENTO
    # ======================================================

    assets_by_department = (
        Asset.objects
        .exclude(department="")
        .values("department")
        .annotate(total=Count("id"))
        .order_by("-total")[:8]
    )

    department_labels = [
        item["department"]
        for item in assets_by_department
    ]

    department_values = [
        item["total"]
        for item in assets_by_department
    ]

    # ======================================================
    # GRÁFICO: TICKETS POR MES
    # ======================================================

    six_months_ago = (
        timezone.now()
        - timedelta(days=180)
    )

    tickets_by_month = (
        Ticket.objects
        .filter(
            created_at__gte=six_months_ago
        )
        .annotate(
            month=TruncMonth("created_at")
        )
        .values("month")
        .annotate(total=Count("id"))
        .order_by("month")
    )

    ticket_month_labels = [
        item["month"].strftime("%m/%Y")
        for item in tickets_by_month
        if item["month"]
    ]

    ticket_month_values = [
        item["total"]
        for item in tickets_by_month
        if item["month"]
    ]

    # ======================================================
    # ACTIVIDAD Y CARGA DE TRABAJO POR TÉCNICO
    # ======================================================

    technicians = (
        User.objects
        .filter(
            role=User.Role.TECHNICIAN,
            is_active=True,
        )
        .annotate(
            assigned_ticket_count=Count(
                "assigned_tickets",
                distinct=True,
            ),
            pending_ticket_count=Count(
                "assigned_tickets",
                filter=~Q(
                    assigned_tickets__status="CLOSED"
                ),
                distinct=True,
            ),
            closed_ticket_count=Count(
                "assigned_tickets",
                filter=Q(
                    assigned_tickets__status="CLOSED"
                ),
                distinct=True,
            ),
        )
        .order_by(
            "-pending_ticket_count",
            "-closed_ticket_count",
            "first_name",
            "last_name",
        )
    )

    technician_ranking = []

    technician_workload_labels = []
    technician_pending_values = []
    technician_closed_values = []

    for technician in technicians:
        assigned = (
            technician.assigned_ticket_count
        )

        pending = (
            technician.pending_ticket_count
        )

        closed = (
            technician.closed_ticket_count
        )

        performance_percentage = (
            round((closed / assigned) * 100)
            if assigned
            else 0
        )

        if assigned == 0:
            performance_label = "Sin actividad"
            performance_class = "inactive"

        elif performance_percentage >= 85:
            performance_label = "Excelente"
            performance_class = "excellent"

        elif performance_percentage >= 65:
            performance_label = "Bueno"
            performance_class = "good"

        elif performance_percentage >= 40:
            performance_label = "Regular"
            performance_class = "warning"

        else:
            performance_label = "Bajo"
            performance_class = "critical"

        full_name = (
            f"{technician.first_name} "
            f"{technician.last_name}"
        ).strip()

        technician_name = (
            full_name
            or technician.email
            or technician.username
        )

        technician_workload_labels.append(
            technician_name
        )

        technician_pending_values.append(
            pending
        )

        technician_closed_values.append(
            closed
        )

        technician_ranking.append(
            {
                "technician": technician,
                "assigned": assigned,
                "pending": pending,
                "closed": closed,
                "percentage": (
                    performance_percentage
                ),
                "performance_label": (
                    performance_label
                ),
                "performance_class": (
                    performance_class
                ),
            }
        )

    technician_ranking = (
        technician_ranking[:5]
    )

    # ======================================================
    # ALERTAS Y ACTIVIDAD RECIENTE
    # ======================================================

    warranty_alerts = (
        Asset.objects
        .filter(
            warranty_expiration__isnull=False,
            warranty_expiration__gte=today,
            warranty_expiration__lte=(
                warranty_limit
            ),
        )
        .select_related("assigned_user")
        .order_by(
            "warranty_expiration"
        )[:5]
    )

    recent_tickets = (
        Ticket.objects
        .select_related(
            "requester",
            "assigned_to",
            "asset",
        )
        .order_by("-created_at")[:5]
    )

    recent_movements = (
        AssetCustodyMovement.objects
        .select_related(
            "asset",
            "recipient",
        )
        .order_by("-movement_date")[:5]
    )

    # ======================================================
    # CONTEXTO
    # ======================================================

    context = {
        # Tickets
        "total_tickets": total_tickets,
        "open_tickets": open_tickets,
        "in_progress_tickets": (
            in_progress_tickets
        ),
        "closed_tickets": closed_tickets,
        "critical_tickets": (
            critical_tickets
        ),

        # Inventario
        "total_assets": total_assets,
        "operational_assets": (
            operational_assets
        ),
        "maintenance_assets": (
            maintenance_assets
        ),
        "out_of_service_assets": (
            out_of_service_assets
        ),
        "warranty_expiring_assets": (
            warranty_expiring_assets
        ),
        "expired_warranty_assets": (
            expired_warranty_assets
        ),

        # Custodia
        "total_movements": total_movements,
        "completed_movements": (
            completed_movements
        ),
        "pending_signature_movements": (
            pending_signature_movements
        ),
        "delivered_assets": (
            delivered_assets
        ),
        "available_assets": (
            available_assets
        ),

        # Gráficos generales
        "ticket_status_labels": (
            ticket_status_labels
        ),
        "ticket_status_values": (
            ticket_status_values
        ),
        "asset_status_labels": (
            asset_status_labels
        ),
        "asset_status_values": (
            asset_status_values
        ),
        "department_labels": (
            department_labels
        ),
        "department_values": (
            department_values
        ),
        "ticket_month_labels": (
            ticket_month_labels
        ),
        "ticket_month_values": (
            ticket_month_values
        ),

        # Gráfico de técnicos
        "technician_workload_labels": (
            technician_workload_labels
        ),
        "technician_pending_values": (
            technician_pending_values
        ),
        "technician_closed_values": (
            technician_closed_values
        ),

        # Ranking y actividad
        "technician_ranking": (
            technician_ranking
        ),
        "warranty_alerts": (
            warranty_alerts
        ),
        "recent_tickets": (
            recent_tickets
        ),
        "recent_movements": (
            recent_movements
        ),

        # Preferencias del dashboard
        "saved_dashboard_layout": (
            saved_dashboard_layout
        ),
        "saved_dashboard_chart_types": (
            saved_dashboard_chart_types
        ),
    }

    return render(
        request,
        "dashboard/executive_dashboard.html",
        context,
    )


# ==========================================================
# DASHBOARD POR DEPARTAMENTO
# ==========================================================

@login_required
@roles_required("ADMIN", "SUPERVISOR", "AUDITOR", "TECHNICIAN")
def department_dashboard_view(request):
    """
    Dashboard específico para cada departamento.
    Muestra tickets filtrados por el departamento del usuario.
    """

    department = None

    # La relación explícita del usuario es la fuente principal.
    if request.user.role != "CLIENT":
        department = request.user.department
        if department is None:
            department = Department.objects.filter(code=request.user.role).first()

    # Filtrar tickets por departamento
    if department:
        tickets = Ticket.objects.filter(department=department)
    else:
        tickets = Ticket.objects.none()

    # Estadísticas del departamento
    total = tickets.count()
    open_tickets = tickets.filter(status="OPEN").count()
    in_progress = tickets.filter(status="IN_PROGRESS").count()
    resolved = tickets.filter(status="RESOLVED").count()
    closed = tickets.filter(status="CLOSED").count()

    # Tickets pendientes (abiertos + en proceso)
    pending = open_tickets + in_progress

    # Tickets recientes (últimos 5)
    recent_tickets = tickets.order_by("-created_at")[:5]

    context = {
        "department": department,
        "total": total,
        "open": open_tickets,
        "in_progress": in_progress,
        "resolved": resolved,
        "closed": closed,
        "pending": pending,
        "recent_tickets": recent_tickets,
    }

    return render(
        request,
        "dashboard/department_dashboard.html",
        context,
    )


@login_required
@roles_required("ADMIN", "SUPERVISOR", "AUDITOR")
def technician_control_view(request):
    active_ticket = Ticket.objects.filter(
        assigned_to_id=OuterRef("technician_id"),
        status__in=[Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS],
    )
    active_workdays = (
        TechnicianWorkday.objects
        .filter(
            status=TechnicianWorkday.Status.ACTIVE,
            ended_at__isnull=True,
            scheduled_end_at__gt=timezone.now(),
        )
        .select_related("technician", "technician__department", "shift")
        .annotate(has_active_ticket=Exists(active_ticket))
        .order_by("technician__first_name", "technician__last_name")
    )
    requests = (
        TechnicianAvailabilityRequest.objects
        .select_related("technician", "technician__department", "workday", "resolved_by")
        .order_by("-requested_at")
    )
    pending_requests = requests.filter(
        status=TechnicianAvailabilityRequest.Status.PENDING,
    )
    active_workday_list = list(active_workdays)
    context = {
        "pending_requests": pending_requests,
        "recent_requests": requests.exclude(
            status=TechnicianAvailabilityRequest.Status.PENDING,
        )[:20],
        "active_workdays": active_workday_list,
        "pending_count": pending_requests.count(),
        "active_count": len(active_workday_list),
        "available_count": sum(
            item.technician.availability_status == User.AvailabilityStatus.AVAILABLE
            and not item.has_active_ticket
            for item in active_workday_list
        ),
        "unavailable_count": sum(
            item.technician.availability_status == User.AvailabilityStatus.UNAVAILABLE
            for item in active_workday_list
        ),
        "busy_count": sum(item.has_active_ticket for item in active_workday_list),
        "can_resolve": request.user.role in {User.Role.ADMIN, User.Role.SUPERVISOR},
    }
    return render(request, "dashboard/technician_control.html", context)


@login_required
@roles_required("ADMIN", "SUPERVISOR")
@require_POST
def resolve_technician_request_view(request, pk):
    availability_request = get_object_or_404(TechnicianAvailabilityRequest, pk=pk)
    decision = request.POST.get("decision")
    if decision not in {"approve", "reject"}:
        messages.error(request, "La decisión indicada no es válida.")
        return redirect("dashboard:technician_control")
    try:
        resolve_technician_availability_request(
            availability_request,
            request.user,
            approve=decision == "approve",
            resolution_note=request.POST.get("resolution_note", ""),
        )
        messages.success(request, "La solicitud fue resuelta correctamente.")
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
    return redirect("dashboard:technician_control")
