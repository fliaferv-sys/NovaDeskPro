import re

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.inventory.models import StockBalance, StockProduct
from apps.inventory.models import StockMovement as InventoryStockMovement
from apps.inventory.services.stock import register_stock_entry

from .models import (
    Consumable,
    ConsumableStockMigrationBatch,
    ConsumableStockMigrationItem,
    StockMovement,
)


def normalize_reference_code(value):
    """Normalize only for comparison; stored references remain untouched."""
    return re.sub(r"[\s\-_./]+", "", (value or "").strip().upper())


def _movement_snapshots(consumable):
    positive = {
        StockMovement.MovementType.ENTRY,
        StockMovement.MovementType.RETURN,
        StockMovement.MovementType.POSITIVE_ADJUSTMENT,
    }
    negative = {
        StockMovement.MovementType.ISSUE,
        StockMovement.MovementType.CONSUMPTION,
        StockMovement.MovementType.NEGATIVE_ADJUSTMENT,
        StockMovement.MovementType.WRITE_OFF,
    }
    rows = consumable.stock_movements.values("movement_type").annotate(
        total=Coalesce(Sum("quantity"), 0)
    )
    totals = {row["movement_type"]: row["total"] for row in rows}
    entries = sum(totals.get(kind, 0) for kind in positive)
    outputs = sum(totals.get(kind, 0) for kind in negative)
    transfers = totals.get(StockMovement.MovementType.TRANSFER, 0)
    return entries, outputs, transfers, consumable.initial_stock + entries - outputs


def _resolve_candidate(consumable, products_by_code):
    if consumable.stock_product_id:
        return consumable.stock_product, ConsumableStockMigrationItem.MatchStatus.LINKED
    candidates = products_by_code.get(normalize_reference_code(consumable.reference_code), [])
    if len(candidates) == 1:
        return candidates[0], ConsumableStockMigrationItem.MatchStatus.EXACT_CODE_MATCH
    if len(candidates) > 1:
        return None, ConsumableStockMigrationItem.MatchStatus.AMBIGUOUS_CODE
    return None, ConsumableStockMigrationItem.MatchStatus.NO_MATCH


@transaction.atomic
def generate_consumable_stock_migration_batch(*, batch):
    """Create or refresh snapshots without changing products, balances or movements."""
    locked_batch = ConsumableStockMigrationBatch.objects.select_for_update().get(pk=batch.pk)
    if locked_batch.status in {
        ConsumableStockMigrationBatch.Status.COMPLETED,
        ConsumableStockMigrationBatch.Status.CANCELLED,
    }:
        raise ValidationError("Un lote completado o cancelado no puede recalcularse.")

    products_by_code = {}
    for product in StockProduct.objects.all().order_by("pk"):
        products_by_code.setdefault(normalize_reference_code(product.reference_code), []).append(product)
    balances = {
        row["product_id"]: (row["total"], row["count"] > 0)
        for row in StockBalance.objects.values("product_id").annotate(
            total=Coalesce(Sum("quantity"), 0), count=Count("id")
        )
    }

    for consumable in Consumable.objects.select_related("stock_product").order_by("pk"):
        candidate, match_status = _resolve_candidate(consumable, products_by_code)
        existing_item = locked_batch.items.filter(consumable=consumable).first()
        if (
            candidate is None
            and existing_item
            and existing_item.decision_status
            == ConsumableStockMigrationItem.DecisionStatus.LINK_EXISTING_PRODUCT
            and existing_item.stock_product_candidate_id
        ):
            candidate = existing_item.stock_product_candidate
        entries, outputs, transfers, current = _movement_snapshots(consumable)
        inventory_total = None
        has_balance = False
        product_active = None
        difference = None
        if candidate:
            inventory_total, has_balance = balances.get(candidate.pk, (0, False))
            product_active = candidate.is_active
            difference = current - inventory_total

        if current < 0:
            quantity_status = ConsumableStockMigrationItem.QuantityStatus.NEGATIVE_PRINTING_STOCK
        elif candidate is None:
            quantity_status = ConsumableStockMigrationItem.QuantityStatus.NO_PRODUCT
        elif not has_balance:
            quantity_status = ConsumableStockMigrationItem.QuantityStatus.NO_BALANCE
        elif difference == 0:
            quantity_status = ConsumableStockMigrationItem.QuantityStatus.MATCH
        elif difference > 0:
            quantity_status = ConsumableStockMigrationItem.QuantityStatus.PRINTING_GREATER
        else:
            quantity_status = ConsumableStockMigrationItem.QuantityStatus.INVENTORY_GREATER

        ConsumableStockMigrationItem.objects.update_or_create(
            batch=locked_batch,
            consumable=consumable,
            defaults={
                "stock_product_candidate": candidate,
                "printing_reference_snapshot": consumable.reference_code,
                "printing_name_snapshot": consumable.name,
                "printing_active_snapshot": consumable.is_active,
                "printing_initial_stock_snapshot": consumable.initial_stock,
                "printing_entries_snapshot": entries,
                "printing_outputs_snapshot": outputs,
                "printing_transfers_snapshot": transfers,
                "printing_current_stock_snapshot": current,
                "inventory_total_stock_snapshot": inventory_total,
                "inventory_has_balance_snapshot": has_balance,
                "stock_product_active_snapshot": product_active,
                "match_status": match_status,
                "quantity_status": quantity_status,
                "difference": difference,
            },
        )

    items = locked_batch.items.all()
    total = items.count()
    pending = items.filter(
        decision_status=ConsumableStockMigrationItem.DecisionStatus.PENDING
    ).count()
    errors = items.filter(
        quantity_status=ConsumableStockMigrationItem.QuantityStatus.NEGATIVE_PRINTING_STOCK
    ).count()
    ConsumableStockMigrationBatch.objects.filter(pk=locked_batch.pk).update(
        status=ConsumableStockMigrationBatch.Status.IN_REVIEW,
        total_items=total,
        pending_items=pending,
        reviewed_items=total - pending,
        error_items=errors,
    )
    locked_batch.refresh_from_db()
    return locked_batch


def complete_consumable_stock_migration_batch(*, batch):
    if batch.status not in {
        ConsumableStockMigrationBatch.Status.DRAFT,
        ConsumableStockMigrationBatch.Status.IN_REVIEW,
    }:
        raise ValidationError("Solo puede completarse un lote abierto.")
    now = timezone.now()
    ConsumableStockMigrationBatch.objects.filter(pk=batch.pk).update(
        status=ConsumableStockMigrationBatch.Status.COMPLETED,
        completed_at=now,
    )
    batch.refresh_from_db()
    return batch


def _validate_item_for_consolidation(item):
    allowed_batch_statuses = {
        ConsumableStockMigrationBatch.Status.IN_REVIEW,
        ConsumableStockMigrationBatch.Status.COMPLETED,
    }
    if item.batch.status not in allowed_batch_statuses:
        raise ValidationError({"batch": "El lote debe estar en revisión o completado."})
    if item.inventory_stock_movement_id:
        raise ValidationError("El ítem ya fue consolidado anteriormente.")
    if item.decision_status != ConsumableStockMigrationItem.DecisionStatus.USE_PRINTING:
        raise ValidationError({"decision_status": "El ítem debe estar aprobado para usar Printing."})
    if not item.stock_product_candidate_id:
        raise ValidationError({"stock_product_candidate": "Debe seleccionar un producto de stock."})
    if not item.stock_product_candidate.is_active:
        raise ValidationError({"stock_product_candidate": "El producto de stock debe estar activo."})
    if not item.consumable.is_active:
        raise ValidationError({"consumable": "El consumible debe estar activo para consolidarlo."})
    if not isinstance(item.approved_quantity, int) or item.approved_quantity <= 0:
        raise ValidationError({"approved_quantity": "La cantidad aprobada debe ser mayor que cero."})
    if not item.destination_branch_id:
        raise ValidationError({"destination_branch": "Debe seleccionar una sede de destino."})
    if not item.destination_location_id:
        raise ValidationError({"destination_location": "Debe seleccionar una ubicación de destino."})
    if item.destination_location.branch_id != item.destination_branch_id:
        raise ValidationError({"destination_location": "La ubicación no pertenece a la sede seleccionada."})
    if (
        item.consumable.stock_product_id
        and item.consumable.stock_product_id != item.stock_product_candidate_id
    ):
        raise ValidationError(
            {"stock_product_candidate": "El candidato no coincide con el producto ya vinculado."}
        )


@transaction.atomic
def consolidate_consumable_stock_items(*, items, performed_by):
    """Consolidate an explicitly approved selection as one atomic operation."""
    item_ids = sorted({item.pk for item in items}, key=str)
    if not item_ids:
        raise ValidationError("Debe seleccionar al menos un ítem.")

    locked_items = list(
        ConsumableStockMigrationItem.objects.select_for_update()
        .select_related(
            "batch", "consumable__stock_product", "stock_product_candidate",
            "destination_branch", "destination_location",
        )
        .filter(pk__in=item_ids)
        .order_by("pk")
    )
    if len(locked_items) != len(item_ids):
        raise ValidationError("Uno o más ítems seleccionados ya no existen.")

    batch_ids = sorted({item.batch_id for item in locked_items}, key=str)
    locked_batches = {
        batch.pk: batch
        for batch in ConsumableStockMigrationBatch.objects.select_for_update()
        .filter(pk__in=batch_ids)
        .order_by("pk")
    }
    for item in locked_items:
        item.batch = locked_batches[item.batch_id]
        _validate_item_for_consolidation(item)

    movements = []
    now = timezone.now()
    for item in locked_items:
        consumable = Consumable.objects.select_for_update().get(pk=item.consumable_id)
        product = item.stock_product_candidate
        if consumable.stock_product_id and consumable.stock_product_id != product.pk:
            raise ValidationError("El vínculo del consumible cambió durante la consolidación.")
        if not consumable.stock_product_id:
            consumable.stock_product = product
            consumable.save(update_fields=["stock_product", "updated_at"])

        movement = register_stock_entry(
            product=product,
            branch=item.destination_branch,
            organizational_location=item.destination_location,
            quantity=item.approved_quantity,
            reason=InventoryStockMovement.Reason.INITIAL_ENTRY,
            performed_by=performed_by,
            observation=(
                "Consolidación controlada desde Printing. "
                f"Consumible: {item.consumable_id}; lote: {item.batch_id}; ítem: {item.pk}."
            ),
            document_reference=f"PRINT-CONSOL:{item.batch_id}:{item.pk}",
        )
        updated = ConsumableStockMigrationItem.objects.filter(
            pk=item.pk, inventory_stock_movement__isnull=True
        ).update(
            inventory_stock_movement=movement,
            consolidated_quantity=item.approved_quantity,
            consolidated_by=performed_by,
            consolidated_at=now,
            updated_at=now,
        )
        if updated != 1:
            raise ValidationError("El ítem ya fue consolidado por otra operación.")
        movements.append(movement)
    return movements
