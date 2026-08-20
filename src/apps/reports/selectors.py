from datetime import datetime, time, timedelta

from django.db.models import Count, F, IntegerField, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncDay
from django.utils import timezone

from apps.deliveries.models import AssetCustodyMovement
from apps.inventory.models import (
    StockBalance,
    StockDelivery,
    StockDeliveryLine,
    StockEntryLine,
    StockEntryOperation,
    StockMovement as InventoryStockMovement,
    TicketStockUsage,
    TicketStockUsageLine,
)
from apps.printing.models import (
    Consumable,
    PrintingDevice,
    StockMovement as PrintingStockMovement,
)
from apps.tickets.models import Ticket


def _aware_day_start(value):
    if not value:
        return None
    result = datetime.combine(value, time.min)
    return timezone.make_aware(result, timezone.get_current_timezone())


def _datetime_range(queryset, field_name, filters):
    date_from = _aware_day_start(filters.get("date_from"))
    date_to = _aware_day_start(filters.get("date_to"))
    if date_from:
        queryset = queryset.filter(**{f"{field_name}__gte": date_from})
    if date_to:
        queryset = queryset.filter(**{f"{field_name}__lt": date_to + timedelta(days=1)})
    return queryset


def _date_range(queryset, field_name, filters):
    if filters.get("date_from"):
        queryset = queryset.filter(**{f"{field_name}__gte": filters["date_from"]})
    if filters.get("date_to"):
        queryset = queryset.filter(**{f"{field_name}__lte": filters["date_to"]})
    return queryset


def _ticket_dimensions(queryset, filters):
    if filters.get("department"):
        queryset = queryset.filter(department=filters["department"])
    if filters.get("technician"):
        queryset = queryset.filter(assigned_to=filters["technician"])
    if filters.get("status"):
        queryset = queryset.filter(status=filters["status"])
    if filters.get("branch"):
        queryset = queryset.filter(requester__branch=filters["branch"])
    return queryset


def get_ticket_report(filters):
    dimensioned = _ticket_dimensions(Ticket.objects.all(), filters)
    tickets = _datetime_range(dimensioned, "created_at", filters)
    resolved = _datetime_range(
        dimensioned.filter(resolved_at__isnull=False), "resolved_at", filters
    )

    now = timezone.now()
    terminal = [Ticket.Status.RESOLVED, Ticket.Status.CLOSED]
    sla = tickets.aggregate(
        met=Count("id", filter=Q(status__in=terminal, due_date__isnull=False,
                                  resolved_at__isnull=False, resolved_at__lte=F("due_date"))),
        breached=Count("id", filter=Q(status__in=terminal, due_date__isnull=False,
                                       resolved_at__isnull=False, resolved_at__gt=F("due_date"))),
        active_on_time=Count("id", filter=Q(~Q(status__in=terminal), due_date__isnull=False,
                                             due_date__gte=now)),
        active_overdue=Count("id", filter=Q(~Q(status__in=terminal), due_date__isnull=False,
                                             due_date__lt=now)),
        no_data=Count("id", filter=Q(due_date__isnull=True) | Q(status__in=terminal, resolved_at__isnull=True)),
    )
    sla["evaluable_resolved"] = sla["met"] + sla["breached"]

    return {
        "total": tickets.count(),
        "by_status": list(tickets.values("status").annotate(total=Count("id")).order_by("status")),
        "by_priority": list(tickets.values("priority").annotate(total=Count("id")).order_by("priority")),
        "by_department": list(
            tickets.values("department__name").annotate(total=Count("id")).order_by("-total", "department__name")
        ),
        "by_technician": list(
            tickets.values("assigned_to__first_name", "assigned_to__last_name", "assigned_to__username")
            .annotate(total=Count("id")).order_by("-total", "assigned_to__username")
        ),
        "created_by_day": list(
            tickets.annotate(day=TruncDay("created_at")).values("day").annotate(total=Count("id")).order_by("day")
        ),
        "resolved_by_day": list(
            resolved.annotate(day=TruncDay("resolved_at")).values("day").annotate(total=Count("id")).order_by("day")
        ),
        "sla": sla,
    }


def _inventory_activity_dimensions(queryset, filters):
    if filters.get("department"):
        queryset = queryset.filter(department=filters["department"])
    if filters.get("branch"):
        queryset = queryset.filter(balance__branch=filters["branch"])
    return queryset


def get_inventory_report(filters):
    balances = StockBalance.objects.select_related(
        "product", "branch", "organizational_location"
    ).annotate(
        effective_minimum=Coalesce("minimum_stock", "product__minimum_stock"),
    )
    if filters.get("branch"):
        balances = balances.filter(branch=filters["branch"])

    low_balances = balances.filter(quantity__gt=0, effective_minimum__gt=0,
                                   quantity__lte=F("effective_minimum"))
    empty_balances = balances.filter(quantity=0)

    movements = _inventory_activity_dimensions(InventoryStockMovement.objects.select_related(
        "product", "balance__branch", "balance__organizational_location", "department", "ticket"
    ), filters)
    movements = _datetime_range(movements, "movement_date", filters)

    entries = StockEntryLine.objects.filter(entry__status=StockEntryOperation.Status.CONFIRMED)
    entries = _date_range(entries, "entry__entry_date", filters)
    if filters.get("branch"):
        entries = entries.filter(branch=filters["branch"])

    deliveries = StockDelivery.objects.filter(status=StockDelivery.Status.COMPLETED).select_related(
        "department", "branch", "recipient"
    )
    deliveries = _date_range(deliveries, "delivery_date", filters)
    if filters.get("department"):
        deliveries = deliveries.filter(department=filters["department"])
    if filters.get("branch"):
        deliveries = deliveries.filter(branch=filters["branch"])

    delivery_lines = StockDeliveryLine.objects.filter(delivery__in=deliveries)

    usages = TicketStockUsage.objects.filter(status=TicketStockUsage.Status.CONFIRMED).select_related("ticket")
    usages = _datetime_range(usages, "confirmed_at", filters)
    if filters.get("department"):
        usages = usages.filter(ticket__department=filters["department"])
    usage_lines = TicketStockUsageLine.objects.filter(usage__in=usages).select_related(
        "usage__ticket", "product", "source_branch"
    )
    if filters.get("branch"):
        usage_lines = usage_lines.filter(source_branch=filters["branch"])

    custody = AssetCustodyMovement.objects.filter(
        movement_type=AssetCustodyMovement.MovementType.DELIVERY,
        status=AssetCustodyMovement.MovementStatus.DELIVERED,
    ).select_related("asset", "recipient", "destination_branch")
    custody = _datetime_range(custody, "movement_date", filters)
    if filters.get("department"):
        custody = custody.filter(department__iexact=filters["department"].name)
    if filters.get("branch"):
        custody = custody.filter(destination_branch=filters["branch"])

    transfer_movements = movements.filter(reason=InventoryStockMovement.Reason.TRANSFER)
    totals = movements.aggregate(
        entries=Coalesce(Sum("quantity", filter=Q(direction=InventoryStockMovement.Direction.ENTRY)), 0),
        exits=Coalesce(Sum("quantity", filter=Q(direction=InventoryStockMovement.Direction.EXIT)), 0),
        transfer_entries=Coalesce(Sum("quantity", filter=Q(reason=InventoryStockMovement.Reason.TRANSFER,
                                                            direction=InventoryStockMovement.Direction.ENTRY)), 0),
        transfer_exits=Coalesce(Sum("quantity", filter=Q(reason=InventoryStockMovement.Reason.TRANSFER,
                                                          direction=InventoryStockMovement.Direction.EXIT)), 0),
    )

    return {
        "stock_total": balances.aggregate(total=Coalesce(Sum("quantity"), 0))["total"],
        "balance_count": balances.count(),
        "low_count": low_balances.count(),
        "empty_count": empty_balances.count(),
        "balances": balances.order_by("product__name", "branch__name")[:100],
        "low_balances": low_balances.order_by("quantity", "product__name")[:100],
        "movements": movements.order_by("-movement_date")[:100],
        "movement_count": movements.count(),
        "movement_totals": totals,
        "documented_entry_quantity": entries.aggregate(total=Coalesce(Sum("quantity"), 0))["total"],
        "delivery_count": deliveries.count(),
        "delivery_quantity": delivery_lines.aggregate(total=Coalesce(Sum("quantity"), 0))["total"],
        "deliveries": deliveries.order_by("-delivery_date")[:100],
        "usage_count": usages.count(),
        "usage_quantity": usage_lines.aggregate(total=Coalesce(Sum("quantity"), 0))["total"],
        "usage_lines": usage_lines.order_by("-usage__confirmed_at")[:100],
        "transfer_movements": transfer_movements.order_by("-movement_date")[:100],
        "custody_count": custody.count(),
        "custody_deliveries": custody.order_by("-movement_date")[:100],
    }


def get_printing_report(filters):
    devices = PrintingDevice.objects.select_related(
        "asset__branch", "asset__physical_location", "branch",
        "organizational_location",
    )
    if filters.get("branch"):
        devices = devices.filter(
            Q(branch=filters["branch"])
            | Q(branch__isnull=True, asset__branch=filters["branch"])
        )
    if filters.get("active"):
        devices = devices.filter(is_active=filters["active"] == "true")

    device_rows = list(devices.order_by("brand", "model", "serial_number")[:100])
    branch_totals = {}
    for device in device_rows:
        branch = device.effective_branch
        location = device.effective_location
        identifier = (
            f"ID {device.photocopier_id}"
            if device.photocopier_id
            else device.identifier
        )
        brand_model = " ".join(
            value for value in (device.effective_brand, device.effective_model) if value
        )
        device.report_identifier = identifier
        device.report_equipment = " - ".join(
            value for value in (identifier, brand_model) if value
        )
        device.report_brand_model = brand_model or "Sin marca / modelo"
        device.report_branch = branch.name if branch else "Sin sede"
        device.report_location = location.name if location else "Sin ubicación"
        branch_label = str(branch) if branch else "Sin sede"
        branch_totals[branch_label] = branch_totals.get(branch_label, 0) + 1

    positive = [
        PrintingStockMovement.MovementType.ENTRY,
        PrintingStockMovement.MovementType.RETURN,
        PrintingStockMovement.MovementType.POSITIVE_ADJUSTMENT,
    ]
    negative = [
        PrintingStockMovement.MovementType.ISSUE,
        PrintingStockMovement.MovementType.CONSUMPTION,
        PrintingStockMovement.MovementType.NEGATIVE_ADJUSTMENT,
        PrintingStockMovement.MovementType.WRITE_OFF,
    ]
    consumables_queryset = Consumable.objects.select_related("stock_product").prefetch_related(
        "stock_product__balances", "stock_product__stock_movements"
    ).annotate(
        entries_total=Coalesce(Sum("stock_movements__quantity", filter=Q(stock_movements__movement_type__in=positive)), 0),
        outputs_total=Coalesce(Sum("stock_movements__quantity", filter=Q(stock_movements__movement_type__in=negative)), 0),
    ).annotate(current_stock_value=F("initial_stock") + F("entries_total") - F("outputs_total"))
    if filters.get("active"):
        consumables_queryset = consumables_queryset.filter(
            is_active=filters["active"] == "true"
        )

    consumables = list(consumables_queryset.order_by("name"))
    for consumable in consumables:
        if consumable.stock_product_id:
            consumable.current_stock_value = consumable.inventory_stock(
                branch=filters.get("branch")
            )
            inventory_movements = consumable.stock_product.stock_movements.all()
            if filters.get("branch"):
                inventory_movements = inventory_movements.filter(
                    balance__branch=filters["branch"]
                )
            consumable.entries_total = sum(
                movement.quantity for movement in inventory_movements
                if movement.direction == InventoryStockMovement.Direction.ENTRY
            )
            consumable.outputs_total = sum(
                movement.quantity for movement in inventory_movements
                if movement.direction == InventoryStockMovement.Direction.EXIT
            )
        consumable.stock_minimum_value = consumable.effective_minimum_stock
        consumable.stock_source_label = (
            "Inventory" if consumable.stock_product_id else "Printing histórico"
        )

    low_consumables = [
        row for row in consumables
        if 0 < row.current_stock_value <= row.stock_minimum_value
    ]
    empty_consumables = [row for row in consumables if row.current_stock_value <= 0]

    movements = PrintingStockMovement.objects.select_related("consumable", "printing_device__asset")
    movements = _datetime_range(movements, "movement_date", filters)
    if filters.get("active"):
        movements = movements.filter(consumable__is_active=filters["active"] == "true")

    return {
        "device_total": devices.count(),
        "devices": device_rows,
        "devices_by_type": list(devices.values("device_type").annotate(total=Count("id")).order_by("device_type")),
        "devices_by_active": list(devices.values("is_active").annotate(total=Count("id")).order_by("-is_active")),
        "devices_by_branch": [
            {"label": label, "total": total}
            for label, total in sorted(
                branch_totals.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        "consumable_count": len(consumables),
        "consumables": consumables[:100],
        "low_count": len(low_consumables),
        "empty_count": len(empty_consumables),
        "low_consumables": sorted(
            low_consumables, key=lambda row: (row.current_stock_value, row.name)
        )[:100],
        "movement_count": movements.count(),
        "movements": movements.order_by("-movement_date")[:100],
    }
