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

    items = list(locked_loan.items.order_by("created_at"))
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
def register_tool_return(
    *,
    loan,
    received_by,
    return_observations="",
    returned_at=None,
):
    """Return every tool on an active loan as one atomic operation."""
    if not isinstance(loan, ToolLoan) or not loan.pk:
        raise ValidationError({"loan": "El préstamo debe estar guardado."})
    if received_by is None or not getattr(received_by, "pk", None):
        raise ValidationError({"received_by": "Debe indicar quién recibe la devolución."})

    locked_loan = ToolLoan.objects.select_for_update().get(pk=loan.pk)
    if locked_loan.status != ToolLoan.Status.ACTIVE:
        raise ValidationError({"status": "El préstamo ya no está activo."})

    tool_ids = list(locked_loan.items.values_list("tool_id", flat=True))
    if not tool_ids:
        raise ValidationError({"items": "El préstamo no contiene herramientas."})
    tools = list(
        Tool.objects.select_for_update()
        .filter(pk__in=tool_ids)
        .order_by("pk")
    )

    effective_returned_at = (
        returned_at
        if isinstance(returned_at, datetime) and timezone.is_aware(returned_at)
        else timezone.now()
    )
    now = timezone.now()

    ToolLoan.objects.filter(pk=locked_loan.pk).update(
        status=ToolLoan.Status.RETURNED,
        returned_at=effective_returned_at,
        received_by=received_by,
        return_observations=return_observations or "",
        updated_at=now,
    )
    # El destino de estado queda centralizado aquí para admitir reparación futura.
    for tool in tools:
        _set_tool_status(tool, Tool.Status.AVAILABLE, updated_at=now)

    locked_loan.refresh_from_db()
    return locked_loan
