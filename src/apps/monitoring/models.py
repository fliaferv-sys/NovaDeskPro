import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class DeviceHeartbeat(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    asset = models.OneToOneField(
        "inventory.Asset",
        on_delete=models.CASCADE,
        related_name="device_heartbeat",
        verbose_name="Activo",
    )

    computer_name = models.CharField(
        "Nombre del equipo",
        max_length=150,
    )

    logged_user = models.CharField(
        "Usuario conectado",
        max_length=150,
        blank=True,
    )

    ip_address = models.GenericIPAddressField(
        "Dirección IP actual",
        blank=True,
        null=True,
    )

    mac_address = models.CharField(
        "Dirección MAC",
        max_length=50,
        blank=True,
    )

    operating_system = models.CharField(
        "Sistema operativo",
        max_length=200,
        blank=True,
    )

    processor = models.CharField(
        "Procesador",
        max_length=250,
        blank=True,
    )

    ram_total_gb = models.DecimalField(
        "Memoria RAM total (GB)",
        max_digits=8,
        decimal_places=2,
        blank=True,
        null=True,
    )

    disk_total_gb = models.DecimalField(
        "Disco total (GB)",
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
    )

    disk_free_gb = models.DecimalField(
        "Disco disponible (GB)",
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
    )

    agent_version = models.CharField(
        "Versión del agente",
        max_length=50,
        blank=True,
    )

    last_seen = models.DateTimeField(
        "Última comunicación",
        default=timezone.now,
    )

    first_seen = models.DateTimeField(
        "Primera comunicación",
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        "Última actualización",
        auto_now=True,
    )

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="updated_device_heartbeats",
        verbose_name="Actualizado por",
        blank=True,
        null=True,
    )

    notes = models.TextField(
        "Observaciones",
        blank=True,
    )

    class Meta:
        verbose_name = "Estado de equipo"
        verbose_name_plural = "Estados de equipos"
        ordering = ["computer_name"]

    @property
    def is_online(self):
        if not self.last_seen:
            return False

        threshold = timezone.now() - timedelta(minutes=3)
        return self.last_seen >= threshold

    @property
    def status_label(self):
        return "En línea" if self.is_online else "Fuera de línea"

    def __str__(self):
        return f"{self.computer_name} - {self.ip_address or 'Sin IP'}"
    
class DeviceIPHistory(models.Model):
    device = models.ForeignKey(
        DeviceHeartbeat,
        on_delete=models.CASCADE,
        related_name="ip_history",
        verbose_name="Equipo monitoreado",
    )

    ip_address = models.GenericIPAddressField(
        "Dirección IP",
    )

    computer_name = models.CharField(
        "Nombre del equipo",
        max_length=150,
    )

    logged_user = models.CharField(
        "Usuario conectado",
        max_length=150,
        blank=True,
    )

    mac_address = models.CharField(
        "Dirección MAC",
        max_length=50,
        blank=True,
    )

    first_seen = models.DateTimeField(
        "Primera detección",
        default=timezone.now,
    )

    last_seen = models.DateTimeField(
        "Última detección",
        default=timezone.now,
    )

    detection_count = models.PositiveIntegerField(
        "Cantidad de detecciones",
        default=1,
    )

    class Meta:
        verbose_name = "Historial de IP"
        verbose_name_plural = "Historial de IP"
        ordering = ["-last_seen"]
        indexes = [
            models.Index(fields=["ip_address"]),
            models.Index(fields=["-last_seen"]),
        ]

    def __str__(self):
        return f"{self.ip_address} - {self.computer_name}"    