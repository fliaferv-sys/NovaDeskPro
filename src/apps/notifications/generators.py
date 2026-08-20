from datetime import timedelta

from django.utils import timezone

from apps.monitoring.models import DeviceHeartbeat
from apps.printing.models import Consumable, PrintingContract
from apps.tickets.models import Ticket

from .models import Notification
from .services import (
    create_or_update_notification,
    deactivate_notification,
)


def generate_device_offline_notifications():
    """
    Genera o actualiza alertas para equipos fuera de línea
    y desactiva la alerta cuando el equipo vuelve a conectarse.
    """

    created_count = 0
    updated_count = 0
    deactivated_count = 0

    devices = DeviceHeartbeat.objects.select_related("asset").all()

    for device in devices:
        unique_key = f"device-offline-{device.pk}"

        if device.is_online:
            deactivated_count += deactivate_notification(unique_key)
            continue

        asset_code = (
            device.asset.internal_code
            if device.asset
            else "Sin código"
        )

        notification, created = create_or_update_notification(
            notification_type=Notification.TYPE_DEVICE_OFFLINE,
            level=Notification.LEVEL_DANGER,
            title=f"Equipo fuera de línea: {device.computer_name}",
            message=(
                f"El equipo {device.computer_name}, correspondiente al "
                f"activo {asset_code}, no está enviando información al "
                "servidor de monitoreo."
            ),
            link=f"/monitoring/equipo/{device.pk}/",
            object_type="DeviceHeartbeat",
            object_id=device.pk,
            unique_key=unique_key,
        )

        if created:
            created_count += 1
        else:
            updated_count += 1

    return {
        "created": created_count,
        "updated": updated_count,
        "deactivated": deactivated_count,
    }


def generate_consumable_stock_notifications():
    """
    Genera alertas para consumibles sin stock o con stock bajo.

    Cuando el stock vuelve a un nivel normal, desactiva
    automáticamente las alertas relacionadas.
    """

    created_count = 0
    updated_count = 0
    deactivated_count = 0

    consumables = Consumable.objects.filter(is_active=True)

    for consumable in consumables:
        no_stock_key = f"consumable-out-of-stock-{consumable.pk}"
        low_stock_key = f"consumable-low-stock-{consumable.pk}"

        if consumable.stock_product_id:
            deactivated_count += deactivate_notification(no_stock_key)
            deactivated_count += deactivate_notification(low_stock_key)
            continue

        current_stock = consumable.current_stock

        if current_stock <= 0:
            deactivated_count += deactivate_notification(low_stock_key)

            notification, created = create_or_update_notification(
                notification_type=Notification.TYPE_STOCK_OUT,
                level=Notification.LEVEL_DANGER,
                title=f"Consumible sin stock: {consumable.name}",
                message=(
                    f"El consumible {consumable.name}, con código de "
                    f"referencia {consumable.reference_code}, se encuentra "
                    "sin existencias."
                ),
                link="/admin/printing/consumable/",
                object_type="Consumable",
                object_id=consumable.pk,
                unique_key=no_stock_key,
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

            continue

        deactivated_count += deactivate_notification(no_stock_key)

        if current_stock <= consumable.minimum_stock:
            notification, created = create_or_update_notification(
                notification_type=Notification.TYPE_LOW_STOCK,
                level=Notification.LEVEL_WARNING,
                title=f"Stock bajo: {consumable.name}",
                message=(
                    f"El consumible {consumable.name}, con código de "
                    f"referencia {consumable.reference_code}, tiene un "
                    f"stock actual de {current_stock}. El mínimo configurado "
                    f"es {consumable.minimum_stock}."
                ),
                link="/admin/printing/consumable/",
                object_type="Consumable",
                object_id=consumable.pk,
                unique_key=low_stock_key,
            )

            if created:
                created_count += 1
            else:
                updated_count += 1
        else:
            deactivated_count += deactivate_notification(low_stock_key)

    return {
        "created": created_count,
        "updated": updated_count,
        "deactivated": deactivated_count,
    }


def generate_printing_contract_notifications():
    """
    Genera alertas para contratos de impresión próximos a vencer
    o que ya se encuentran vencidos.

    Reglas:
    - Contrato vencido: alerta crítica.
    - Vence dentro de 7 días: alerta crítica.
    - Vence dentro de 15 días: advertencia.
    - Vence dentro de 30 días: advertencia.
    - Más de 30 días: se desactiva cualquier alerta previa.
    - Contratos cancelados, suspendidos, inactivos o en borrador:
      se desactiva cualquier alerta previa.
    """

    created_count = 0
    updated_count = 0
    deactivated_count = 0

    today = timezone.localdate()
    alert_limit_date = today + timedelta(days=30)

    contracts = PrintingContract.objects.all()

    for contract in contracts:
        unique_key = f"printing-contract-expiring-{contract.pk}"

        contract_is_valid = (
            contract.is_active
            and contract.status == PrintingContract.Status.ACTIVE
        )

        if not contract_is_valid:
            deactivated_count += deactivate_notification(unique_key)
            continue

        days_remaining = (contract.end_date - today).days

        if contract.end_date > alert_limit_date:
            deactivated_count += deactivate_notification(unique_key)
            continue

        if days_remaining < 0:
            overdue_days = abs(days_remaining)

            title = f"Contrato vencido: {contract.contract_number}"
            level = Notification.LEVEL_DANGER
            message = (
                f"El contrato {contract.contract_number}, correspondiente "
                f"al proveedor {contract.provider}, venció el "
                f"{contract.end_date.strftime('%d/%m/%Y')}."
            )

            if overdue_days == 1:
                message += " El contrato tiene 1 día de vencimiento."
            else:
                message += (
                    f" El contrato tiene {overdue_days} días de vencimiento."
                )

        elif days_remaining == 0:
            title = f"Contrato vence hoy: {contract.contract_number}"
            level = Notification.LEVEL_DANGER
            message = (
                f"El contrato {contract.contract_number}, correspondiente "
                f"al proveedor {contract.provider}, vence hoy "
                f"{contract.end_date.strftime('%d/%m/%Y')}."
            )

        elif days_remaining <= 7:
            title = (
                f"Contrato próximo a vencer: "
                f"{contract.contract_number}"
            )
            level = Notification.LEVEL_DANGER
            message = (
                f"El contrato {contract.contract_number}, correspondiente "
                f"al proveedor {contract.provider}, vence dentro de "
                f"{days_remaining} días, el "
                f"{contract.end_date.strftime('%d/%m/%Y')}."
            )

        elif days_remaining <= 15:
            title = (
                f"Contrato próximo a vencer: "
                f"{contract.contract_number}"
            )
            level = Notification.LEVEL_WARNING
            message = (
                f"El contrato {contract.contract_number}, correspondiente "
                f"al proveedor {contract.provider}, vence dentro de "
                f"{days_remaining} días, el "
                f"{contract.end_date.strftime('%d/%m/%Y')}."
            )

        else:
            title = (
                f"Contrato próximo a vencer: "
                f"{contract.contract_number}"
            )
            level = Notification.LEVEL_WARNING
            message = (
                f"El contrato {contract.contract_number}, correspondiente "
                f"al proveedor {contract.provider}, vence dentro de "
                f"{days_remaining} días, el "
                f"{contract.end_date.strftime('%d/%m/%Y')}."
            )

        notification, created = create_or_update_notification(
            notification_type=Notification.TYPE_CONTRACT_EXPIRING,
            level=level,
            title=title,
            message=message,
            link="/admin/printing/printingcontract/",
            object_type="PrintingContract",
            object_id=contract.pk,
            unique_key=unique_key,
        )

        if created:
            created_count += 1
        else:
            updated_count += 1

    return {
        "created": created_count,
        "updated": updated_count,
        "deactivated": deactivated_count,
    }


def generate_ticket_sla_notifications():
    now = timezone.now()
    warning_limit = now + timedelta(hours=4)
    active_tickets = Ticket.objects.exclude(
        status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED]
    ).filter(due_date__isnull=False).select_related("assigned_to", "requester")

    created_count = updated_count = deactivated_count = 0
    active_ids = set()
    for ticket in active_tickets:
        key = f"ticket-sla-{ticket.pk}"
        active_ids.add(str(ticket.pk))
        if ticket.due_date > warning_limit:
            deactivated_count += deactivate_notification(key)
            new_status = "OK"
        elif ticket.due_date > now:
            new_status = "WARNING"
            level = Notification.LEVEL_WARNING
            title = f"Ticket por vencer: {ticket.ticket_number}"
        else:
            new_status = "EXPIRED"
            level = Notification.LEVEL_DANGER
            title = f"Ticket vencido: {ticket.ticket_number}"

        if ticket.sla_status != new_status:
            Ticket.objects.filter(pk=ticket.pk).update(sla_status=new_status)

        if new_status in {"WARNING", "EXPIRED"}:
            notification, created = create_or_update_notification(
                recipient=ticket.assigned_to or ticket.requester,
                level=level,
                title=title,
                message=f"Fecha límite: {timezone.localtime(ticket.due_date):%d/%m/%Y %H:%M}.",
                link=f"/tickets/{ticket.pk}/",
                object_type="Ticket",
                object_id=ticket.pk,
                unique_key=key,
            )
            created_count += int(created)
            updated_count += int(not created)

    stale = Notification.objects.filter(
        unique_key__startswith="ticket-sla-",
        is_active=True,
    ).exclude(object_id__in=active_ids)
    deactivated_count += stale.update(is_active=False)
    return {"created": created_count, "updated": updated_count, "deactivated": deactivated_count}
