"""Local inventory search and audited printer usage associations."""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Case, CharField, F, Prefetch, Q, Value, When
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.access import can_manage_inventory, roles_required
from apps.core.models import Department
from apps.inventory.models import OrganizationalLocation
from apps.institution.models import OrganizationalUnit
from apps.directory.person_references import enrich_person_records
from .connectivity import with_connectivity
from .models import PrintingDevice, PrintingDeviceNetworkDetection, PrintingDeviceUserAssignment
from .historical_notes import historical_search_pattern, with_historical_labels
from .presentation import with_monitoring_display


def inventory_context(request):
    params = request.GET
    devices = with_connectivity(PrintingDevice.objects.all())
    lifecycle = params.get("lifecycle", "active")
    if lifecycle != "all":
        devices = devices.filter(is_active=lifecycle != "archived")
    for field in ("brand", "model"):
        value = params.get(field, "").strip()
        if value:
            devices = devices.filter(Q(**{field: value}) | Q(**{field: "", "asset__" + field: value}))
    # Association subqueries avoid multiplying printer rows.
    assignments = PrintingDeviceUserAssignment.objects.filter(ended_at__isnull=True)
    department = params.get("department", "")
    if department:
        if department.isascii() and department.isdigit() and len(department) < 19:
            assignments = assignments.filter(user__department_id=department)
            devices = devices.filter(Q(responsible_user__department_id=department) | Q(pk__in=assignments.values("device_id")))
        else:
            devices = devices.none()
    unit = params.get("user_unit", "")
    if unit:
        unit_assignments = PrintingDeviceUserAssignment.objects.filter(ended_at__isnull=True)
        if unit.isascii() and unit.isdigit() and len(unit) < 19:
            unit_assignments = unit_assignments.filter(user__organizational_unit_id=unit)
            devices = devices.filter(Q(responsible_user__organizational_unit_id=unit) | Q(pk__in=unit_assignments.values("device_id")))
        else:
            devices = devices.none()
    installation = params.get("installation", "").strip()
    if installation:
        devices = devices.filter(asset__department=installation)
    historical_dependency = params.get("historical_dependency", "").strip()[:200]
    for term in historical_dependency.split():
        devices = devices.filter(notes__iregex=historical_search_pattern(term, dependency_only=True))
    location = params.get("location", "")
    if location:
        import uuid
        try:
            uuid.UUID(location)
        except ValueError:
            devices = devices.none()
        else:
            devices = devices.filter(Q(organizational_location_id=location) | Q(organizational_location__isnull=True, asset__physical_location_id=location))
    search = params.get("search", "").strip()[:200]
    for term in search.split():
        people = PrintingDeviceUserAssignment.objects.filter(ended_at__isnull=True).filter(
            Q(user__first_name__icontains=term) | Q(user__last_name__icontains=term)
            | Q(user__username__icontains=term) | Q(user__department__name__icontains=term)
            | Q(user__organizational_unit__name__icontains=term))
        # Responsibilities may be a local account or a persisted name without
        # any account link. Singular relations plus the assignment subquery keep
        # one result per printer even when both relationships match.
        query = (Q(pk__in=people.values("device_id"))
                 | Q(responsible_user__first_name__icontains=term)
                 | Q(responsible_user__last_name__icontains=term)
                 | Q(responsible_user__username__icontains=term)
                 | Q(responsible_user__department__name__icontains=term)
                 | Q(responsible_user__organizational_unit__name__icontains=term)
                 | Q(responsible_identity__name__icontains=term)
                 | Q(notes__iregex=historical_search_pattern(term)))
        for field in ("photocopier_id", "serial_number", "brand", "model", "ip_address", "monitored_ip",
                      "asset__internal_code", "asset__brand", "asset__model", "asset__serial_number",
                      "asset__department", "asset__location", "organizational_location__name",
                      "asset__physical_location__name", "branch__name"):
            query |= Q(**{field + "__icontains": term})
        detections = PrintingDeviceNetworkDetection.objects.filter(is_current=True).filter(
            Q(detected_ip__icontains=term) | Q(detected_mac__icontains=term))
        # Accept compact, colon-separated and hyphen-separated MAC addresses.
        compact = term.replace(":", "").replace("-", "")
        if len(compact) == 12 and all(c in "0123456789abcdefABCDEF" for c in compact):
            canonical = ":".join(compact[i:i+2] for i in range(0, 12, 2))
            detections = PrintingDeviceNetworkDetection.objects.filter(is_current=True, detected_mac__iexact=canonical)
        query |= Q(pk__in=detections.values("printing_device_id"))
        devices = devices.filter(query)
    now = timezone.now()
    valid = (Q(supports_network=True, monitored_ip=F("ip_address"), monitor_method="TCP",
               monitor_evidence__network_port=F("network_port"), monitor_ip_conflict=False,
               last_checked_at__gte=now-timedelta(seconds=settings.PRINTING_MONITOR_MAX_AGE_SECONDS),
               last_checked_at__lte=now, connection_status__in=["ONLINE", "OFFLINE"])
             & Q(ip_address__regex=r"^([0-9]{1,3}\.){3}[0-9]{1,3}$")
             & ~Q(ip_address__startswith="127.") & ~Q(ip_address__startswith="169.254.")
             & ~Q(ip_address__regex=r"^(22[4-9]|23[0-9])\.")
             & ~Q(ip_address__in=["0.0.0.0", "255.255.255.255"]))
    devices = devices.annotate(inventory_status=Case(When(valid, then=F("connection_status")), default=Value("UNKNOWN"), output_field=CharField()))
    status = params.get("status", "")
    if status in PrintingDevice.ConnectionStatus.values:
        devices = devices.filter(inventory_status=status)
    devices = devices.select_related("asset__branch", "asset__physical_location", "branch", "organizational_location",
                                     "responsible_user__organizational_unit", "responsible_user__branch").prefetch_related(
        Prefetch("network_detections", queryset=PrintingDeviceNetworkDetection.objects.filter(is_current=True), to_attr="current_network_detections"),
        Prefetch("user_assignments", queryset=PrintingDeviceUserAssignment.objects.filter(ended_at__isnull=True).select_related("user__department"), to_attr="active_user_assignments"))
    page = Paginator(devices.order_by("photocopier_id", "pk"), 50).get_page(params.get("page"))
    page.object_list = enrich_person_records(page.object_list, "responsible_identity", "responsible_user")
    for device in page.object_list:
        with_historical_labels(device)
        with_monitoring_display(device, now=now)
    query_params = params.copy()
    query_params.pop("page", None)
    return dict(devices=page, page_obj=page, total=page.paginator.count, query_params=query_params.urlencode(),
                brand=params.get("brand", ""), model=params.get("model", ""),
                departments=Department.objects.order_by("name"), user_units=OrganizationalUnit.objects.order_by("name"),
                locations=OrganizationalLocation.objects.order_by("name"),
                installation_departments=PrintingDevice.objects.exclude(asset__department="").exclude(asset__department__isnull=True).values_list("asset__department", flat=True).distinct().order_by("asset__department"))


def assignment_context(request, device):
    history = device.user_assignments.select_related("user__department", "user__organizational_unit", "assigned_by", "ended_by")
    query = request.GET.get("person_search", "").strip()[:150]
    candidates = get_user_model().objects.none()
    if query and can_manage_inventory(request.user) and device.is_active:
        candidates = get_user_model().objects.filter(is_active=True)
        for term in query.split():
            candidates = candidates.filter(Q(first_name__icontains=term) | Q(last_name__icontains=term) | Q(username__icontains=term) | Q(department__name__icontains=term) | Q(organizational_unit__name__icontains=term))
        candidates = candidates.exclude(pk__in=history.filter(ended_at__isnull=True).values("user_id")).select_related("department").order_by("last_name", "first_name", "pk")[:30]
    return dict(active_assignments=history.filter(ended_at__isnull=True),
                assignment_history=Paginator(history.filter(ended_at__isnull=False), 25).get_page(request.GET.get("history_page")),
                can_manage_users=can_manage_inventory(request.user), person_candidates=candidates, person_search=query)


@transaction.atomic
def assign_user(device_id, user_id, operator):
    if not can_manage_inventory(operator):
        raise PermissionDenied
    device = PrintingDevice.objects.select_for_update().get(pk=device_id)
    if not device.is_active:
        raise ValidationError("No se pueden agregar usuarios a una impresora archivada.")
    user = get_object_or_404(get_user_model(), pk=user_id, is_active=True)
    if device.user_assignments.filter(user=user, ended_at__isnull=True).exists():
        raise ValidationError("El usuario ya está asociado a esta impresora.")
    return PrintingDeviceUserAssignment.objects.create(device=device, user=user, assigned_by=operator)


@transaction.atomic
def end_assignment(device_id, assignment_id, operator):
    if not can_manage_inventory(operator):
        raise PermissionDenied
    assignment = get_object_or_404(PrintingDeviceUserAssignment.objects.select_for_update(), pk=assignment_id, device_id=device_id)
    if assignment.ended_at is None:
        assignment.ended_at = timezone.now()
        assignment.ended_by = operator
        assignment.save(update_fields=["ended_at", "ended_by"])


@login_required
@roles_required("ADMIN", "SUPERVISOR")
@require_POST
def manage_device_user(request, pk):
    get_object_or_404(PrintingDevice, pk=pk)
    try:
        if request.POST.get("action") == "add":
            assign_user(pk, request.POST.get("user_id"), request.user)
            messages.success(request, "Usuario agregado.")
        elif request.POST.get("action") == "remove":
            end_assignment(pk, request.POST.get("assignment_id"), request.user)
            messages.success(request, "Asociación finalizada; se conservó el historial.")
        else:
            raise ValidationError("Acción inválida.")
    except (ValidationError, IntegrityError, ValueError, TypeError) as exc:
        messages.error(request, " ".join(exc.messages) if isinstance(exc, ValidationError) else "No se pudo registrar la asociación. Revisá los datos; puede existir una asociación activa.")
    return redirect("printing:device_detail", pk=pk)
