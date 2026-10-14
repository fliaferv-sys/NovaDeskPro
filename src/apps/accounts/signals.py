from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .institutional_sync import try_sync_user_institutional_data


@receiver(user_logged_in, dispatch_uid="accounts.institutional_sync_after_login")
def sync_authenticated_user(sender, request, user, **kwargs):
    try_sync_user_institutional_data(user, actor=user)
