from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts.models import User
from apps.core.models import Department

from ..models import StockBalance, StockMovement


@transaction.atomic
def register_stock_movement(
    *,
    balance,
    quantity,
    direction,
    reason,
    performed_by,
    movement_date=None,
    recipient=None,
    department=None,
    observation="",
    document_reference="",
):
    """Register an immutable movement and update its balance atomically."""
    if not balance.pk:
        raise ValidationError({"balance": "El saldo debe estar guardado."})
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise ValidationError({"quantity": "La cantidad debe ser mayor que cero."})
    if direction not in StockMovement.Direction.values:
        raise ValidationError({"direction": "La dirección no es válida."})

    allowed_reasons = (
        StockMovement.ENTRY_REASONS
        if direction == StockMovement.Direction.ENTRY
        else StockMovement.EXIT_REASONS
    )
    if reason not in allowed_reasons:
        raise ValidationError({"reason": "El motivo no corresponde a la dirección."})
    if not isinstance(performed_by, User) or not performed_by.pk:
        raise ValidationError({"performed_by": "Debe indicar el usuario que registra el movimiento."})
    if recipient is not None and not isinstance(recipient, User):
        raise ValidationError({"recipient": "El destinatario no es válido."})
    if department is not None and not isinstance(department, Department):
        raise ValidationError({"department": "El departamento no es válido."})

    locked_balance = StockBalance.objects.select_for_update().select_related(
        "product"
    ).get(pk=balance.pk)

    if (
        direction == StockMovement.Direction.EXIT
        and quantity > locked_balance.quantity
    ):
        raise ValidationError(
            {"quantity": "La cantidad solicitada supera el stock disponible."}
        )

    if direction == StockMovement.Direction.ENTRY:
        locked_balance.quantity += quantity
    else:
        locked_balance.quantity -= quantity

    movement_data = {
        "product": locked_balance.product,
        "balance": locked_balance,
        "quantity": quantity,
        "direction": direction,
        "reason": reason,
        "performed_by": performed_by,
        "recipient": recipient,
        "department": department,
        "observation": observation,
        "document_reference": document_reference,
    }
    if movement_date is not None:
        movement_data["movement_date"] = movement_date

    movement = StockMovement.objects.create(**movement_data)
    locked_balance.save(update_fields=["quantity", "updated_at"])

    balance.quantity = locked_balance.quantity
    return movement
