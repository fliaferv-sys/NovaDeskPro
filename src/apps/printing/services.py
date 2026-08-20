from django.core.exceptions import ValidationError
from django.db import transaction

from apps.inventory.models import (
    StockBalance,
    TicketStockUsage,
    TicketStockUsageLine,
)
from apps.inventory.services.stock import confirm_ticket_stock_usage
from apps.tickets.models import Ticket

from .models import (
    ConsumableCompatibility,
    PrintingDevice,
    PrintingTicketStockUsageContext,
    PrintingTicketStockUsageLineContext,
)


@transaction.atomic
def register_printing_ticket_stock_usage(
    *,
    ticket,
    printing_device,
    compatibility,
    stock_balance,
    quantity,
    observation,
    registered_by,
):
    """Create and confirm the official Inventory usage with Printing snapshots."""
    locked_ticket = (
        Ticket.objects.select_for_update()
        .select_related("printing_device")
        .get(pk=ticket.pk)
    )
    if not locked_ticket.printing_device_id:
        raise ValidationError("El ticket no tiene un equipo de impresión relacionado.")

    locked_device = (
        PrintingDevice.objects.select_for_update()
        .select_related(
            "asset__branch", "asset__physical_location", "branch",
            "organizational_location",
        )
        .get(pk=printing_device.pk)
    )
    if locked_device.pk != locked_ticket.printing_device_id or not locked_device.is_active:
        raise ValidationError("El ticket no corresponde a un equipo de impresión activo.")

    locked_compatibility = (
        ConsumableCompatibility.objects.select_for_update()
        .select_related("consumable__stock_product")
        .get(pk=compatibility.pk)
    )
    consumable = locked_compatibility.consumable
    if (
        locked_compatibility.printing_device_id != locked_device.pk
        or not locked_compatibility.is_active
        or not consumable.is_active
    ):
        raise ValidationError("El consumible no es compatible con esta impresora.")
    if not consumable.stock_product_id or not consumable.stock_product.is_active:
        raise ValidationError("El consumible no tiene un producto de stock activo vinculado.")

    balance = (
        StockBalance.objects.select_related("branch", "organizational_location")
        .get(pk=stock_balance.pk)
    )
    if balance.product_id != consumable.stock_product_id:
        raise ValidationError("El balance seleccionado no corresponde al consumible.")
    if balance.organizational_location.branch_id != balance.branch_id:
        raise ValidationError("La ubicación no pertenece a la sede de origen.")
    if not balance.branch.is_active or not balance.organizational_location.is_active:
        raise ValidationError("La sede y la ubicación del stock deben estar activas.")
    if quantity <= 0:
        raise ValidationError("La cantidad debe ser mayor que cero.")

    usage = TicketStockUsage.objects.create(
        ticket=locked_ticket,
        observation=observation,
        registered_by=registered_by,
    )
    usage_line = TicketStockUsageLine.objects.create(
        usage=usage,
        product=consumable.stock_product,
        source_branch=balance.branch,
        source_location=balance.organizational_location,
        quantity=quantity,
    )
    usage = confirm_ticket_stock_usage(
        usage=usage,
        confirmed_by=registered_by,
    )

    branch = locked_device.effective_branch
    location = locked_device.effective_location
    PrintingTicketStockUsageContext.objects.create(
        usage=usage,
        printing_device=locked_device,
        device_id_snapshot=str(locked_device.pk),
        device_identifier_snapshot=locked_device.identifier,
        device_brand_snapshot=locked_device.effective_brand,
        device_model_snapshot=locked_device.effective_model,
        device_serial_snapshot=locked_device.effective_serial_number,
        branch_snapshot=str(branch or ""),
        location_snapshot=location.full_path if location else "",
        created_by=registered_by,
    )
    PrintingTicketStockUsageLineContext.objects.create(
        usage_line=usage_line,
        consumable=consumable,
        reference_snapshot=consumable.reference_code,
        type_snapshot=consumable.get_consumable_type_display(),
        manufacturer_snapshot=consumable.manufacturer or "",
        model_snapshot=consumable.model or "",
        color_snapshot=consumable.color or "",
    )
    return usage
