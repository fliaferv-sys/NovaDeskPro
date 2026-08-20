from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render

from apps.accounts.models import TechnicianAvailabilityRequest, User
from apps.activity.models import ActivityLog
from apps.institution.models import InstitutionSettings
from apps.printing.models import Consumable
from apps.tickets.forms import TicketForm
from apps.tickets.models import Ticket
from .access import roles_required


class CustomLoginView(LoginView):
	template_name = "accounts/login.html"
	redirect_authenticated_user = True

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context["institution_settings"] = InstitutionSettings.get_active()
		return context


@login_required
def home_view(request):
    if request.user.role == "CLIENT" and not request.user.is_superuser:
        return redirect("tickets:ticket_create")

    if request.user.role == User.Role.TECHNICIAN and not request.user.is_superuser:
        return redirect("tickets:dashboard")

    total_tickets = Ticket.objects.count()

    open_tickets = Ticket.objects.filter(
        status="OPEN"
    ).count()

    in_progress_tickets = Ticket.objects.filter(
        status="IN_PROGRESS"
    ).count()

    waiting_tickets = Ticket.objects.filter(
        status="WAITING"
    ).count()

    resolved_tickets = Ticket.objects.filter(
        status="RESOLVED"
    ).count()

    closed_tickets = Ticket.objects.filter(
        status="CLOSED"
    ).count()

    pending_tickets = Ticket.objects.filter(
        status__in=[
            "OPEN",
            "IN_PROGRESS",
            "WAITING",
        ]
    ).count()

    low_priority_tickets = Ticket.objects.filter(
        priority="LOW"
    ).count()

    medium_priority_tickets = Ticket.objects.filter(
        priority="MEDIUM"
    ).count()

    high_priority_tickets = Ticket.objects.filter(
        priority="HIGH"
    ).count()

    critical_priority_tickets = Ticket.objects.filter(
        priority="CRITICAL"
    ).count()

    recent_activities = (
        ActivityLog.objects
        .select_related("user")
        .order_by("-created_at")[:8]
    )

    consumables = Consumable.objects.filter(is_active=True).select_related(
        "stock_product"
    ).prefetch_related("stock_product__balances")

    consumables_out_of_stock = 0
    consumables_low_stock = 0
    consumables_overstock = 0
    total_reorder_cost = Decimal("0.00")

    for consumable in consumables:
        stock = consumable.operational_stock

        if stock <= 0:
            consumables_out_of_stock += 1

        elif stock <= consumable.effective_minimum_stock:
            consumables_low_stock += 1

        elif (
            consumable.maximum_stock is not None
            and stock > consumable.maximum_stock
        ):
            consumables_overstock += 1

        if stock <= consumable.effective_minimum_stock:
            total_reorder_cost += consumable.estimated_reorder_cost

    ticket_status_labels = [
        "Abiertos",
        "En progreso",
        "En espera",
        "Resueltos",
        "Cerrados",
    ]

    ticket_status_values = [
        open_tickets,
        in_progress_tickets,
        waiting_tickets,
        resolved_tickets,
        closed_tickets,
    ]

    ticket_priority_labels = [
        "Baja",
        "Media",
        "Alta",
        "Crítica",
    ]

    ticket_priority_values = [
        low_priority_tickets,
        medium_priority_tickets,
        high_priority_tickets,
        critical_priority_tickets,
    ]

    context = {
        "total_tickets": total_tickets,
        "open_tickets": open_tickets,
        "in_progress_tickets": in_progress_tickets,
        "waiting_tickets": waiting_tickets,
        "resolved_tickets": resolved_tickets,
        "closed_tickets": closed_tickets,
        "pending_tickets": pending_tickets,
        "recent_activities": recent_activities,
        "ticket_status_labels": ticket_status_labels,
        "ticket_status_values": ticket_status_values,
        "ticket_priority_labels": ticket_priority_labels,
        "ticket_priority_values": ticket_priority_values,
        "consumables_out_of_stock": consumables_out_of_stock,
        "consumables_low_stock": consumables_low_stock,
        "consumables_overstock": consumables_overstock,
        "total_reorder_cost": total_reorder_cost,
        "pending_technician_requests": TechnicianAvailabilityRequest.objects.filter(
            status=TechnicianAvailabilityRequest.Status.PENDING,
        ).count(),
    }

    return render(
        request,
        "accounts/home.html",
        context,
    )


@login_required
def profile_view(request):
    user = (
        User.objects
        .select_related("branch", "department")
        .get(pk=request.user.pk)
    )

    return render(
        request,
        "accounts/profile.html",
        {"profile_user": user},
    )


@login_required
@roles_required("ADMIN", "SUPERVISOR", "AUDITOR")
def user_list_view(request):
	users = (
		User.objects
		.select_related("branch")
		.order_by("first_name", "last_name")
	)

	context = {
		"users": users,
	}

	return render(
		request,
		"accounts/user_list.html",
		context,
	)
