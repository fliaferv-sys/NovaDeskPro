from django.contrib.auth.views import LogoutView
from django.urls import path

from .views import (
    CustomLoginView,
    home_view,
    profile_view,
    user_list_view,
)

urlpatterns = [
    path("", home_view, name="home"),

    path(
        "accounts/profile/",
        profile_view,
        name="profile",
    ),

    path(
        "login/",
        CustomLoginView.as_view(),
        name="login",
    ),

    path(
        "logout/",
        LogoutView.as_view(
            next_page="/login/"
        ),
        name="logout",
    ),

    # =====================================
    # GESTIÓN DE USUARIOS
    # =====================================

    path(
        "usuarios/",
        user_list_view,
        name="user_list",
    ),
]
