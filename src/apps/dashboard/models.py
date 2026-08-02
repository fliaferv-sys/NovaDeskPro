# ==========================================================
# MODELOS DEL DASHBOARD
# NOVADESK PRO
# SPRINT 18
# ==========================================================

from django.conf import settings
from django.db import models


# ==========================================================
# PREFERENCIAS DEL DASHBOARD POR USUARIO
# ==========================================================

class DashboardPreference(models.Model):
    """
    Guarda la distribución personalizada del dashboard
    y los tipos de gráficos seleccionados por cada usuario.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="dashboard_preference",
        verbose_name="Usuario",
    )

    layout = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Distribución de widgets",
        help_text=(
            "Posición y tamaño de los paneles "
            "del dashboard."
        ),
    )

    chart_types = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Tipos de gráficos",
        help_text=(
            "Tipo de gráfico seleccionado "
            "para cada panel."
        ),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de creación",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Última actualización",
    )

    class Meta:
        verbose_name = "Preferencia del dashboard"
        verbose_name_plural = "Preferencias del dashboard"
        ordering = [
            "-updated_at",
        ]

    def __str__(self):
        return (
            f"Dashboard de {self.user}"
        )