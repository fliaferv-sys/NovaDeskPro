from apps.directory.person_references import enrich_person_records
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count
from django.shortcuts import redirect, render, get_object_or_404

from apps.tickets.models import Ticket

from .models import (
    Consumable,
    ConsumableCompatibility,
    PrintingDevice,
)
from apps.accounts.access import roles_required
from .forms import PrintingTicketStockUsageForm
from .services import register_printing_ticket_stock_usage
from .connectivity import with_connectivity


# ==========================================================
# DASHBOARD PRINCIPAL
# ==========================================================
@login_required
@roles_required("ADMIN", "SUPERVISOR", "AUDITOR", "TECHNICIAN")
def psline_dashboard(request):

    devices = list(with_connectivity(PrintingDevice.objects.filter(is_active=True).select_related("asset")))

    total_devices = len(devices)

    online_devices = sum(d.effective_connection_status == "ONLINE" for d in devices)
    offline_devices = sum(d.effective_connection_status == "OFFLINE" for d in devices)
    unknown_devices = total_devices - online_devices - offline_devices

    consumables = Consumable.objects.filter(is_active=True).select_related(
        "stock_product"
    ).prefetch_related("stock_product__balances")

    toner_total = sum(
        c.operational_stock for c in consumables
        if c.consumable_type == Consumable.ConsumableType.TONER
    )

    image_unit_total = sum(
        c.operational_stock for c in consumables
        if c.consumable_type == Consumable.ConsumableType.DRUM
    )

    low_stock_count = sum(
        1 for c in consumables
        if c.operational_stock > 0 and c.is_below_minimum_stock
    )

    out_of_stock_count = sum(
        1 for c in consumables
        if c.operational_stock <= 0
    )

    # =========================
    # 🔥 RESUMEN PRO POR MODELO
    # =========================

    model_summary_map = {}

    compatibilities = ConsumableCompatibility.objects.filter(
        is_active=True,
        printing_device__is_active=True,
        consumable__is_active=True,
    ).select_related(
        "printing_device__asset",
        "consumable"
    )

    # Agrupar dispositivos
    for device in devices:
        brand = device.effective_brand or "—"
        model = device.effective_model or "—"
        key = f"{brand}|||{model}"

        if key not in model_summary_map:
            model_summary_map[key] = {
                "brand": brand,
                "model": model,
                "total_devices": 0,
                "online_devices": 0,
                "offline_devices": 0,
                "unknown_devices": 0,
                "toner_total": 0,
                "toner_low": 0,
                "toner_out": 0,
                "drum_total": 0,
                "drum_low": 0,
                "drum_out": 0,
                "is_inventory_only": False,
            }

        model_summary_map[key]["total_devices"] += 1

        status = device.effective_connection_status
        if status == "ONLINE":
            model_summary_map[key]["online_devices"] += 1
        elif status == "OFFLINE":
            model_summary_map[key]["offline_devices"] += 1
        else:
            model_summary_map[key]["unknown_devices"] += 1

    # Evitar duplicados
    seen = set()
    linked_consumable_ids = set()

    # Consumibles por modelo
    for comp in compatibilities:
        brand = comp.printing_device.effective_brand or "—"
        model = comp.printing_device.effective_model or "—"
        key = f"{brand}|||{model}"

        if key not in model_summary_map:
            continue

        pair = (key, comp.consumable_id)
        if pair in seen:
            continue
        seen.add(pair)
        linked_consumable_ids.add(comp.consumable_id)

        consumable = comp.consumable

        if consumable.consumable_type == Consumable.ConsumableType.TONER:
            model_summary_map[key]["toner_total"] += consumable.operational_stock

            if consumable.operational_stock <= 0:
                model_summary_map[key]["toner_out"] += 1
            elif consumable.is_below_minimum_stock:
                model_summary_map[key]["toner_low"] += 1

        elif consumable.consumable_type == Consumable.ConsumableType.DRUM:
            model_summary_map[key]["drum_total"] += consumable.operational_stock

            if consumable.operational_stock <= 0:
                model_summary_map[key]["drum_out"] += 1
            elif consumable.is_below_minimum_stock:
                model_summary_map[key]["drum_low"] += 1

    # Mostrar también el stock que todavía no tiene una impresora compatible
    # asociada. De este modo, los totales superiores coinciden con el resumen.
    for consumable in consumables:
        if consumable.pk in linked_consumable_ids:
            continue

        brand = " ".join((consumable.manufacturer or "—").split()).upper()
        raw_model = consumable.model or consumable.name
        model = "".join(raw_model.split()).upper()
        key = f"STOCK|||{brand}|||{model}"
        item = model_summary_map.setdefault(key, {
            "brand": brand,
            "model": model,
            "total_devices": 0,
            "online_devices": 0,
            "offline_devices": 0,
            "unknown_devices": 0,
            "toner_total": 0,
            "toner_low": 0,
            "toner_out": 0,
            "drum_total": 0,
            "drum_low": 0,
            "drum_out": 0,
            "is_inventory_only": True,
        })
        if consumable.consumable_type == Consumable.ConsumableType.TONER:
            item["toner_total"] += consumable.operational_stock
            item["toner_out"] += int(consumable.operational_stock <= 0)
            item["toner_low"] += int(
                consumable.operational_stock > 0 and consumable.is_below_minimum_stock
            )
        elif consumable.consumable_type == Consumable.ConsumableType.DRUM:
            item["drum_total"] += consumable.operational_stock
            item["drum_out"] += int(consumable.operational_stock <= 0)
            item["drum_low"] += int(
                consumable.operational_stock > 0 and consumable.is_below_minimum_stock
            )

    model_summary = sorted(
        model_summary_map.values(),
        key=lambda x: (-x["total_devices"], x["brand"], x["model"])
    )

    context = {
        "total_devices": total_devices,
        "online_devices": online_devices,
        "offline_devices": offline_devices,
        "unknown_devices": unknown_devices,
        "toner_total": toner_total,
        "image_unit_total": image_unit_total,
        "low_stock_count": low_stock_count,
        "out_of_stock_count": out_of_stock_count,
        "model_summary": model_summary,
    }

    return render(request, "printing/psline_dashboard.html", context)


# ==========================================================
# LISTADO FILTRADO POR MODELO (CON KPIs Y ALERTAS)
# ==========================================================
@login_required
@roles_required("ADMIN", "SUPERVISOR", "AUDITOR", "TECHNICIAN")
def printing_devices_by_model(request):
    from .inventory_users import inventory_context
    return render(request, "printing/printing_devices_by_model.html", inventory_context(request))


# ==========================================================
# DETALLE DE EQUIPO
# ==========================================================
@login_required
@roles_required("ADMIN", "SUPERVISOR", "AUDITOR", "TECHNICIAN")
def printing_device_detail(request, pk):
    device = get_object_or_404(
        with_connectivity(PrintingDevice.objects.select_related(
            "asset",
            "responsible_user__organizational_unit",
            "responsible_user__branch",
            "asset__assigned_user",
            "asset__branch",
            "asset__physical_location",
            "branch",
            "organizational_location",
        )),
        pk=pk,
    )

    enrich_person_records([device], "responsible_identity", "responsible_user")
    from .historical_notes import with_historical_labels
    with_historical_labels(device)
    from .inventory_users import assignment_context
    context = {
        **assignment_context(request, device),
        "current_network_detections": device.network_detections.filter(is_current=True),
        "device": device,
        "devices": [device],
        "brand": device.effective_brand,
        "model": device.effective_model,
    }

    return render(
        request,
        "printing/printing_device_detail.html",
        context,
    )


@login_required
@roles_required("ADMIN", "SUPERVISOR")
def register_ticket_consumable(request, ticket_pk):
    ticket = get_object_or_404(
        Ticket.objects.select_related(
            "printing_device__asset__branch",
            "printing_device__asset__physical_location",
            "printing_device__branch",
            "printing_device__organizational_location",
        ),
        pk=ticket_pk,
    )
    printing_device = ticket.printing_device
    if printing_device is None:
        raise PermissionDenied("El ticket no tiene un equipo de impresión relacionado.")
    if not printing_device.is_active:
        raise PermissionDenied("El equipo de impresión no está activo.")

    form = PrintingTicketStockUsageForm(
        request.POST or None,
        printing_device=printing_device,
    )
    if request.method == "POST" and form.is_valid():
        try:
            usage = register_printing_ticket_stock_usage(
                ticket=ticket,
                printing_device=printing_device,
                compatibility=form.cleaned_data["compatibility"],
                stock_balance=form.cleaned_data["stock_balance"],
                quantity=form.cleaned_data["quantity"],
                observation=form.cleaned_data["observation"],
                registered_by=request.user,
            )
        except ValidationError as error:
            form.add_error(None, "; ".join(error.messages))
        else:
            messages.success(request, "Consumible registrado y stock descontado.")
            return redirect("inventory:ticket_stock_usage_detail", pk=usage.pk)

    configured_compatibilities = ConsumableCompatibility.objects.filter(
        printing_device=printing_device,
        is_active=True,
        consumable__is_active=True,
    )
    usable_compatibilities = form.fields["compatibility"].queryset
    remote_balances = form.fields["stock_balance"].queryset.exclude(
        branch=printing_device.effective_branch
    )
    return render(
        request,
        "printing/register_ticket_consumable.html",
        {
            "ticket": ticket,
            "printing_device": printing_device,
            "form": form,
            "has_configured_compatibilities": configured_compatibilities.exists(),
            "has_usable_compatibilities": usable_compatibilities.exists(),
            "has_remote_stock": remote_balances.exists(),
        },
    )
