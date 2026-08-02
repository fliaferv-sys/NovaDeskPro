from django.db import models


class BusinessSequence(models.Model):
    key = models.CharField(max_length=50, primary_key=True)
    value = models.PositiveBigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Secuencia operativa"
        verbose_name_plural = "Secuencias operativas"

    def __str__(self):
        return f"{self.key}: {self.value}"


class Department(models.Model):

    name = models.CharField(
        max_length=100,
        verbose_name="Nombre"
    )

    code = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Código"
    )

    # 🎨 PERSONALIZACIÓN VISUAL
    primary_color = models.CharField(
        max_length=20,
        default="#0a1a3a",
        verbose_name="Color principal"
    )

    secondary_color = models.CharField(
        max_length=20,
        default="#f68b1e",
        verbose_name="Color secundario"
    )

    logo = models.ImageField(
        upload_to="departments/logos/",
        null=True,
        blank=True,
        verbose_name="Logo"
    )

    # ⏱️ SLA (Service Level Agreement)
    sla_hours = models.IntegerField(
        default=24,
        verbose_name="Horas de SLA",
        help_text="Tiempo máximo de respuesta en horas para este departamento."
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Activo"
    )

    order = models.PositiveIntegerField(
        default=0,
        verbose_name="Orden",
        help_text="Los departamentos con un número menor se muestran primero."
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


# ==========================================================
# CATEGORÍAS DINÁMICAS PARA TICKETS
# ==========================================================

class TicketCategory(models.Model):
    """
    Categoría dinámica para tickets, asociada a un departamento.
    
    Permite gestionar las categorías desde el admin sin tocar código.
    Cada departamento puede tener sus propias categorías.
    """
    
    name = models.CharField(
        max_length=100,
        verbose_name="Nombre de la categoría"
    )
    
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="ticket_categories",
        verbose_name="Departamento"
    )
    
    icon = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="Icono",
        help_text="Clase de Bootstrap Icons (ej: bi-printer, bi-laptop, bi-lightning)"
    )
    
    is_active = models.BooleanField(
        default=True,
        verbose_name="Activa"
    )
    
    order = models.PositiveIntegerField(
        default=0,
        verbose_name="Orden"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de creación"
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Última actualización"
    )
    
    class Meta:
        verbose_name = "Categoría de ticket"
        verbose_name_plural = "Categorías de tickets"
        ordering = ["department", "order", "name"]
        unique_together = [["name", "department"]]
    
    def __str__(self):
        return f"{self.department.name} - {self.name}"
