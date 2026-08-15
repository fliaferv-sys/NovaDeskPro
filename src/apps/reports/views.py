from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.accounts.access import roles_required

from .forms import InventoryReportFilterForm, PrintingReportFilterForm, TicketReportFilterForm
from .selectors import get_inventory_report, get_printing_report, get_ticket_report


REPORT_ROLES = ("ADMIN", "SUPERVISOR", "AUDITOR")


@login_required
@roles_required(*REPORT_ROLES)
@require_GET
def reports_index_view(request):
    return render(request, "reports/index.html")


def _validated_filters(form):
    return form.cleaned_data if form.is_valid() else {}


@login_required
@roles_required(*REPORT_ROLES)
@require_GET
def ticket_report_view(request):
    form = TicketReportFilterForm(request.GET or None)
    report = get_ticket_report(_validated_filters(form))
    return render(request, "reports/tickets.html", {"form": form, "report": report})


@login_required
@roles_required(*REPORT_ROLES)
@require_GET
def inventory_report_view(request):
    form = InventoryReportFilterForm(request.GET or None)
    report = get_inventory_report(_validated_filters(form))
    return render(request, "reports/inventory.html", {"form": form, "report": report})


@login_required
@roles_required(*REPORT_ROLES)
@require_GET
def printing_report_view(request):
    form = PrintingReportFilterForm(request.GET or None)
    report = get_printing_report(_validated_filters(form))
    return render(request, "reports/printing.html", {"form": form, "report": report})
