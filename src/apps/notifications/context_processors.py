from django.db.models import Q

from .models import Notification


def notification_context(request):
    if not request.user.is_authenticated:
        return {
            "navbar_unread_notifications": 0,
        }

    unread_count = Notification.objects.filter(
        Q(recipient=request.user) | Q(recipient__isnull=True),
        is_active=True,
        is_read=False,
    ).count()

    return {
        "navbar_unread_notifications": unread_count,
    }