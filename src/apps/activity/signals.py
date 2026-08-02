from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from .models import ActivityLog
from .services import get_client_ip


@receiver(user_logged_in)
def register_login(sender, request, user, **kwargs):
    ActivityLog.objects.create(
        user=user,
        action=ActivityLog.ACTION_LOGIN,
        module="Autenticación",
        description=f"El usuario {user.get_username()} inició sesión.",
        object_type="Usuario",
        object_id=user.pk,
        ip_address=get_client_ip(request),
    )


@receiver(user_logged_out)
def register_logout(sender, request, user, **kwargs):
    if user is None:
        return

    ActivityLog.objects.create(
        user=user,
        action=ActivityLog.ACTION_LOGOUT,
        module="Autenticación",
        description=f"El usuario {user.get_username()} cerró sesión.",
        object_type="Usuario",
        object_id=user.pk,
        ip_address=get_client_ip(request),
    )