from django.urls import path

from .views import (
    notification_list,
    notification_mark_all_read,
    notification_mark_read,
    notification_reopen,
    notification_resolve,
    push_subscribe,
)


app_name = "notifications"


urlpatterns = [
    path(
        "",
        notification_list,
        name="notification_list",
    ),
    path(
        "leer-todas/",
        notification_mark_all_read,
        name="notification_mark_all_read",
    ),
    path(
        "<uuid:pk>/leer/",
        notification_mark_read,
        name="notification_mark_read",
    ),
    path(
        "<uuid:pk>/resolver/",
        notification_resolve,
        name="notification_resolve",
    ),
    path(
        "<uuid:pk>/reabrir/",
        notification_reopen,
        name="notification_reopen",
    ),
    path(
        "push/suscribir/",
        push_subscribe,
        name="push_subscribe",
    ),
]
