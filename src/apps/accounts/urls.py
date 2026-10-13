from django.contrib.auth.views import LogoutView
from django.urls import path
from .institutional_sync_views import sync_user_institutional_data

from .views import (
    CustomLoginView,
    home_view,
    profile_view,
    user_list_view,
)

urlpatterns = [
    path("usuarios/<uuid:pk>/sincronizar/", sync_user_institutional_data, name="sync_user_institutional_data"),
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
