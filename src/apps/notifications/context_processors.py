from django.conf import settings
from .selectors import notifications_for_user


def notification_context(request):
    if not request.user.is_authenticated:
        return {
            "navbar_unread_notifications": 0,
            "webpush_vapid_public_key": getattr(
                settings,
                "WEBPUSH_VAPID_PUBLIC_KEY",
                "",
            ),
        }

    unread_count = notifications_for_user(request.user).filter(
        is_active=True,
        is_read=False,
    ).count()

    return {
        "navbar_unread_notifications": unread_count,
        "webpush_vapid_public_key": getattr(
            settings,
            "WEBPUSH_VAPID_PUBLIC_KEY",
            "",
        ),
    }
