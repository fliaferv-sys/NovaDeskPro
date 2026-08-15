from django.urls import reverse

from apps.notifications.models import Notification
from apps.notifications.services import (
    create_or_update_notification,
    deactivate_notification,
)

from ..models import StockBalance


LOW_STOCK_KEY_PREFIX = "inventory-stock-low-"
STOCK_OUT_KEY_PREFIX = "inventory-stock-out-"


def generate_inventory_stock_notifications():
    """Create mutually exclusive stock alerts for each physical balance."""
    result = {"created": 0, "updated": 0, "deactivated": 0}
    balances = StockBalance.objects.select_related(
        "product", "branch", "organizational_location"
    )

    for balance in balances.iterator():
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
            continue

        common = {
            "link": reverse("inventory:stock_product_detail", args=[balance.product_id]),
            "object_type": "StockBalance",
            "object_id": balance.pk,
        }
        if balance.quantity == 0:
            result["deactivated"] += deactivate_notification(low_key)
            _, created = create_or_update_notification(
                notification_type=Notification.TYPE_STOCK_OUT,
                level=Notification.LEVEL_DANGER,
                title=f"Sin stock: {balance.product.name}",
                message=f"Sin stock: {balance.product.name} en {location_name} ({balance.branch.name}).",
                unique_key=out_key,
                **common,
            )
        elif (
            balance.effective_minimum_stock > 0
            and balance.quantity <= balance.effective_minimum_stock
        ):
            result["deactivated"] += deactivate_notification(out_key)
            _, created = create_or_update_notification(
                notification_type=Notification.TYPE_LOW_STOCK,
                level=Notification.LEVEL_WARNING,
                title=f"Stock bajo: {balance.product.name}",
                message=(
                    f"Stock bajo: {balance.product.name} — {balance.quantity} "
                    f"unidades disponibles en {location_name} ({balance.branch.name})."
                ),
                unique_key=low_key,
                **common,
            )
        else:
            result["deactivated"] += deactivate_notification(low_key)
            result["deactivated"] += deactivate_notification(out_key)
            continue

        result["created" if created else "updated"] += 1

    return result
