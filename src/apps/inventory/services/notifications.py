from django.urls import reverse

from apps.notifications.models import Notification
from apps.notifications.services import (
    create_or_update_notification,
    deactivate_notification,
)

from ..models import StockBalance


LOW_STOCK_KEY_PREFIX = "inventory-stock-low-"
STOCK_OUT_KEY_PREFIX = "inventory-stock-out-"


def sync_inventory_stock_notification(balance_id):
    """Synchronize stock alerts for one physical balance."""
    result = {"created": 0, "updated": 0, "deactivated": 0}

    try:
        balance = StockBalance.objects.select_related(
            "product",
            "branch",
            "organizational_location",
        ).get(pk=balance_id)
    except StockBalance.DoesNotExist:
        return result

    low_key = f"{LOW_STOCK_KEY_PREFIX}{balance.pk}"
    out_key = f"{STOCK_OUT_KEY_PREFIX}{balance.pk}"
    location_name = balance.organizational_location.full_path

    active = (
        balance.product.is_active
        and balance.branch.is_active
        and balance.organizational_location.is_active
    )

    if not active:
        result["deactivated"] += deactivate_notification(low_key)
        result["deactivated"] += deactivate_notification(out_key)
        return result

    common = {
        "link": reverse(
            "inventory:stock_product_detail",
            args=[balance.product_id],
        ),
        "object_type": "StockBalance",
        "object_id": balance.pk,
    }

    if balance.quantity == 0:
        result["deactivated"] += deactivate_notification(low_key)

        _, created = create_or_update_notification(
            notification_type=Notification.TYPE_STOCK_OUT,
            level=Notification.LEVEL_DANGER,
            title=f"Sin stock: {balance.product.name}",
            message=(
                f"Sin stock: {balance.product.name} "
                f"en {location_name} ({balance.branch.name})."
            ),
            unique_key=out_key,
            **common,
        )

        result["created" if created else "updated"] += 1
        return result

    if (
        balance.effective_minimum_stock > 0
        and balance.quantity <= balance.effective_minimum_stock
    ):
        result["deactivated"] += deactivate_notification(out_key)

        _, created = create_or_update_notification(
            notification_type=Notification.TYPE_LOW_STOCK,
            level=Notification.LEVEL_WARNING,
            title=f"Stock bajo: {balance.product.name}",
            message=(
                f"Stock bajo: {balance.product.name} — "
                f"{balance.quantity} unidades disponibles "
                f"en {location_name} ({balance.branch.name})."
            ),
            unique_key=low_key,
            **common,
        )

        result["created" if created else "updated"] += 1
        return result

    result["deactivated"] += deactivate_notification(low_key)
    result["deactivated"] += deactivate_notification(out_key)

    return result


def generate_inventory_stock_notifications():
    """Reconcile stock alerts for all physical balances."""
    result = {"created": 0, "updated": 0, "deactivated": 0}

    balance_ids = StockBalance.objects.values_list("pk", flat=True)

    for balance_id in balance_ids.iterator():
        balance_result = sync_inventory_stock_notification(balance_id)

        for key in result:
            result[key] += balance_result[key]

    return result
