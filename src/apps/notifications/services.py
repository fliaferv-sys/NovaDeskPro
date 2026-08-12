import json
import logging

from django.conf import settings
from pywebpush import WebPushException, webpush

from .models import Notification, PushSubscription


logger = logging.getLogger(__name__)


def send_web_push_to_user(*, user, title, body, url="/", tag=""):
    """Envía un Web Push a cada dispositivo activo sin propagar errores."""
    result = {
        "sent": 0,
        "failed": 0,
        "deactivated": 0,
    }

    if user is None:
        return result

    subscriptions = PushSubscription.objects.filter(
        user=user,
        is_active=True,
    )

    private_key = getattr(settings, "WEBPUSH_VAPID_PRIVATE_KEY", "")
    public_key = getattr(settings, "WEBPUSH_VAPID_PUBLIC_KEY", "")
    subject = getattr(settings, "WEBPUSH_VAPID_SUBJECT", "")

    if not private_key or not public_key or not subject:
        if subscriptions.exists():
            result["failed"] = subscriptions.count()
            logger.warning(
                "Web Push no enviado: configuración VAPID incompleta."
            )
        return result

    payload = json.dumps(
        {
            "title": title,
            "body": body,
            "url": url or "/",
            "tag": tag or "",
        }
    )

    for subscription in subscriptions.iterator():
        subscription_info = {
            "endpoint": subscription.endpoint,
            "keys": {
                "p256dh": subscription.p256dh,
                "auth": subscription.auth,
            },
        }

        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=private_key,
                vapid_claims={"sub": subject},
            )
            result["sent"] += 1
        except WebPushException as error:
            response = getattr(error, "response", None)
            status_code = getattr(response, "status_code", None)

            if status_code in {404, 410}:
                subscription.is_active = False
                subscription.save(update_fields=["is_active", "updated_at"])
                result["deactivated"] += 1

            result["failed"] += 1
            logger.warning(
                "Falló un envío Web Push (estado HTTP: %s).",
                status_code or "desconocido",
            )
        except Exception as error:
            result["failed"] += 1
            logger.warning(
                "Falló un envío Web Push inesperadamente (%s).",
                type(error).__name__,
            )

    return result


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
