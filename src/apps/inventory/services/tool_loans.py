from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from ..models import Tool, ToolLoan, ToolLoanItem


def _set_tool_status(tool, status, *, updated_at):
    Tool.objects.filter(pk=tool.pk).update(status=status, updated_at=updated_at)


@transaction.atomic
def register_tool_loan(*, loan, already_loaned_tool_ids=()):
    """Register all tools on a loan atomically and mark them as loaned."""
    if not isinstance(loan, ToolLoan) or not loan.pk:
        raise ValidationError({"loan": "El préstamo debe estar guardado."})

    locked_loan = ToolLoan.objects.select_for_update().get(pk=loan.pk)
    if locked_loan.status != ToolLoan.Status.ACTIVE:
        raise ValidationError({"status": "El préstamo debe estar activo."})

    items = list(locked_loan.items.select_for_update().filter(returned_at__isnull=True).order_by("pk"))
    if not items:
        raise ValidationError({"items": "Debe agregar al menos una herramienta."})

    tool_ids = {item.tool_id for item in items}
    tools = list(
        Tool.objects.select_for_update()
        .filter(pk__in=tool_ids)
        .order_by("pk")
    )
    if len(tools) != len(tool_ids):
        raise ValidationError({"items": "Una de las herramientas ya no existe."})

    conflicts = {
        item.tool_id: item.loan
        for item in ToolLoanItem.objects.select_related("loan").filter(
            tool_id__in=tool_ids,
            loan__status=ToolLoan.Status.ACTIVE,
            returned_at__isnull=True,
        ).exclude(loan_id=locked_loan.pk)
    }
    previously_loaned = set(already_loaned_tool_ids)

    for tool in tools:
        if not tool.is_active:
            raise ValidationError(
                {"tool": f"La herramienta {tool.code} está inactiva."}
            )
        conflict = conflicts.get(tool.pk)
        if conflict:
            raise ValidationError(
                {
                    "tool": (
                        f"La herramienta {tool.code} ya pertenece al préstamo "
                        f"activo {conflict.number}."
                    )
                }
            )
        if tool.status != Tool.Status.AVAILABLE and not (
            tool.status == Tool.Status.LOANED and tool.pk in previously_loaned
        ):
            raise ValidationError(
                {"tool": f"La herramienta {tool.code} debe estar disponible."}
            )

    now = timezone.now()
    ToolLoan.objects.filter(pk=locked_loan.pk).update(
        status=ToolLoan.Status.ACTIVE,
        updated_at=now,
    )
    for tool in tools:
        _set_tool_status(tool, Tool.Status.LOANED, updated_at=now)

    locked_loan.refresh_from_db()
    return locked_loan


@transaction.atomic
def register_tool_partial_return(
    *, loan, item_ids, received_by, return_observations="", returned_at=None,
):
    """Return pending items atomically; caller enforces authorization.

    None for item_ids is reserved for the full-return wrapper.
    """
    if not isinstance(loan, ToolLoan) or not loan.pk:
        raise ValidationError({"loan": "El préstamo debe estar guardado."})
    if received_by is None or not getattr(received_by, "pk", None):
        raise ValidationError({"received_by": "Debe indicar quién recibe la devolución."})
    locked_loan = ToolLoan.objects.select_for_update().get(pk=loan.pk)
    if locked_loan.status != ToolLoan.Status.ACTIVE:
        raise ValidationError({"status": "El préstamo ya no está activo."})
    items = list(locked_loan.items.select_for_update().order_by("pk"))
    selected_ids = (
        {str(item.pk) for item in items if item.returned_at is None}
        if item_ids is None else {str(pk) for pk in item_ids}
    )
    if not selected_ids:
        raise ValidationError({"items": "Seleccione al menos una herramienta pendiente."})
    by_id = {str(item.pk): item for item in items}
    if not selected_ids.issubset(by_id):
        raise ValidationError({"items": "Las herramientas deben pertenecer al préstamo."})
    selected = [by_id[pk] for pk in sorted(selected_ids)]
    if any(item.returned_at is not None for item in selected):
        raise ValidationError({"items": "Una herramienta seleccionada ya fue devuelta."})
    tools = list(Tool.objects.select_for_update().filter(
        pk__in=[item.tool_id for item in selected]
    ).order_by("pk"))
    if len(tools) != len(selected) or any(tool.status != Tool.Status.LOANED for tool in tools):
        raise ValidationError({"items": "Las herramientas seleccionadas deben estar prestadas."})
    effective_returned_at = (
        returned_at if isinstance(returned_at, datetime) and timezone.is_aware(returned_at)
        else timezone.now()
    )
    now = timezone.now()
    ToolLoanItem.objects.filter(pk__in=selected_ids).update(
        returned_at=effective_returned_at, received_by=received_by,
        return_observations=return_observations or "",
    )
    for tool in tools:
        _set_tool_status(tool, Tool.Status.AVAILABLE, updated_at=now)
    updates = {"updated_at": now}
    if not any(item.returned_at is None and str(item.pk) not in selected_ids for item in items):
        updates.update(status=ToolLoan.Status.RETURNED, returned_at=effective_returned_at,
                       received_by=received_by, return_observations=return_observations or "")
    ToolLoan.objects.filter(pk=locked_loan.pk).update(**updates)
    locked_loan.refresh_from_db()
    return locked_loan


def register_tool_return(*, loan, received_by, return_observations="", returned_at=None):
    """Return all remaining items, preserving earlier partial returns."""
    return register_tool_partial_return(
        loan=loan, item_ids=None, received_by=received_by,
        return_observations=return_observations, returned_at=returned_at,
    )
