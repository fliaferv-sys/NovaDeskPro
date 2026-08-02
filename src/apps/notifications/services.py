from .models import Notification


def create_or_update_notification(
    *,
    recipient=None,
    notification_type=Notification.TYPE_GENERAL,
    level=Notification.LEVEL_INFO,
    title,
    message,
    link="",
    object_type="",
    object_id="",
    unique_key="",
):
    """
    Crea una notificación o actualiza la existente cuando se utiliza
    una clave única.

    Esto evita generar la misma alerta repetidas veces.
    """

    defaults = {
        "recipient": recipient,
        "notification_type": notification_type,
        "level": level,
        "title": title,
        "message": message,
        "link": link,
        "object_type": object_type,
        "object_id": str(object_id) if object_id else "",
        "is_active": True,
    }

    if unique_key:
        notification, created = Notification.objects.update_or_create(
            unique_key=unique_key,
            defaults=defaults,
        )

        if not created and notification.is_read:
            notification.is_read = False
            notification.read_at = None
            notification.save(
                update_fields=[
                    "is_read",
                    "read_at",
                    "updated_at",
                ]
            )

        return notification, created

    notification = Notification.objects.create(
        unique_key="",
        **defaults,
    )

    return notification, True


def deactivate_notification(unique_key):
    """
    Desactiva una alerta cuando el problema relacionado ya fue resuelto.
    """

    if not unique_key:
        return 0

    return Notification.objects.filter(
        unique_key=unique_key,
        is_active=True,
    ).update(
        is_active=False,
    )


def deactivate_notifications_by_prefix(prefix):
    """
    Desactiva notificaciones activas cuya clave comienza con un prefijo.
    """

    if not prefix:
        return 0

    return Notification.objects.filter(
        unique_key__startswith=prefix,
        is_active=True,
    ).update(
        is_active=False,
    )