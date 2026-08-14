import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.accounts.models import Branch


# ==========================================================
# UBICACIONES FÍSICAS Y ORGANIZACIONALES
# NOVADESK PRO — SPRINT 19
# ==========================================================

class OrganizationalLocation(models.Model):
    """
    Representa una ubicación física dentro de una sede o planta.

    Permite crear estructuras como:

    Planta Industrial 1
        └── Edificio Administrativo
            └── Segundo Piso
                └── Oficina de Informática
    """

    class LocationType(models.TextChoices):
        BUILDING = (
            "BUILDING",
            "Edificio",
        )
        FLOOR = (
            "FLOOR",
            "Piso",
        )
        OFFICE = (
            "OFFICE",
            "Oficina",
        )
        AREA = (
            "AREA",
            "Área o sector",
        )
        WAREHOUSE = (
            "WAREHOUSE",
            "Depósito",
        )
        SERVER_ROOM = (
            "SERVER_ROOM",
            "Sala de servidores",
        )
        WORKSHOP = (
            "WORKSHOP",
            "Taller técnico",
        )
        MEETING_ROOM = (
            "MEETING_ROOM",
            "Sala de reuniones",
        )
        PRODUCTION_AREA = (
            "PRODUCTION_AREA",
            "Área de producción",
        )
        OTHER = (
            "OTHER",
            "Otra ubicación",
        )

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="organizational_locations",
        verbose_name="Sede o planta",
    )

    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="children",
        blank=True,
        null=True,
        verbose_name="Ubicación superior",
        help_text=(
            "Ejemplo: una oficina puede depender de un piso, "
            "y un piso puede depender de un edificio."
        ),
    )

    code = models.CharField(
        max_length=50,
        verbose_name="Código",
        help_text=(
            "Código único dentro de la sede. "
            "Ejemplo: EDIF-A, PISO-02 u OF-203."
        ),
    )

    name = models.CharField(
        max_length=150,
        verbose_name="Nombre",
    )

    location_type = models.CharField(
        max_length=30,
        choices=LocationType.choices,
        default=LocationType.AREA,
        verbose_name="Tipo de ubicación",
    )

    description = models.TextField(
        blank=True,
        verbose_name="Descripción",
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Ubicación activa",
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
        verbose_name = "Ubicación organizacional"
        verbose_name_plural = "Ubicaciones organizacionales"
        ordering = [
            "branch__name",
            "name",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "branch",
                    "code",
                ],
                name=(
                    "unique_organizational_location_"
                    "code_per_branch"
                ),
            ),
        ]

    def __str__(self):
        return (
            f"{self.branch.name} - "
            f"{self.code} - {self.name}"
        )

    @property
    def full_path(self):
        """
        Devuelve la ruta completa de la ubicación.

        Ejemplo:
        Edificio A / Piso 2 / Oficina 203
        """

        locations = []
        current_location = self

        while current_location:
            locations.append(
                current_location.name
            )
            current_location = (
                current_location.parent
            )

        locations.reverse()

        return " / ".join(locations)


# ==========================================================
# ACTIVO INFORMÁTICO
# ==========================================================

class Asset(models.Model):

    class AssetType(models.TextChoices):
        DESKTOP = (
            "DESKTOP",
            "Computadora de escritorio",
        )
        LAPTOP = (
            "LAPTOP",
            "Notebook",
        )
        PRINTER = (
            "PRINTER",
            "Impresora",
        )
        SCANNER = (
            "SCANNER",
            "Escáner",
        )
        MONITOR = (
            "MONITOR",
            "Monitor",
        )
        UPS = (
            "UPS",
            "UPS",
        )
        ROUTER = (
            "ROUTER",
            "Router",
        )
        SWITCH = (
            "SWITCH",
            "Switch",
        )
        IP_PHONE = (
            "IP_PHONE",
            "Teléfono IP",
        )
        OTHER = (
            "OTHER",
            "Otro",
        )


    class OperationalStatus(models.TextChoices):
        OPERATIONAL = (
            "OPERATIONAL",
            "Operativo",
        )
        MAINTENANCE = (
            "MAINTENANCE",
            "En mantenimiento",
        )
        OBSERVATION = (
            "OBSERVATION",
            "En observación",
        )
        OUT_OF_SERVICE = (
            "OUT_OF_SERVICE",
            "Fuera de servicio",
        )
        RETIRED = (
            "RETIRED",
            "Dado de baja",
        )

    class ConnectionStatus(models.TextChoices):
        ONLINE = (
            "ONLINE",
            "En línea",
        )
        OFFLINE = (
            "OFFLINE",
            "Fuera de línea",
        )
        UNKNOWN = (
            "UNKNOWN",
            "Sin información",
        )

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    internal_code = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Código interno",
    )

    patrimonial_code = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Código patrimonial",
    )

    asset_type = models.CharField(
        max_length=20,
        choices=AssetType.choices,
        default=AssetType.DESKTOP,
        verbose_name="Tipo de equipo",
    )

    brand = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Marca",
    )

    model = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Modelo",
    )

    serial_number = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        unique=True,
        verbose_name="Número de serie",
    )

    hostname = models.CharField(
        max_length=150,
        blank=True,
        verbose_name="Nombre del equipo",
    )

    # ======================================================
    # CUSTODIO DEL ACTIVO
    # ======================================================

    assigned_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="assigned_assets",
        blank=True,
        null=True,
        verbose_name="Usuario asignado",
        help_text=(
            "Persona responsable o custodio del equipo. "
            "No necesariamente representa su ubicación física."
        ),
    )

    # ======================================================
    # LOTE DE ADQUISICIÓN
    # ======================================================

    acquisition_batch = models.ForeignKey(
        "inventory.AcquisitionBatch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assets",
        verbose_name="Lote de adquisición",
    )

    # ======================================================
    # UBICACIÓN FÍSICA DEL ACTIVO
    # ======================================================

    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="assets",
        blank=True,
        null=True,
        verbose_name="Sede o planta",
        help_text=(
            "Sede o planta donde se encuentra físicamente "
            "el equipo."
        ),
    )

    physical_location = models.ForeignKey(
        OrganizationalLocation,
        on_delete=models.SET_NULL,
        related_name="assets",
        blank=True,
        null=True,
        verbose_name="Ubicación física detallada",
        help_text=(
            "Edificio, piso, oficina, depósito, "
            "sala técnica o sector."
        ),
    )

    department = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Departamento",
    )

    location = models.CharField(
        max_length=150,
        blank=True,
        verbose_name="Ubicación descriptiva",
        help_text=(
            "Campo adicional para referencias como "
            "mesa, rack, puesto, oficina o sector específico."
        ),
    )

    # ======================================================
    # ESTADO Y CONECTIVIDAD
    # ======================================================

    operational_status = models.CharField(
        max_length=30,
        choices=OperationalStatus.choices,
        default=OperationalStatus.OPERATIONAL,
        verbose_name="Estado operativo",
    )

    connection_status = models.CharField(
        max_length=20,
        choices=ConnectionStatus.choices,
        default=ConnectionStatus.UNKNOWN,
        verbose_name="Estado de conexión",
    )

    operating_system = models.CharField(
        max_length=150,
        blank=True,
        verbose_name="Sistema operativo",
    )

    current_ip = models.GenericIPAddressField(
        protocol="both",
        unpack_ipv4=True,
        blank=True,
        null=True,
        verbose_name="Dirección IP actual",
    )

    mac_address = models.CharField(
        max_length=17,
        blank=True,
        verbose_name="Dirección MAC",
    )

    # ======================================================
    # COMPRA Y GARANTÍA
    # ======================================================

    purchase_date = models.DateField(
        blank=True,
        null=True,
        verbose_name="Fecha de compra",
    )

    warranty_expiration = models.DateField(
        blank=True,
        null=True,
        verbose_name="Vencimiento de garantía",
    )

    supplier = models.CharField(
        max_length=150,
        blank=True,
        verbose_name="Proveedor",
    )

    notes = models.TextField(
        blank=True,
        verbose_name="Observaciones",
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
        verbose_name = "Activo informático"
        verbose_name_plural = "Activos informáticos"
        ordering = [
            "internal_code",
        ]

    def __str__(self):
        return (
            f"{self.internal_code} - "
            f"{self.get_asset_type_display()}"
        )

    # ======================================================
    # UBICACIÓN COMPLETA DEL ACTIVO
    # ======================================================

    @property
    def full_location(self):
        """
        Devuelve una descripción completa de la ubicación
        física del activo.
        """

        location_parts = []

        if self.branch:
            location_parts.append(
                self.branch.name
            )

        if self.physical_location:
            location_parts.append(
                self.physical_location.full_path
            )

        if self.department:
            location_parts.append(
                self.department
            )

        if self.location:
            location_parts.append(
                self.location
            )

        if not location_parts:
            return "Ubicación no registrada"

        return " / ".join(location_parts)

    @property
    def effective_branch(self):
        """
        Devuelve la sede propia del activo.

        Si el activo aún no tiene sede configurada, utiliza
        temporalmente la sede del usuario asignado.
        """

        if self.branch:
            return self.branch

        if (
            self.assigned_user
            and self.assigned_user.branch
        ):
            return self.assigned_user.branch

        return None

    # ======================================================
    # SALUD DEL EQUIPO
    # ======================================================

    @property
    def health_score(self):
        score = 100

        operational_penalties = {
            self.OperationalStatus.OPERATIONAL: 0,
            self.OperationalStatus.OBSERVATION: 15,
            self.OperationalStatus.MAINTENANCE: 25,
            self.OperationalStatus.OUT_OF_SERVICE: 50,
            self.OperationalStatus.RETIRED: 70,
        }

        score -= operational_penalties.get(
            self.operational_status,
            0,
        )

        connection_penalties = {
            self.ConnectionStatus.ONLINE: 0,
            self.ConnectionStatus.UNKNOWN: 5,
            self.ConnectionStatus.OFFLINE: 10,
        }

        score -= connection_penalties.get(
            self.connection_status,
            0,
        )

        if (
            self.warranty_expiration
            and self.warranty_expiration
            < timezone.localdate()
        ):
            score -= 10

        ticket_count = self.tickets.count()

        if ticket_count >= 15:
            score -= 25

        elif ticket_count >= 10:
            score -= 18

        elif ticket_count >= 5:
            score -= 10

        elif ticket_count >= 3:
            score -= 5

        return max(
            0,
            min(score, 100),
        )

    @property
    def health_label(self):
        score = self.health_score

        if score >= 85:
            return "Excelente"

        if score >= 70:
            return "Buena"

        if score >= 50:
            return "Requiere seguimiento"

        if score >= 30:
            return "Crítica"

        return "Recomendado reemplazo"

    @property
    def health_class(self):
        score = self.health_score

        if score >= 85:
            return "excellent"

        if score >= 70:
            return "good"

        if score >= 50:
            return "warning"

        return "critical"


# ==========================================================
# HISTORIAL TÉCNICO DEL ACTIVO
# ==========================================================

class AssetTechnicalHistory(models.Model):

    class InterventionType(models.TextChoices):
        DIAGNOSIS = (
            "DIAGNOSIS",
            "Diagnóstico",
        )
        REPAIR = (
            "REPAIR",
            "Reparación",
        )
        PREVENTIVE_MAINTENANCE = (
            "PREVENTIVE_MAINTENANCE",
            "Mantenimiento preventivo",
        )
        CORRECTIVE_MAINTENANCE = (
            "CORRECTIVE_MAINTENANCE",
            "Mantenimiento correctivo",
        )
        COMPONENT_REPLACEMENT = (
            "COMPONENT_REPLACEMENT",
            "Cambio de componente",
        )
        SOFTWARE_INSTALLATION = (
            "SOFTWARE_INSTALLATION",
            "Instalación de software",
        )
        OPERATING_SYSTEM = (
            "OPERATING_SYSTEM",
            "Sistema operativo",
        )
        OTHER = (
            "OTHER",
            "Otro",
        )

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    asset = models.ForeignKey(
        Asset,
        on_delete=models.CASCADE,
        related_name="technical_history",
        verbose_name="Activo",
    )

    ticket = models.ForeignKey(
        "tickets.Ticket",
        on_delete=models.SET_NULL,
        related_name="technical_interventions",
        blank=True,
        null=True,
        verbose_name="Ticket relacionado",
    )

    technician = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="asset_interventions",
        verbose_name="Técnico responsable",
    )

    intervention_type = models.CharField(
        max_length=40,
        choices=InterventionType.choices,
        default=InterventionType.DIAGNOSIS,
        verbose_name="Tipo de intervención",
    )

    diagnosis = models.TextField(
        blank=True,
        verbose_name="Diagnóstico",
    )

    action_taken = models.TextField(
        verbose_name="Acción realizada",
    )

    components_replaced = models.TextField(
        blank=True,
        verbose_name="Componentes reemplazados",
    )

    duration_minutes = models.PositiveIntegerField(
        blank=True,
        null=True,
        verbose_name="Duración en minutos",
    )

    cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="Costo",
    )

    intervention_date = models.DateTimeField(
        default=timezone.now,
        verbose_name="Fecha de intervención",
    )

    notes = models.TextField(
        blank=True,
        verbose_name="Observaciones",
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
        verbose_name = "Intervención técnica"
        verbose_name_plural = "Intervenciones técnicas"
        ordering = [
            "-intervention_date",
        ]

    def __str__(self):
        return (
            f"{self.asset.internal_code} - "
            f"{self.get_intervention_type_display()}"
        )
class AcquisitionBatch(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Borrador"
        PENDING_DOCUMENTS = "PENDING_DOCUMENTS", "Pendiente de documentación"
        VALIDATED = "VALIDATED", "Validado"
        CLOSED = "CLOSED", "Cerrado"
        CANCELLED = "CANCELLED", "Cancelado"

    code = models.CharField(max_length=50, unique=True, verbose_name="Código del lote")
    date = models.DateField()
    document = models.FileField(
        upload_to="batches/",
        blank=True,
        verbose_name="Documento principal anterior",
        help_text="Campo heredado. Use Documentos del lote para nuevas cargas.",
    )
    description = models.TextField(blank=True)

    status = models.CharField(
        max_length=25,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name="Estado",
    )
    supplier = models.CharField(
        max_length=150,
        blank=True,
        verbose_name="Proveedor",
    )
    reference = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Orden de compra, contrato o referencia",
    )
    expected_quantity = models.PositiveIntegerField(
        default=0,
        verbose_name="Cantidad esperada",
    )
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="acquisition_batches_received",
        blank=True,
        null=True,
        verbose_name="Responsable de recepción",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return self.code

    @property
    def registered_quantity(self):
        return self.assets.count()

    @property
    def quantity_matches(self):
        return not self.expected_quantity or self.registered_quantity == self.expected_quantity


class AcquisitionBatchDocument(models.Model):
    class DocumentType(models.TextChoices):
        PURCHASE_ORDER = "PURCHASE_ORDER", "Orden de compra o contrato"
        INVOICE = "INVOICE", "Factura"
        DELIVERY_NOTE = "DELIVERY_NOTE", "Remisión"
        RECEIPT_REPORT = "RECEIPT_REPORT", "Acta de recepción"
        WARRANTY = "WARRANTY", "Garantía"
        OTHER = "OTHER", "Otro documento"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(
        AcquisitionBatch,
        on_delete=models.PROTECT,
        related_name="audit_documents",
        verbose_name="Lote",
    )
    document_type = models.CharField(
        max_length=30,
        choices=DocumentType.choices,
        verbose_name="Tipo de documento",
    )
    file = models.FileField(
        upload_to="inventory/acquisition_batches/%Y/%m/",
        verbose_name="Archivo",
    )
    observations = models.CharField(max_length=255, blank=True, verbose_name="Observaciones")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_acquisition_documents",
        verbose_name="Cargado por",
    )
    verified = models.BooleanField(
        default=False,
        verbose_name="Documento verificado",
        help_text="Confirma que el archivo fue revisado y corresponde al lote.",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["document_type", "-uploaded_at"]

    def __str__(self):
        return f"{self.batch.code} - {self.get_document_type_display()}"


# ==========================================================
# STOCK GENÉRICO
# ==========================================================

class StockCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField("Nombre", max_length=120)
    code = models.SlugField("Código", max_length=50, unique=True)
    description = models.TextField("Descripción", blank=True)
    is_active = models.BooleanField("Activa", default=True)
    created_at = models.DateTimeField("Fecha de creación", auto_now_add=True)
    updated_at = models.DateTimeField("Última actualización", auto_now=True)

    class Meta:
        verbose_name = "Categoría de stock"
        verbose_name_plural = "Categorías de stock"
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} - {self.name}"


class StockProduct(models.Model):
    class UnitOfMeasure(models.TextChoices):
        UNIT = "UNIT", "Unidad"
        BOX = "BOX", "Caja"
        METER = "METER", "Metro"
        ROLL = "ROLL", "Rollo"
        PACKAGE = "PACKAGE", "Paquete"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField("Nombre", max_length=200)
    reference_code = models.CharField(
        "Código de referencia", max_length=100, unique=True
    )
    category = models.ForeignKey(
        StockCategory,
        on_delete=models.PROTECT,
        related_name="products",
        verbose_name="Categoría",
    )
    brand = models.CharField("Marca", max_length=150, blank=True)
    model = models.CharField("Modelo", max_length=150, blank=True)
    description = models.TextField("Descripción", blank=True)
    unit_of_measure = models.CharField(
        "Unidad de medida",
        max_length=20,
        choices=UnitOfMeasure.choices,
        default=UnitOfMeasure.UNIT,
    )
    minimum_stock = models.PositiveIntegerField("Stock mínimo", default=0)
    is_active = models.BooleanField("Activo", default=True)
    default_location = models.ForeignKey(
        OrganizationalLocation,
        on_delete=models.PROTECT,
        related_name="default_stock_products",
        verbose_name="Ubicación predeterminada",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField("Fecha de creación", auto_now_add=True)
    updated_at = models.DateTimeField("Última actualización", auto_now=True)

    class Meta:
        verbose_name = "Producto de stock"
        verbose_name_plural = "Productos de stock"
        ordering = ["name", "reference_code"]

    def __str__(self):
        return f"{self.reference_code} - {self.name}"


class StockBalance(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(
        StockProduct,
        on_delete=models.PROTECT,
        related_name="balances",
        verbose_name="Producto",
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="stock_balances",
        verbose_name="Sede o planta",
    )
    organizational_location = models.ForeignKey(
        OrganizationalLocation,
        on_delete=models.PROTECT,
        related_name="stock_balances",
        verbose_name="Ubicación organizacional",
    )
    quantity = models.PositiveIntegerField("Cantidad actual", default=0)
    minimum_stock = models.PositiveIntegerField(
        "Stock mínimo en la ubicación", blank=True, null=True
    )
    created_at = models.DateTimeField("Fecha de creación", auto_now_add=True)
    updated_at = models.DateTimeField("Última actualización", auto_now=True)

    class Meta:
        verbose_name = "Saldo de stock"
        verbose_name_plural = "Saldos de stock"
        ordering = ["product__name", "branch__name", "organizational_location__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "branch", "organizational_location"],
                name="unique_stock_balance_per_location",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gte=0),
                name="stock_balance_quantity_nonnegative",
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.organizational_location_id
            and self.branch_id
            and self.organizational_location.branch_id != self.branch_id
        ):
            raise ValidationError(
                {"organizational_location": "La ubicación debe pertenecer a la sede seleccionada."}
            )

    def __str__(self):
        return f"{self.product} - {self.organizational_location}: {self.quantity}"


class StockMovement(models.Model):
    class Direction(models.TextChoices):
        ENTRY = "ENTRY", "Entrada"
        EXIT = "EXIT", "Salida"

    class Reason(models.TextChoices):
        PURCHASE = "PURCHASE", "Compra"
        RETURN = "RETURN", "Devolución"
        INITIAL_ENTRY = "INITIAL_ENTRY", "Ingreso inicial"
        DELIVERY = "DELIVERY", "Entrega"
        REPAIR = "REPAIR", "Uso en reparación"
        CONSUMPTION = "CONSUMPTION", "Consumo"
        WRITE_OFF = "WRITE_OFF", "Baja"
        ADJUSTMENT = "ADJUSTMENT", "Ajuste"
        POSITIVE_ADJUSTMENT = "POSITIVE_ADJUSTMENT", "Ajuste positivo"
        NEGATIVE_ADJUSTMENT = "NEGATIVE_ADJUSTMENT", "Ajuste negativo"
        TRANSFER = "TRANSFER", "Transferencia"
        OTHER = "OTHER", "Otro"

    ENTRY_REASONS = frozenset(
        {
            Reason.PURCHASE,
            Reason.RETURN,
            Reason.INITIAL_ENTRY,
            Reason.ADJUSTMENT,
            Reason.POSITIVE_ADJUSTMENT,
            Reason.TRANSFER,
            Reason.OTHER,
        }
    )
    EXIT_REASONS = frozenset(
        {
            Reason.DELIVERY,
            Reason.REPAIR,
            Reason.CONSUMPTION,
            Reason.WRITE_OFF,
            Reason.ADJUSTMENT,
            Reason.NEGATIVE_ADJUSTMENT,
            Reason.TRANSFER,
            Reason.OTHER,
        }
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(
        StockProduct,
        on_delete=models.PROTECT,
        related_name="stock_movements",
        verbose_name="Producto",
    )
    balance = models.ForeignKey(
        StockBalance,
        on_delete=models.PROTECT,
        related_name="movements",
        verbose_name="Saldo",
    )
    quantity = models.PositiveIntegerField("Cantidad")
    direction = models.CharField(
        "Dirección", max_length=10, choices=Direction.choices
    )
    reason = models.CharField("Motivo", max_length=20, choices=Reason.choices)
    movement_date = models.DateTimeField("Fecha del movimiento", default=timezone.now)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="inventory_stock_movements",
        verbose_name="Registrado por",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="received_stock_movements",
        verbose_name="Destinatario",
        blank=True,
        null=True,
    )
    department = models.ForeignKey(
        "core.Department",
        on_delete=models.PROTECT,
        related_name="stock_movements",
        verbose_name="Departamento",
        blank=True,
        null=True,
    )
    observation = models.TextField("Observación", blank=True)
    document_reference = models.CharField(
        "Referencia documental", max_length=100, blank=True
    )
    created_at = models.DateTimeField("Fecha de registro", auto_now_add=True)

    class Meta:
        verbose_name = "Movimiento de stock"
        verbose_name_plural = "Movimientos de stock"
        ordering = ["-movement_date", "-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="stock_movement_quantity_positive",
            )
        ]

    def clean(self):
        super().clean()
        if self.balance_id and self.product_id != self.balance.product_id:
            raise ValidationError(
                {"product": "El producto debe coincidir con el saldo seleccionado."}
            )
        allowed_reasons = (
            self.ENTRY_REASONS
            if self.direction == self.Direction.ENTRY
            else self.EXIT_REASONS
        )
        if self.direction and self.reason not in allowed_reasons:
            raise ValidationError(
                {"reason": "El motivo no corresponde a la dirección seleccionada."}
            )

    def __str__(self):
        return f"{self.get_direction_display()} - {self.product} ({self.quantity})"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError(
                "Los movimientos confirmados no pueden modificarse; registre un movimiento compensatorio."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los movimientos confirmados no pueden eliminarse.")
    

    
    
