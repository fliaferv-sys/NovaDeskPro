from django.db.models import Q

from apps.accounts.models import User

from .models import Notification


EXECUTIVE_NOTIFICATION_ROLES = frozenset(
    {User.Role.ADMIN, User.Role.SUPERVISOR}
)


def can_view_executive_notifications(user):
    return bool(
        user.is_authenticated
        and (
            user.is_superuser
            or getattr(user, "role", None) in EXECUTIVE_NOTIFICATION_ROLES
        )
    )


def notifications_for_user(user):
    """Limit notifications according to the authenticated user's role."""
    if can_view_executive_notifications(user):
        return Notification.objects.filter(
            Q(recipient=user) | Q(recipient__isnull=True)
        )

    return Notification.objects.filter(recipient=user)
