from django.conf import settings
from django.db import models


class ActivityLog(models.Model):
    ACTION_CREATE = "create"
    ACTION_UPDATE = "update"
    ACTION_DELETE = "delete"
    ACTION_ASSIGN = "assign"
    ACTION_STATUS = "status"
    ACTION_COMMENT = "comment"
    ACTION_LOGIN = "login"
    ACTION_LOGOUT = "logout"
    ACTION_OTHER = "other"

    ACTION_CHOICES = [
        (ACTION_CREATE, "Creación"),
        (ACTION_UPDATE, "Actualización"),
        (ACTION_DELETE, "Eliminación"),
        (ACTION_ASSIGN, "Asignación"),
        (ACTION_STATUS, "Cambio de estado"),
        (ACTION_COMMENT, "Comentario"),
        (ACTION_LOGIN, "Inicio de sesión"),
        (ACTION_LOGOUT, "Cierre de sesión"),
        (ACTION_OTHER, "Otra acción"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_logs",
        verbose_name="Usuario",
    )

    action = models.CharField(
        max_length=30,
        choices=ACTION_CHOICES,
        default=ACTION_OTHER,
        verbose_name="Acción",
    )

    module = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Módulo",
    )

    description = models.TextField(
        verbose_name="Descripción",
    )

    object_type = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Tipo de objeto",
    )

    object_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="ID del objeto",
    )

    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name="Dirección IP",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha y hora",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Registro de actividad"
        verbose_name_plural = "Registros de actividad"

    def __str__(self):
        username = self.user.get_username() if self.user else "Sistema"
        return (
            f"{username} - "
            f"{self.get_action_display()} - "
            f"{self.created_at:%d/%m/%Y %H:%M}"
        )