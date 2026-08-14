from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts.models import Branch, User
from apps.core.models import Department

from ..models import (
    OrganizationalLocation,
    StockBalance,
    StockMovement,
    StockProduct,
)


def _validate_quantity(quantity):
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise ValidationError({"quantity": "La cantidad debe ser mayor que cero."})


def _validate_location(*, branch, organizational_location):
    if not isinstance(branch, Branch) or not branch.pk:
        raise ValidationError({"branch": "La sede no es válida."})
    if (
        not isinstance(organizational_location, OrganizationalLocation)
        or not organizational_location.pk
    ):
        raise ValidationError(
            {"organizational_location": "La ubicación no es válida."}
        )
    if organizational_location.branch_id != branch.pk:
        raise ValidationError(
            {"organizational_location": "La ubicación no pertenece a la sede."}
        )


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
    product=None,
):
    """Register an immutable movement and update its balance atomically."""
    if not isinstance(balance, StockBalance) or not balance.pk:
        raise ValidationError({"balance": "El saldo debe estar guardado."})
    _validate_quantity(quantity)
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

    if product is not None and (
        not isinstance(product, StockProduct)
        or product.pk != locked_balance.product_id
    ):
        raise ValidationError(
            {"product": "El producto no coincide con el saldo seleccionado."}
        )

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


@transaction.atomic
def register_stock_entry(
    *,
    product,
    branch,
    organizational_location,
    quantity,
    reason,
    performed_by,
    minimum_stock=None,
    **movement_data,
):
    """Create or lock the location balance and register an entry."""
    if not isinstance(product, StockProduct) or not product.pk:
        raise ValidationError({"product": "El producto no es válido."})
    _validate_quantity(quantity)
    _validate_location(
        branch=branch,
        organizational_location=organizational_location,
    )
    if reason not in StockMovement.ENTRY_REASONS:
        raise ValidationError({"reason": "El motivo no corresponde a una entrada."})

    balance, _ = StockBalance.objects.get_or_create(
        product=product,
        branch=branch,
        organizational_location=organizational_location,
        defaults={"minimum_stock": minimum_stock},
    )
    return register_stock_movement(
        balance=balance,
        product=product,
        quantity=quantity,
        direction=StockMovement.Direction.ENTRY,
        reason=reason,
        performed_by=performed_by,
        **movement_data,
    )


@transaction.atomic
def register_stock_exit(
    *,
    product,
    branch,
    organizational_location,
    quantity,
    reason,
    performed_by,
    **movement_data,
):
    """Lock an existing location balance and register an exit."""
    if not isinstance(product, StockProduct) or not product.pk:
        raise ValidationError({"product": "El producto no es válido."})
    _validate_quantity(quantity)
    _validate_location(
        branch=branch,
        organizational_location=organizational_location,
    )
    if reason not in StockMovement.EXIT_REASONS:
        raise ValidationError({"reason": "El motivo no corresponde a una salida."})

    try:
        balance = StockBalance.objects.get(
            product=product,
            branch=branch,
            organizational_location=organizational_location,
        )
    except StockBalance.DoesNotExist as error:
        raise ValidationError(
            {"balance": "No existe saldo para el producto en la ubicación de origen."}
        ) from error

    return register_stock_movement(
        balance=balance,
        product=product,
        quantity=quantity,
        direction=StockMovement.Direction.EXIT,
        reason=reason,
        performed_by=performed_by,
        **movement_data,
    )


@transaction.atomic
def transfer_stock(
    *,
    product,
    source_branch,
    source_location,
    destination_branch,
    destination_location,
    quantity,
    performed_by,
    movement_date=None,
    observation="",
    document_reference="",
):
    """Transfer stock atomically, locking both balances in UUID order."""
    if not isinstance(product, StockProduct) or not product.pk:
        raise ValidationError({"product": "El producto no es válido."})
    _validate_quantity(quantity)
    _validate_location(
        branch=source_branch,
        organizational_location=source_location,
    )
    _validate_location(
        branch=destination_branch,
        organizational_location=destination_location,
    )
    if not isinstance(performed_by, User) or not performed_by.pk:
        raise ValidationError(
            {"performed_by": "Debe indicar el usuario que registra el movimiento."}
        )
    if (
        source_branch.pk == destination_branch.pk
        and source_location.pk == destination_location.pk
    ):
        raise ValidationError(
            {"destination_location": "La ubicación de destino debe ser diferente al origen."}
        )

    try:
        source_balance = StockBalance.objects.get(
            product=product,
            branch=source_branch,
            organizational_location=source_location,
        )
    except StockBalance.DoesNotExist as error:
        raise ValidationError(
            {"source_location": "No existe saldo en la ubicación de origen."}
        ) from error

    destination_balance, _ = StockBalance.objects.get_or_create(
        product=product,
        branch=destination_branch,
        organizational_location=destination_location,
    )

    locked_balances = {
        balance.pk: balance
        for balance in StockBalance.objects.select_for_update()
        .select_related("product")
        .filter(pk__in=[source_balance.pk, destination_balance.pk])
        .order_by("pk")
    }
    source_balance = locked_balances[source_balance.pk]
    destination_balance = locked_balances[destination_balance.pk]

    if quantity > source_balance.quantity:
        raise ValidationError(
            {"quantity": "La cantidad solicitada supera el stock disponible."}
        )

    source_balance.quantity -= quantity
    destination_balance.quantity += quantity

    common_data = {
        "product": product,
        "quantity": quantity,
        "reason": StockMovement.Reason.TRANSFER,
        "performed_by": performed_by,
        "observation": observation,
        "document_reference": document_reference,
    }
    if movement_date is not None:
        common_data["movement_date"] = movement_date

    exit_movement = StockMovement.objects.create(
        balance=source_balance,
        direction=StockMovement.Direction.EXIT,
        **common_data,
    )
    entry_movement = StockMovement.objects.create(
        balance=destination_balance,
        direction=StockMovement.Direction.ENTRY,
        **common_data,
    )
    source_balance.save(update_fields=["quantity", "updated_at"])
    destination_balance.save(update_fields=["quantity", "updated_at"])

    return exit_movement, entry_movement
