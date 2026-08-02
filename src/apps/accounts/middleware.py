from django.conf import settings
from django.contrib.auth import logout
from django.contrib.auth import get_user_model
from django.contrib.auth import SESSION_KEY
from django.shortcuts import redirect


class AccountAccessMiddleware:
    """End existing sessions as soon as an account loses access."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and not user.is_authenticated and request.session.get(SESSION_KEY):
            session_user = (
                get_user_model().objects.filter(pk=request.session[SESSION_KEY]).first()
            )
            if session_user is None or not session_user.can_access_system:
                logout(request)
                return redirect(settings.LOGIN_URL)
        if user and user.is_authenticated and not user.can_access_system:
            logout(request)
            return redirect(settings.LOGIN_URL)
        return self.get_response(request)
