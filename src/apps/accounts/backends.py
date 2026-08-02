from django.contrib.auth.backends import ModelBackend


class ApprovedUserModelBackend(ModelBackend):
    """Reject accounts that are inactive, unapproved, suspended, or expired."""

    def user_can_authenticate(self, user):
        return super().user_can_authenticate(user) and user.can_access_system
