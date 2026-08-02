from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render, get_object_or_404

from .models import (
    Consumable,
    ConsumableCompatibility,
    PrintingDevice,
)
from apps.accounts.access import roles_required


# ==========================================================
# DASHBOARD PRINCIPAL
# ==========================================================
@login_required
@roles_required("ADMIN", "SUPERVISOR", "AUDITOR", "TECHNICIAN")
def psline_dashboard(request):

    devices = PrintingDevice.objects.filter(is_active=True).select_related("asset")

    total_devices = devices.count()

    online_devices = devices.filter(asset__connection_status="ONLINE").count()
    offline_devices = devices.filter(asset__connection_status="OFFLINE").count()
    unknown_devices = devices.filter(asset__connection_status="UNKNOWN").count()

    consumables = Consumable.objects.filter(is_active=True)

    toner_total = sum(
        c.current_stock for c in consumables
        if c.consumable_type == Consumable.ConsumableType.TONER
    )

    image_unit_total = sum(
        c.current_stock for c in consumables
        if c.consumable_type == Consumable.ConsumableType.DRUM
    )

    low_stock_count = sum(
        1 for c in consumables
        if c.current_stock > 0 and c.is_below_minimum_stock
    )

    out_of_stock_count = sum(
        1 for c in consumables
        if c.current_stock <= 0
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
        brand = device.asset.brand or "—"
        model = device.asset.model or "—"
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

        status = device.asset.connection_status
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
        brand = comp.printing_device.asset.brand or "—"
        model = comp.printing_device.asset.model or "—"
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
            model_summary_map[key]["toner_total"] += consumable.current_stock

            if consumable.current_stock <= 0:
                model_summary_map[key]["toner_out"] += 1
            elif consumable.is_below_minimum_stock:
                model_summary_map[key]["toner_low"] += 1

        elif consumable.consumable_type == Consumable.ConsumableType.DRUM:
            model_summary_map[key]["drum_total"] += consumable.current_stock

            if consumable.current_stock <= 0:
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
            item["toner_total"] += consumable.current_stock
            item["toner_out"] += int(consumable.current_stock <= 0)
            item["toner_low"] += int(
                consumable.current_stock > 0 and consumable.is_below_minimum_stock
            )
        elif consumable.consumable_type == Consumable.ConsumableType.DRUM:
            item["drum_total"] += consumable.current_stock
            item["drum_out"] += int(consumable.current_stock <= 0)
            item["drum_low"] += int(
                consumable.current_stock > 0 and consumable.is_below_minimum_stock
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
    brand = request.GET.get("brand", "").strip()
    model = request.GET.get("model", "").strip()

    status = request.GET.get("status")
    search = request.GET.get("search")

    devices = (
        PrintingDevice.objects
        .select_related(
            "asset",
            "responsible_user",
            "asset__branch",
            "asset__physical_location",
        )
        .filter(is_active=True)
    )

    if brand:
        devices = devices.filter(asset__brand=brand)

    if model:
        devices = devices.filter(asset__model=model)

    if status:
        devices = devices.filter(asset__connection_status=status)

    if search:
        devices = devices.filter(asset__internal_code__icontains=search)

    # KPIs
    total = devices.count()
    online = devices.filter(asset__connection_status="ONLINE").count()
    offline = devices.filter(asset__connection_status="OFFLINE").count()
    unknown = devices.filter(asset__connection_status="UNKNOWN").count()

    # Alertas
    has_offline = offline > 0
    has_unknown = unknown > 0

    context = {
        "devices": devices,
        "brand": brand,
        "model": model,
        "total": total,
        "online": online,
        "offline": offline,
        "unknown": unknown,
        "has_offline": has_offline,
        "has_unknown": has_unknown,
    }

    return render(
        request,
        "printing/printing_devices_by_model.html",
        context,
    )


# ==========================================================
# DETALLE DE EQUIPO
# ==========================================================
@login_required
@roles_required("ADMIN", "SUPERVISOR", "AUDITOR", "TECHNICIAN")
def printing_device_detail(request, pk):
    device = get_object_or_404(
        PrintingDevice.objects.select_related(
            "asset",
            "responsible_user",
            "asset__assigned_user",
            "asset__branch",
            "asset__location_detail",
        ),
        pk=pk,
    )

    context = {
        "device": device,
    }

    return render(
        request,
        "printing/printing_device_detail.html",
        context,
    )
