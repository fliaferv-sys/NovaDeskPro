import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Notification(models.Model):
    TYPE_DEVICE_OFFLINE = "DEVICE_OFFLINE"
    TYPE_STOCK_OUT = "STOCK_OUT"
    TYPE_LOW_STOCK = "LOW_STOCK"
    TYPE_CONTRACT_EXPIRING = "CONTRACT_EXPIRING"
    TYPE_TICKET_ASSIGNED = "TICKET_ASSIGNED"
    TYPE_TICKET_COMMENT = "TICKET_COMMENT"
    TYPE_GENERAL = "GENERAL"

    TYPE_CHOICES = [
        (TYPE_DEVICE_OFFLINE, "Equipo fuera de línea"),
        (TYPE_STOCK_OUT, "Consumible sin stock"),
        (TYPE_LOW_STOCK, "Consumible con stock bajo"),
        (TYPE_CONTRACT_EXPIRING, "Contrato próximo a vencer"),
        (TYPE_TICKET_ASSIGNED, "Ticket asignado"),
        (TYPE_TICKET_COMMENT, "Nueva respuesta en ticket"),
        (TYPE_GENERAL, "Notificación general"),
    ]

    LEVEL_INFO = "INFO"
    LEVEL_WARNING = "WARNING"
    LEVEL_DANGER = "DANGER"
    LEVEL_SUCCESS = "SUCCESS"

    LEVEL_CHOICES = [
        (LEVEL_INFO, "Información"),
        (LEVEL_WARNING, "Advertencia"),
        (LEVEL_DANGER, "Crítica"),
        (LEVEL_SUCCESS, "Correcta"),
    ]

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="Destinatario",
        blank=True,
        null=True,
    )

    notification_type = models.CharField(
        "Tipo de notificación",
        max_length=30,
        choices=TYPE_CHOICES,
        default=TYPE_GENERAL,
    )

    level = models.CharField(
        "Nivel",
        max_length=20,
        choices=LEVEL_CHOICES,
        default=LEVEL_INFO,
    )

    title = models.CharField(
        "Título",
        max_length=200,
    )

    message = models.TextField(
        "Mensaje",
    )

    link = models.CharField(
        "Enlace interno",
        max_length=500,
        blank=True,
    )

    object_type = models.CharField(
        "Tipo de objeto",
        max_length=100,
        blank=True,
    )

    object_id = models.CharField(
        "Identificador del objeto",
        max_length=100,
        blank=True,
    )

    unique_key = models.CharField(
        "Clave única",
        max_length=255,
        blank=True,
        db_index=True,
    )

    is_read = models.BooleanField(
        "Leída",
        default=False,
    )

    is_active = models.BooleanField(
        "Activa",
        default=True,
    )

    read_at = models.DateTimeField(
        "Fecha de lectura",
        blank=True,
        null=True,
    )

    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="resolved_notifications",
        verbose_name="Resuelta por",
        blank=True,
        null=True,
    )

    resolved_at = models.DateTimeField(
        "Fecha de resolución",
        blank=True,
        null=True,
    )

    reopened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reopened_notifications",
        verbose_name="Reabierta por",
        blank=True,
        null=True,
    )

    reopened_at = models.DateTimeField(
        "Fecha de reapertura",
        blank=True,
        null=True,
    )

    created_at = models.DateTimeField(
        "Fecha de creación",
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        "Última actualización",
        auto_now=True,
    )

    class Meta:
        verbose_name = "Notificación"
        verbose_name_plural = "Notificaciones"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "is_read", "is_active"]),
            models.Index(fields=["notification_type", "is_active"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["unique_key"],
                condition=~models.Q(unique_key=""),
                name="unique_nonempty_notification_key",
            ),
        ]

    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(
                update_fields=[
                    "is_read",
                    "read_at",
                    "updated_at",
                ]
            )

    def mark_as_unread(self):
        if self.is_read:
            self.is_read = False
            self.read_at = None
            self.save(
                update_fields=[
                    "is_read",
                    "read_at",
                    "updated_at",
                ]
            )

    def resolve(self, user=None):
        self.is_active = False
        self.is_read = True

        if not self.read_at:
            self.read_at = timezone.now()

        self.resolved_by = user
        self.resolved_at = timezone.now()

        self.save(
            update_fields=[
                "is_active",
                "is_read",
                "read_at",
                "resolved_by",
                "resolved_at",
                "updated_at",
            ]
        )

    def reopen(self, user=None):
        self.is_active = True
        self.is_read = False
        self.read_at = None
        self.reopened_by = user
        self.reopened_at = timezone.now()

        self.save(
            update_fields=[
                "is_active",
                "is_read",
                "read_at",
                "reopened_by",
                "reopened_at",
                "updated_at",
            ]
        )

    def __str__(self):
        return self.title
class PushSubscription(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="push_subscriptions",
        verbose_name="Usuario",
    )

    endpoint = models.TextField(
        "Endpoint Push",
        unique=True,
    )

    p256dh = models.TextField(
        "Clave pública p256dh",
    )

    auth = models.TextField(
        "Clave de autenticación",
    )

    user_agent = models.TextField(
        "Navegador / dispositivo",
        blank=True,
    )

    is_active = models.BooleanField(
        "Activa",
        default=True,
    )

    created_at = models.DateTimeField(
        "Fecha de creación",
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        "Última actualización",
        auto_now=True,
    )

    class Meta:
        verbose_name = "Suscripción Push"
        verbose_name_plural = "Suscripciones Push"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.user} - {self.endpoint[:50]}"