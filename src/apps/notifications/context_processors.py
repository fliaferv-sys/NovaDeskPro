from django.conf import settings
from django.db.models import Q

from .models import Notification


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

    unread_count = Notification.objects.filter(
        Q(recipient=request.user) | Q(recipient__isnull=True),
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