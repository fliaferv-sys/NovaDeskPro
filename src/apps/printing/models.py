import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone


class PrintingDevice(models.Model):
    class DeviceType(models.TextChoices):
        PRINTER = "PRINTER", "Impresora"
        MULTIFUNCTION = "MULTIFUNCTION", "Multifuncional"
        PHOTOCOPIER = "PHOTOCOPIER", "Fotocopiadora"
        SCANNER = "SCANNER", "Escáner"
        

    class Technology(models.TextChoices):
        LASER = "LASER", "Láser"
        INKJET = "INKJET", "Inyección de tinta"
        THERMAL = "THERMAL", "Térmica"
        OTHER = "OTHER", "Otra"

    class ColorMode(models.TextChoices):
        MONOCHROME = "MONOCHROME", "Monocromática"
        COLOR = "COLOR", "Color"

    class OwnershipType(models.TextChoices):
        OWNED = "OWNED", "Propio"
        RENTED = "RENTED", "Alquilado"
        LOANED = "LOANED", "En préstamo"
        LEASING = "LEASING", "Leasing"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    asset = models.OneToOneField(
        "inventory.Asset",
        on_delete=models.SET_NULL,
        related_name="printing_device",
        verbose_name="Activo patrimonial (opcional)",
        blank=True,
        null=True,
        help_text="Solo para equipos institucionales históricos; no crear activos para equipos tercerizados.",
    )

    branch = models.ForeignKey(
        "accounts.Branch", on_delete=models.PROTECT, related_name="printing_devices",
        verbose_name="Sede", blank=True, null=True,
    )
    organizational_location = models.ForeignKey(
        "inventory.OrganizationalLocation", on_delete=models.PROTECT,
        related_name="printing_devices", verbose_name="Ubicación", blank=True, null=True,
    )
    brand = models.CharField("Marca", max_length=100, blank=True)
    model = models.CharField("Modelo", max_length=100, blank=True)
    serial_number = models.CharField("Número de serie", max_length=150, blank=True)
    photocopier_id = models.CharField(
        "ID de fotocopiadora",
        max_length=50,
        unique=True,
        blank=True,
        null=True,
        help_text="Identificador operativo asignado al equipo tercerizado.",
    )
    is_outsourced = models.BooleanField("Equipo tercerizado", default=True)

    device_type = models.CharField(
        "Tipo de equipo",
        max_length=20,
        choices=DeviceType.choices,
        default=DeviceType.PRINTER,
    )

    technology = models.CharField(
        "Tecnología",
        max_length=20,
        choices=Technology.choices,
        default=Technology.LASER,
    )

    color_mode = models.CharField(
        "Modo de impresión",
        max_length=20,
        choices=ColorMode.choices,
        default=ColorMode.MONOCHROME,
    )

    ownership_type = models.CharField(
        "Modalidad de propiedad",
        max_length=20,
        choices=OwnershipType.choices,
        default=OwnershipType.OWNED,
    )

    supports_duplex = models.BooleanField(
        "Impresión doble faz",
        default=False,
    )

    supports_network = models.BooleanField(
        "Conectado a red",
        default=True,
    )

    supports_scan = models.BooleanField(
        "Permite escanear",
        default=False,
    )

    supports_copy = models.BooleanField(
        "Permite copiar",
        default=False,
    )

    supports_fax = models.BooleanField(
        "Permite fax",
        default=False,
    )

    web_interface_url = models.URLField(
        "Dirección de administración web",
        blank=True,
    )

    network_port = models.PositiveIntegerField(
        "Puerto de red",
        default=9100,
        validators=[MinValueValidator(1)],
    )

    snmp_enabled = models.BooleanField(
        "SNMP habilitado",
        default=False,
    )

    snmp_community = models.CharField(
        "Comunidad SNMP",
        max_length=100,
        blank=True,
    )

    monthly_print_limit = models.PositiveIntegerField(
        "Límite mensual de impresiones",
        blank=True,
        null=True,
    )

    notes = models.TextField(
        "Observaciones",
        blank=True,
    )

    responsible_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="responsible_printing_devices",
        verbose_name="Responsable del equipo",
        blank=True,
        null=True,
    )

    is_active = models.BooleanField(
        "Activo",
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
        verbose_name = "Equipo de impresión"
        verbose_name_plural = "Equipos de impresión"
        ordering = ["brand", "model", "serial_number"]

    @property
    def effective_branch(self):
        return self.branch or (self.asset.branch if self.asset_id else None)

    @property
    def effective_location(self):
        return self.organizational_location or (
            self.asset.physical_location if self.asset_id else None
        )

    @property
    def effective_brand(self):
        return self.brand or (self.asset.brand if self.asset_id else "")

    @property
    def effective_model(self):
        return self.model or (self.asset.model if self.asset_id else "")

    @property
    def effective_serial_number(self):
        return self.serial_number or (self.asset.serial_number if self.asset_id else "")

    @property
    def identifier(self):
        if self.photocopier_id:
            return self.photocopier_id
        if self.asset_id:
            return self.asset.internal_code
        return self.serial_number or "Sin ID operativo"

    def clean(self):
        super().clean()
        if self.organizational_location_id and self.branch_id:
            if self.organizational_location.branch_id != self.branch_id:
                raise ValidationError(
                    {"organizational_location": "La ubicación no pertenece a la sede indicada."}
                )
        if self.is_outsourced and not self.asset_id:
            required = {
                "branch": self.branch_id,
                "organizational_location": self.organizational_location_id,
                "brand": self.brand,
                "model": self.model,
                "serial_number": self.serial_number,
            }
            for field, value in required.items():
                if not value:
                    raise ValidationError(
                        {field: "Este dato es obligatorio para un equipo tercerizado."}
                    )

    def __str__(self):
        description = " ".join(
            value for value in (self.effective_brand, self.effective_model) if value
        )
        return f"{self.identifier} - {description or self.get_device_type_display()}"

    
class PrintingDeviceNetworkDetection(models.Model):
    """
    Guarda el historial de ubicaciones detectadas
    para una impresora, multifuncional o fotocopiadora.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    printing_device = models.ForeignKey(
        PrintingDevice,
        on_delete=models.CASCADE,
        related_name="network_detections",
        verbose_name="Equipo de impresión",
    )

    detected_ip = models.GenericIPAddressField(
        "Dirección IP detectada",
        protocol="both",
        unpack_ipv4=True,
        blank=True,
        null=True,
    )

    detected_mac = models.CharField(
        "Dirección MAC detectada",
        max_length=17,
        blank=True,
    )

    switch_name = models.CharField(
        "Switch detectado",
        max_length=150,
        blank=True,
    )

    switch_port = models.CharField(
        "Puerto del switch",
        max_length=50,
        blank=True,
    )

    vlan = models.CharField(
        "VLAN",
        max_length=50,
        blank=True,
    )

    detected_location = models.CharField(
        "Ubicación detectada",
        max_length=255,
        blank=True,
        help_text=(
            "Ubicación física asociada al switch y puerto "
            "donde fue detectado el equipo."
        ),
    )

    detection_source = models.CharField(
        "Origen de la detección",
        max_length=100,
        blank=True,
        help_text=(
            "Ejemplo: SNMP, tabla MAC del switch, "
            "servidor DHCP o detección manual."
        ),
    )

    is_current = models.BooleanField(
        "Detección actual",
        default=True,
    )

    detected_at = models.DateTimeField(
        "Fecha y hora de detección",
        auto_now_add=True,
    )

    notes = models.TextField(
        "Observaciones",
        blank=True,
    )

    class Meta:
        verbose_name = "Detección de red de equipo de impresión"
        verbose_name_plural = "Detecciones de red de equipos de impresión"
        ordering = ["-detected_at"]

    def __str__(self):
        return (
            f"{self.printing_device.identifier} - "
            f"{self.detected_ip or 'Sin IP'} - "
            f"{self.detected_at:%d/%m/%Y %H:%M}"
        )
    

class Consumable(models.Model):
    """Modelo para consumibles (tóner, tinta, etc.)"""
    
    class ConsumableType(models.TextChoices):
        TONER = "TONER", "Tóner"
        INK = "INK", "Tinta"
        DRUM = "DRUM", "Unidad de imagen"
        FUSER = "FUSER", "Unidad de fusión"
        WASTE_TONER = "WASTE_TONER", "Tóner residual"
        OTHER = "OTHER", "Otro"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    name = models.CharField(
        "Nombre del consumible",
        max_length=200,
    )

    consumable_type = models.CharField(
        "Tipo de consumible",
        max_length=20,
        choices=ConsumableType.choices,
        default=ConsumableType.TONER,
    )

    reference_code = models.CharField(
        "Código de referencia",
        max_length=100,
        unique=True,
    )

    stock_product = models.OneToOneField(
        "inventory.StockProduct",
        on_delete=models.PROTECT,
        related_name="printing_consumable",
        verbose_name="Producto de stock",
        blank=True,
        null=True,
    )

    manufacturer = models.CharField(
        "Fabricante",
        max_length=150,
    )

    model = models.CharField(
        "Modelo",
        max_length=150,
        blank=True,
    )

    color = models.CharField(
        "Color",
        max_length=50,
        blank=True,
        help_text="Ej: Negro, Cian, Magenta, Amarillo",
    )

    estimated_yield_pages = models.PositiveIntegerField(
        "Rendimiento estimado (páginas)",
        blank=True,
        null=True,
        help_text="Número de páginas estimadas que imprime este consumible.",
    )

    unit_price = models.DecimalField(
        "Precio unitario",
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    initial_stock = models.PositiveIntegerField(
        "Stock inicial",
        default=0,
    )

    minimum_stock = models.PositiveIntegerField(
        "Stock mínimo",
        default=5,
    )

    maximum_stock = models.PositiveIntegerField(
        "Stock máximo",
        blank=True,
        null=True,
        help_text="Opcional. Si se define, alerta cuando se supera.",
    )

    notes = models.TextField(
        "Observaciones",
        blank=True,
    )

    is_active = models.BooleanField(
        "Activo",
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
        verbose_name = "Consumible"
        verbose_name_plural = "Consumibles"
        ordering = ["name"]

    def clean(self):
        super().clean()

        if (
            not self.stock_product_id
            and self.maximum_stock is not None
            and self.maximum_stock < self.minimum_stock
        ):
            raise ValidationError(
                {
                    "maximum_stock": (
                        "El stock máximo no puede ser menor "
                        "que el stock mínimo."
                    )
                }
            )

        if (
            not self.stock_product_id
            and self.maximum_stock is not None
            and self.initial_stock > self.maximum_stock
        ):
            raise ValidationError(
                {
                    "initial_stock": (
                        "El stock inicial no puede superar "
                        "el stock máximo configurado."
                    )
                }
            )

    @property
    def total_entries(self):
        positive_types = [
            StockMovement.MovementType.ENTRY,
            StockMovement.MovementType.RETURN,
            StockMovement.MovementType.POSITIVE_ADJUSTMENT,
        ]

        return (
            self.stock_movements.filter(
                movement_type__in=positive_types
            ).aggregate(
                total=Coalesce(Sum("quantity"), 0)
            )["total"]
        )

    @property
    def total_outputs(self):
        negative_types = [
            StockMovement.MovementType.ISSUE,
            StockMovement.MovementType.CONSUMPTION,
            StockMovement.MovementType.NEGATIVE_ADJUSTMENT,
            StockMovement.MovementType.WRITE_OFF,
        ]

        return (
            self.stock_movements.filter(
                movement_type__in=negative_types
            ).aggregate(
                total=Coalesce(Sum("quantity"), 0)
            )["total"]
        )

    @property
    def current_stock(self):
        """Legacy Printing balance retained for reconciliation and audit only."""
        return self.initial_stock + self.total_entries - self.total_outputs

    def inventory_stock(self, *, branch=None):
        if not self.stock_product_id:
            return None
        balances = self.stock_product.balances.all()
        if branch is not None:
            balances = balances.filter(branch=branch)
        return sum(balance.quantity for balance in balances)

    @property
    def operational_stock(self):
        if self.stock_product_id:
            return self.inventory_stock()
        return self.current_stock

    @property
    def stock_source(self):
        return "INVENTORY" if self.stock_product_id else "PRINTING_LEGACY"

    @property
    def effective_minimum_stock(self):
        if self.stock_product_id:
            return self.stock_product.minimum_stock
        return self.minimum_stock

    @property
    def effective_maximum_stock(self):
        """Legacy maximum only applies while Printing remains the stock source."""
        if self.stock_product_id:
            return None
        return self.maximum_stock

    @property
    def is_below_minimum_stock(self):
        return self.operational_stock <= self.effective_minimum_stock

    @property
    def is_above_maximum_stock(self):
        return (
            self.effective_maximum_stock is not None
            and self.operational_stock > self.effective_maximum_stock
        )

    @property
    def quantity_to_minimum(self):
        return max(
            self.effective_minimum_stock - self.operational_stock,
            0,
        )

    @property
    def suggested_reorder_quantity(self):
        if self.effective_maximum_stock is not None:
            return max(
                self.effective_maximum_stock - self.operational_stock,
                0,
            )

        return self.quantity_to_minimum

    @property
    def estimated_reorder_cost(self):
        return (
            self.suggested_reorder_quantity
            * self.unit_price
        )

    def __str__(self):
        reference = self.model or self.reference_code
        return f"{self.name} - {reference}"


class ConsumableCompatibility(models.Model):
    """Modelo para gestionar compatibilidad entre consumibles y equipos de impresión"""
    
    class CompatibilityType(models.TextChoices):
        ORIGINAL = "ORIGINAL", "Original"
        COMPATIBLE = "COMPATIBLE", "Compatible"
        ALTERNATIVE = "ALTERNATIVE", "Alternativo"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    printing_device = models.ForeignKey(
        PrintingDevice,
        on_delete=models.CASCADE,
        related_name="consumable_compatibilities",
        verbose_name="Equipo de impresión",
    )

    consumable = models.ForeignKey(
        Consumable,
        on_delete=models.CASCADE,
        related_name="device_compatibilities",
        verbose_name="Consumible",
    )

    compatibility_type = models.CharField(
        "Tipo de compatibilidad",
        max_length=20,
        choices=CompatibilityType.choices,
        default=CompatibilityType.ORIGINAL,
    )

    is_primary = models.BooleanField(
        "Consumible principal",
        default=False,
        help_text="Indica si es el consumible recomendado para este equipo.",
    )

    notes = models.TextField(
        "Observaciones",
        blank=True,
    )

    is_active = models.BooleanField(
        "Activo",
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
        verbose_name = "Compatibilidad de consumible"
        verbose_name_plural = "Compatibilidades de consumibles"
        ordering = [
            "printing_device",
            "consumable",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "printing_device",
                    "consumable",
                ],
                name="unique_printing_device_consumable",
            )
        ]

    def __str__(self):
        return f"{self.printing_device} → {self.consumable}"


class PrintingTicketStockUsageContext(models.Model):
    """Immutable printing context for an Inventory ticket stock usage."""

    usage = models.OneToOneField(
        "inventory.TicketStockUsage",
        on_delete=models.PROTECT,
        related_name="printing_context",
        verbose_name="Consumo de stock",
    )
    printing_device = models.ForeignKey(
        PrintingDevice,
        on_delete=models.PROTECT,
        related_name="ticket_stock_usage_contexts",
        verbose_name="Equipo de impresión",
    )
    device_id_snapshot = models.CharField("ID histórico del equipo", max_length=36)
    device_identifier_snapshot = models.CharField(
        "Identificador histórico", max_length=150
    )
    device_brand_snapshot = models.CharField("Marca histórica", max_length=100, blank=True)
    device_model_snapshot = models.CharField("Modelo histórico", max_length=100, blank=True)
    device_serial_snapshot = models.CharField("Serie histórica", max_length=150, blank=True)
    branch_snapshot = models.CharField("Sede histórica", max_length=150, blank=True)
    location_snapshot = models.CharField("Ubicación histórica", max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_printing_ticket_stock_contexts",
        verbose_name="Registrado por",
    )

    class Meta:
        verbose_name = "Contexto Printing de consumo por ticket"
        verbose_name_plural = "Contextos Printing de consumos por ticket"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.usage} - {self.device_identifier_snapshot}"


class PrintingTicketStockUsageLineContext(models.Model):
    """Technical consumable snapshots for one Inventory usage line."""

    usage_line = models.OneToOneField(
        "inventory.TicketStockUsageLine",
        on_delete=models.PROTECT,
        related_name="printing_context",
        verbose_name="Línea de consumo",
    )
    consumable = models.ForeignKey(
        Consumable,
        on_delete=models.PROTECT,
        related_name="ticket_stock_usage_line_contexts",
        verbose_name="Consumible",
    )
    reference_snapshot = models.CharField("Referencia histórica", max_length=100)
    type_snapshot = models.CharField("Tipo histórico", max_length=50)
    manufacturer_snapshot = models.CharField("Fabricante histórico", max_length=150, blank=True)
    model_snapshot = models.CharField("Modelo histórico", max_length=150, blank=True)
    color_snapshot = models.CharField("Color histórico", max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Contexto Printing de línea de consumo"
        verbose_name_plural = "Contextos Printing de líneas de consumo"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.usage_line} - {self.reference_snapshot}"


class StockMovement(models.Model):
    """Modelo para registrar movimientos de stock de consumibles"""
    
    class MovementType(models.TextChoices):
        ENTRY = "ENTRY", "Entrada"
        ISSUE = "ISSUE", "Salida"
        CONSUMPTION = "CONSUMPTION", "Consumo en equipo"
        RETURN = "RETURN", "Devolución"
        POSITIVE_ADJUSTMENT = "POSITIVE_ADJUSTMENT", "Ajuste positivo"
        NEGATIVE_ADJUSTMENT = "NEGATIVE_ADJUSTMENT", "Ajuste negativo"
        TRANSFER = "TRANSFER", "Transferencia"
        WRITE_OFF = "WRITE_OFF", "Baja"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    consumable = models.ForeignKey(
        Consumable,
        on_delete=models.PROTECT,
        related_name="stock_movements",
        verbose_name="Consumible",
    )

    movement_type = models.CharField(
        "Tipo de movimiento",
        max_length=30,
        choices=MovementType.choices,
    )

    quantity = models.PositiveIntegerField(
        "Cantidad",
        validators=[MinValueValidator(1)],
    )

    printing_device = models.ForeignKey(
        PrintingDevice,
        on_delete=models.PROTECT,
        related_name="consumable_movements",
        verbose_name="Equipo de impresión",
        blank=True,
        null=True,
        help_text="Completar cuando el consumible se instale o utilice en un equipo.",
    )

    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="printing_stock_movements",
        verbose_name="Registrado por",
    )

    movement_date = models.DateTimeField(
        "Fecha del movimiento",
        default=timezone.now,
    )

    unit_cost = models.DecimalField(
        "Costo unitario",
        max_digits=14,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(0)],
    )

    source_location = models.CharField(
        "Ubicación de origen",
        max_length=150,
        blank=True,
    )

    destination_location = models.CharField(
        "Ubicación de destino",
        max_length=150,
        blank=True,
    )

    document_reference = models.CharField(
        "Documento de referencia",
        max_length=100,
        blank=True,
        help_text="Factura, remisión, orden de trabajo u otro comprobante.",
    )

    notes = models.TextField(
        "Observaciones",
        blank=True,
    )

    created_at = models.DateTimeField(
        "Fecha de registro",
        auto_now_add=True,
    )

    def clean(self):
        super().clean()

        negative_types = [
            self.MovementType.ISSUE,
            self.MovementType.CONSUMPTION,
            self.MovementType.NEGATIVE_ADJUSTMENT,
            self.MovementType.WRITE_OFF,
        ]

        positive_types = [
            self.MovementType.ENTRY,
            self.MovementType.RETURN,
            self.MovementType.POSITIVE_ADJUSTMENT,
        ]

        if (
            self.consumable_id
            and self.quantity is not None
            and self.movement_type in negative_types
            and self.quantity > self.consumable.current_stock
        ):
            raise ValidationError(
                {
                    "quantity": (
                        "La cantidad solicitada supera el stock disponible. "
                        f"Stock actual: {self.consumable.current_stock}."
                    )
                }
            )

        if (
            self.movement_type == self.MovementType.CONSUMPTION
            and not self.printing_device_id
        ):
            raise ValidationError(
                {
                    "printing_device": (
                        "Debe seleccionar el equipo donde se utilizó "
                        "el consumible."
                    )
                }
            )

        if (
            self.printing_device_id
            and self.consumable_id
            and not ConsumableCompatibility.objects.filter(
                printing_device_id=self.printing_device_id,
                consumable_id=self.consumable_id,
                is_active=True,
            ).exists()
        ):
            raise ValidationError(
                {
                    "printing_device": (
                        "El consumible seleccionado no está registrado "
                        "como compatible con este equipo."
                    )
                }
            )

        if (
            self.movement_type == self.MovementType.TRANSFER
            and not self.source_location
        ):
            raise ValidationError(
                {
                    "source_location": (
                        "Debe indicar la ubicación de origen "
                        "para una transferencia."
                    )
                }
            )

        if (
            self.movement_type == self.MovementType.TRANSFER
            and not self.destination_location
        ):
            raise ValidationError(
                {
                    "destination_location": (
                        "Debe indicar la ubicación de destino "
                        "para una transferencia."
                    )
                }
            )

        if (
            self.movement_type in positive_types
            and self.consumable_id
            and self.quantity is not None
            and self.consumable.maximum_stock is not None
        ):
            projected_stock = (
                self.consumable.current_stock + self.quantity
            )

            if projected_stock > self.consumable.maximum_stock:
                raise ValidationError(
                    {
                        "quantity": (
                            "Este movimiento superaría el stock máximo. "
                            f"Stock proyectado: {projected_stock}. "
                            f"Stock máximo: "
                            f"{self.consumable.maximum_stock}."
                        )
                    }
                )

    class Meta:
        verbose_name = "Movimiento de stock"
        verbose_name_plural = "Movimientos de stock"
        ordering = ["-movement_date", "-created_at"]

    def __str__(self):
        return (
            f"{self.get_movement_type_display()} - "
            f"{self.consumable} ({self.quantity})"
        )


class MeterReading(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    printing_device = models.ForeignKey(
        PrintingDevice,
        on_delete=models.PROTECT,
        related_name="meter_readings",
        verbose_name="Equipo de impresión",
    )

    reading_date = models.DateTimeField(
        "Fecha de lectura",
        default=timezone.now,
    )

    total_counter = models.PositiveBigIntegerField(
        "Contador total",
        default=0,
    )

    black_white_counter = models.PositiveBigIntegerField(
        "Contador blanco y negro",
        default=0,
    )

    color_counter = models.PositiveBigIntegerField(
        "Contador color",
        default=0,
    )

    copy_counter = models.PositiveBigIntegerField(
        "Contador de copias",
        default=0,
    )

    scan_counter = models.PositiveBigIntegerField(
        "Contador de escaneos",
        default=0,
    )

    registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="printing_meter_readings",
        verbose_name="Registrado por",
    )

    notes = models.TextField(
        "Observaciones",
        blank=True,
    )

    created_at = models.DateTimeField(
        "Fecha de registro",
        auto_now_add=True,
    )

    class Meta:
        verbose_name = "Lectura de contador"
        verbose_name_plural = "Lecturas de contadores"
        ordering = [
            "-reading_date",
            "-created_at",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "printing_device",
                    "reading_date",
                ],
                name="unique_device_meter_reading_date",
            )
        ]

    def clean(self):
        super().clean()

        counters = [
            self.black_white_counter,
            self.color_counter,
            self.copy_counter,
            self.scan_counter,
        ]

        if self.total_counter < max(counters):
            raise ValidationError(
                {
                    "total_counter": (
                        "El contador total no puede ser menor que "
                        "los contadores parciales."
                    )
                }
            )

        previous_reading = (
            MeterReading.objects.filter(
                printing_device=self.printing_device,
                reading_date__lt=self.reading_date,
            )
            .exclude(pk=self.pk)
            .order_by("-reading_date")
            .first()
        )

        if not previous_reading:
            return

        comparisons = [
            (
                "total_counter",
                "contador total",
                previous_reading.total_counter,
            ),
            (
                "black_white_counter",
                "contador blanco y negro",
                previous_reading.black_white_counter,
            ),
            (
                "color_counter",
                "contador color",
                previous_reading.color_counter,
            ),
            (
                "copy_counter",
                "contador de copias",
                previous_reading.copy_counter,
            ),
            (
                "scan_counter",
                "contador de escaneos",
                previous_reading.scan_counter,
            ),
        ]

        errors = {}

        for field_name, field_label, previous_value in comparisons:
            current_value = getattr(self, field_name)

            if current_value < previous_value:
                errors[field_name] = (
                    f"El {field_label} no puede ser menor que la lectura "
                    f"anterior: {previous_value}."
                )

        if errors:
            raise ValidationError(errors)

    @property
    def previous_reading(self):
        return (
            MeterReading.objects.filter(
                printing_device=self.printing_device,
                reading_date__lt=self.reading_date,
            )
            .exclude(pk=self.pk)
            .order_by("-reading_date")
            .first()
        )

    @property
    def total_consumption(self):
        previous = self.previous_reading

        if not previous:
            return 0

        return self.total_counter - previous.total_counter

    @property
    def black_white_consumption(self):
        previous = self.previous_reading

        if not previous:
            return 0

        return (
            self.black_white_counter
            - previous.black_white_counter
        )

    @property
    def color_consumption(self):
        previous = self.previous_reading

        if not previous:
            return 0

        return self.color_counter - previous.color_counter

    @property
    def copy_consumption(self):
        previous = self.previous_reading

        if not previous:
            return 0

        return self.copy_counter - previous.copy_counter

    @property
    def scan_consumption(self):
        previous = self.previous_reading

        if not previous:
            return 0

        return self.scan_counter - previous.scan_counter

    @property
    def active_contract(self):
        if not self.printing_device_id or not self.reading_date:
            return None

        reading_day = self.reading_date.date()

        return (
            PrintingContract.objects.filter(
                devices=self.printing_device,
                status=PrintingContract.Status.ACTIVE,
                is_active=True,
                start_date__lte=reading_day,
                end_date__gte=reading_day,
            )
            .order_by("-start_date")
            .first()
        )

    @property
    def excess_black_white(self):
        contract = self.active_contract

        if not contract:
            return 0

        return max(
            self.black_white_consumption
            - contract.included_prints_bw,
            0,
        )

    @property
    def excess_color(self):
        contract = self.active_contract

        if not contract:
            return 0

        return max(
            self.color_consumption
            - contract.included_prints_color,
            0,
        )

    @property
    def excess_cost_black_white(self):
        contract = self.active_contract

        if not contract:
            return Decimal("0.00")

        return (
            Decimal(self.excess_black_white)
            * contract.excess_cost_bw
        )

    @property
    def excess_cost_color(self):
        contract = self.active_contract

        if not contract:
            return Decimal("0.00")

        return (
            Decimal(self.excess_color)
            * contract.excess_cost_color
        )

    @property
    def total_excess_cost(self):
        return (
            self.excess_cost_black_white
            + self.excess_cost_color
        )

    @property
    def estimated_period_cost(self):
        contract = self.active_contract

        if not contract:
            return Decimal("0.00")

        return contract.monthly_cost + self.total_excess_cost

    def __str__(self):
        return (
            f"{self.printing_device} - "
            f"{self.reading_date:%d/%m/%Y %H:%M}"
        )


class MaintenanceRecord(models.Model):
    class MaintenanceType(models.TextChoices):
        PREVENTIVE = "PREVENTIVE", "Preventivo"
        CORRECTIVE = "CORRECTIVE", "Correctivo"
        INSPECTION = "INSPECTION", "Inspección"
        CLEANING = "CLEANING", "Limpieza"
        PART_REPLACEMENT = "PART_REPLACEMENT", "Cambio de repuesto"
        OTHER = "OTHER", "Otro"

    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Programado"
        IN_PROGRESS = "IN_PROGRESS", "En proceso"
        COMPLETED = "COMPLETED", "Completado"
        CANCELLED = "CANCELLED", "Cancelado"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    printing_device = models.ForeignKey(
        PrintingDevice,
        on_delete=models.PROTECT,
        related_name="maintenance_records",
        verbose_name="Equipo de impresión",
    )

    maintenance_type = models.CharField(
        "Tipo de mantenimiento",
        max_length=30,
        choices=MaintenanceType.choices,
        default=MaintenanceType.PREVENTIVE,
    )

    status = models.CharField(
        "Estado",
        max_length=20,
        choices=Status.choices,
        default=Status.SCHEDULED,
    )

    scheduled_date = models.DateTimeField(
        "Fecha programada",
        blank=True,
        null=True,
    )

    performed_date = models.DateTimeField(
        "Fecha de realización",
        blank=True,
        null=True,
    )

    next_maintenance_date = models.DateField(
        "Próximo mantenimiento",
        blank=True,
        null=True,
    )

    technician_name = models.CharField(
        "Técnico responsable",
        max_length=150,
        blank=True,
    )

    provider = models.CharField(
        "Proveedor o empresa técnica",
        max_length=150,
        blank=True,
    )

    description = models.TextField(
        "Descripción del trabajo",
    )

    diagnosis = models.TextField(
        "Diagnóstico",
        blank=True,
    )

    solution = models.TextField(
        "Solución aplicada",
        blank=True,
    )

    replaced_parts = models.TextField(
        "Repuestos reemplazados",
        blank=True,
        help_text=(
            "Ejemplo: fusor, rodillo, tambor, unidad de imagen."
        ),
    )

    meter_counter = models.PositiveBigIntegerField(
        "Contador del equipo al realizar el trabajo",
        blank=True,
        null=True,
    )

    labor_cost = models.DecimalField(
        "Costo de mano de obra",
        max_digits=14,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    parts_cost = models.DecimalField(
        "Costo de repuestos",
        max_digits=14,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="printing_maintenance_records",
        verbose_name="Registrado por",
    )

    notes = models.TextField(
        "Observaciones",
        blank=True,
    )

    created_at = models.DateTimeField(
        "Fecha de registro",
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        "Última actualización",
        auto_now=True,
    )

    class Meta:
        verbose_name = "Mantenimiento de impresión"
        verbose_name_plural = "Mantenimientos de impresión"
        ordering = [
            "-performed_date",
            "-scheduled_date",
            "-created_at",
        ]

    def clean(self):
        super().clean()

        if (
            self.status == self.Status.COMPLETED
            and not self.performed_date
        ):
            raise ValidationError(
                {
                    "performed_date": (
                        "Debe indicar la fecha de realización cuando "
                        "el mantenimiento está completado."
                    )
                }
            )

        if (
            self.next_maintenance_date
            and self.performed_date
            and self.next_maintenance_date
            < self.performed_date.date()
        ):
            raise ValidationError(
                {
                    "next_maintenance_date": (
                        "El próximo mantenimiento no puede ser anterior "
                        "a la fecha de realización."
                    )
                }
            )

    @property
    def total_cost(self):
        return self.labor_cost + self.parts_cost

    def __str__(self):
        return (
            f"{self.printing_device} - "
            f"{self.get_maintenance_type_display()}"
        )


class PrintingContract(models.Model):
    class ContractType(models.TextChoices):
        RENTAL = "RENTAL", "Alquiler"
        LEASING = "LEASING", "Leasing"
        MAINTENANCE = "MAINTENANCE", "Mantenimiento"
        LOAN = "LOAN", "Préstamo"
        OTHER = "OTHER", "Otro"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Borrador"
        ACTIVE = "ACTIVE", "Activo"
        EXPIRED = "EXPIRED", "Vencido"
        SUSPENDED = "SUSPENDED", "Suspendido"
        CANCELLED = "CANCELLED", "Cancelado"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    contract_number = models.CharField(
        "Número de contrato",
        max_length=100,
        unique=True,
    )

    contract_type = models.CharField(
        "Tipo de contrato",
        max_length=20,
        choices=ContractType.choices,
        default=ContractType.RENTAL,
    )

    provider = models.CharField(
        "Proveedor",
        max_length=150,
    )

    devices = models.ManyToManyField(
        PrintingDevice,
        related_name="contracts",
        verbose_name="Equipos incluidos",
        blank=True,
    )

    start_date = models.DateField(
        "Fecha de inicio",
    )

    end_date = models.DateField(
        "Fecha de finalización",
    )

    monthly_cost = models.DecimalField(
        "Costo mensual",
        max_digits=14,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    included_prints_bw = models.PositiveIntegerField(
        "Impresiones B/N incluidas",
        default=0,
    )

    included_prints_color = models.PositiveIntegerField(
        "Impresiones color incluidas",
        default=0,
    )

    excess_cost_bw = models.DecimalField(
        "Costo excedente B/N",
        max_digits=12,
        decimal_places=4,
        default=0,
        validators=[MinValueValidator(0)],
    )

    excess_cost_color = models.DecimalField(
        "Costo excedente color",
        max_digits=12,
        decimal_places=4,
        default=0,
        validators=[MinValueValidator(0)],
    )

    response_time_hours = models.PositiveIntegerField(
        "Tiempo de respuesta SLA en horas",
        blank=True,
        null=True,
    )

    resolution_time_hours = models.PositiveIntegerField(
        "Tiempo de resolución SLA en horas",
        blank=True,
        null=True,
    )

    contact_name = models.CharField(
        "Nombre del contacto",
        max_length=150,
        blank=True,
    )

    contact_phone = models.CharField(
        "Teléfono del contacto",
        max_length=50,
        blank=True,
    )

    contact_email = models.EmailField(
        "Correo del contacto",
        blank=True,
    )

    status = models.CharField(
        "Estado",
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    notes = models.TextField(
        "Observaciones",
        blank=True,
    )

    is_active = models.BooleanField(
        "Activo",
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
        verbose_name = "Contrato de impresión"
        verbose_name_plural = "Contratos de impresión"
        ordering = ["-start_date", "contract_number"]

    def __str__(self):
        return f"{self.contract_number} - {self.provider}"


class ConsumableStockMigrationBatch(models.Model):
    """Persistent, non-mutating audit of Printing and Inventory stock."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Borrador"
        IN_REVIEW = "IN_REVIEW", "En revisión"
        COMPLETED = "COMPLETED", "Completado"
        CANCELLED = "CANCELLED", "Cancelado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_consumable_stock_migration_batches",
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(blank=True)
    total_items = models.PositiveIntegerField(default=0, editable=False)
    pending_items = models.PositiveIntegerField(default=0, editable=False)
    reviewed_items = models.PositiveIntegerField(default=0, editable=False)
    error_items = models.PositiveIntegerField(default=0, editable=False)
    completed_at = models.DateTimeField(blank=True, null=True, editable=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Lote de conciliación de consumibles"
        verbose_name_plural = "Lotes de conciliación de consumibles"

    def __str__(self):
        return f"Conciliación {self.created_at:%d/%m/%Y %H:%M}"

    def save(self, *args, **kwargs):
        if self.pk and not self._state.adding:
            previous = type(self).objects.filter(pk=self.pk).values_list("status", flat=True).first()
            if previous == self.Status.COMPLETED:
                raise ValidationError("Un lote completado es inmutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status == self.Status.COMPLETED:
            raise ValidationError("Un lote completado no puede eliminarse.")
        return super().delete(*args, **kwargs)


class ConsumableStockMigrationItem(models.Model):
    class MatchStatus(models.TextChoices):
        LINKED = "LINKED", "Producto vinculado"
        EXACT_CODE_MATCH = "EXACT_CODE_MATCH", "Coincidencia exacta de código"
        AMBIGUOUS_CODE = "AMBIGUOUS_CODE", "Código ambiguo"
        NO_MATCH = "NO_MATCH", "Sin coincidencia"

    class QuantityStatus(models.TextChoices):
        MATCH = "MATCH", "Cantidades iguales"
        PRINTING_GREATER = "PRINTING_GREATER", "Printing mayor"
        INVENTORY_GREATER = "INVENTORY_GREATER", "Inventory mayor"
        NO_PRODUCT = "NO_PRODUCT", "Sin producto resuelto"
        NO_BALANCE = "NO_BALANCE", "Inventory sin saldo"
        NEGATIVE_PRINTING_STOCK = "NEGATIVE_PRINTING_STOCK", "Stock Printing negativo"

    class DecisionStatus(models.TextChoices):
        PENDING = "PENDING", "Pendiente"
        USE_INVENTORY = "USE_INVENTORY", "Usar Inventory"
        USE_PRINTING = "USE_PRINTING", "Usar Printing"
        PHYSICAL_COUNT_REQUIRED = "PHYSICAL_COUNT_REQUIRED", "Requiere conteo físico"
        LINK_EXISTING_PRODUCT = "LINK_EXISTING_PRODUCT", "Vincular producto existente"
        CREATE_NEW_PRODUCT_LATER = "CREATE_NEW_PRODUCT_LATER", "Crear producto posteriormente"
        IGNORE_INACTIVE = "IGNORE_INACTIVE", "Ignorar inactivo"
        BLOCKED = "BLOCKED", "Bloqueado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(
        ConsumableStockMigrationBatch,
        on_delete=models.PROTECT,
        related_name="items",
    )
    consumable = models.ForeignKey(
        Consumable,
        on_delete=models.PROTECT,
        related_name="stock_migration_items",
    )
    stock_product_candidate = models.ForeignKey(
        "inventory.StockProduct",
        on_delete=models.PROTECT,
        related_name="printing_stock_migration_candidates",
        blank=True,
        null=True,
    )
    printing_reference_snapshot = models.CharField(max_length=100)
    printing_name_snapshot = models.CharField(max_length=200)
    printing_active_snapshot = models.BooleanField()
    printing_initial_stock_snapshot = models.IntegerField()
    printing_entries_snapshot = models.IntegerField()
    printing_outputs_snapshot = models.IntegerField()
    printing_transfers_snapshot = models.IntegerField()
    printing_current_stock_snapshot = models.IntegerField()
    inventory_total_stock_snapshot = models.IntegerField(blank=True, null=True)
    inventory_has_balance_snapshot = models.BooleanField(default=False)
    stock_product_active_snapshot = models.BooleanField(blank=True, null=True)
    match_status = models.CharField(max_length=30, choices=MatchStatus.choices)
    quantity_status = models.CharField(max_length=30, choices=QuantityStatus.choices)
    decision_status = models.CharField(
        max_length=30,
        choices=DecisionStatus.choices,
        default=DecisionStatus.PENDING,
    )
    difference = models.IntegerField(blank=True, null=True)
    destination_branch = models.ForeignKey(
        "accounts.Branch",
        on_delete=models.PROTECT,
        related_name="consumable_stock_migration_items",
        blank=True,
        null=True,
    )
    destination_location = models.ForeignKey(
        "inventory.OrganizationalLocation",
        on_delete=models.PROTECT,
        related_name="consumable_stock_migration_items",
        blank=True,
        null=True,
    )
    approved_quantity = models.PositiveIntegerField(blank=True, null=True)
    inventory_stock_movement = models.OneToOneField(
        "inventory.StockMovement",
        on_delete=models.PROTECT,
        related_name="printing_stock_consolidation_item",
        blank=True,
        null=True,
        editable=False,
    )
    consolidated_quantity = models.PositiveIntegerField(blank=True, null=True, editable=False)
    consolidated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="consolidated_consumable_stock_migration_items",
        blank=True,
        null=True,
        editable=False,
    )
    consolidated_at = models.DateTimeField(blank=True, null=True, editable=False)
    notes = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviewed_consumable_stock_migration_items",
        blank=True,
        null=True,
    )
    reviewed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["printing_name_snapshot", "printing_reference_snapshot"]
        verbose_name = "Ítem de conciliación de consumible"
        verbose_name_plural = "Ítems de conciliación de consumibles"
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "consumable"],
                name="unique_consumable_per_stock_migration_batch",
            )
        ]

    def clean(self):
        super().clean()
        if (
            self.destination_branch_id
            and self.destination_location_id
            and self.destination_location.branch_id != self.destination_branch_id
        ):
            raise ValidationError(
                {"destination_location": "La ubicación debe pertenecer a la sede seleccionada."}
            )
        if self.batch_id and self.batch.status == ConsumableStockMigrationBatch.Status.COMPLETED:
            raise ValidationError("Los ítems de un lote completado son inmutables.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.batch.status == ConsumableStockMigrationBatch.Status.COMPLETED:
            raise ValidationError("Los ítems de un lote completado no pueden eliminarse.")
        return super().delete(*args, **kwargs)

    @property
    def requires_review(self):
        return (
            self.decision_status == self.DecisionStatus.PENDING
            or self.match_status in {self.MatchStatus.AMBIGUOUS_CODE, self.MatchStatus.NO_MATCH}
            or self.quantity_status != self.QuantityStatus.MATCH
            or not self.printing_active_snapshot
            or self.stock_product_active_snapshot is False
        )

    def __str__(self):
        return f"{self.printing_reference_snapshot} - {self.printing_name_snapshot}"
