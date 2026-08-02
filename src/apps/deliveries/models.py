import uuid

from django.conf import settings
from django.db import models
from apps.core.sequences import next_business_number
from django.utils import timezone


class DeliveryBatch(models.Model):
    """
    Acta agrupada de entrega.

    Una misma acta puede contener uno o varios movimientos de activos.
    Cada activo conserva su movimiento individual y su trazabilidad.
    """

    class BatchStatus(models.TextChoices):
        DRAFT = (
            "DRAFT",
            "Borrador",
        )
        PREPARED = (
            "PREPARED",
            "Preparado",
        )
        PENDING_SIGNATURE = (
            "PENDING_SIGNATURE",
            "Pendiente de firma",
        )
        DELIVERED = (
            "DELIVERED",
            "Entregado",
        )
        CANCELLED = (
            "CANCELLED",
            "Cancelado",
        )

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    batch_number = models.CharField(
        max_length=25,
        unique=True,
        blank=True,
        verbose_name="Número de acta agrupada",
    )

    status = models.CharField(
        max_length=25,
        choices=BatchStatus.choices,
        default=BatchStatus.DRAFT,
        verbose_name="Estado del acta",
    )

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="delivery_batches_received",
        blank=True,
        null=True,
        verbose_name="Receptor",
    )

    recipient_employee_number = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Legajo del receptor",
    )

    recipient_position = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Cargo del receptor",
    )

    recipient_area = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Área del receptor",
    )

    recipient_unit = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Unidad del receptor",
    )

    recipient_section = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Sección del receptor",
    )

    delivery_responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="delivery_batches_delivered",
        verbose_name="Responsable de entrega",
    )

    authorizing_director = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="delivery_batches_authorized",
        blank=True,
        null=True,
        verbose_name="Director que autoriza",
    )

    origin_unit = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Unidad de origen",
    )

    origin_department = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Departamento de origen",
    )

    origin_area = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Área de origen",
    )

    origin_section = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Sección de origen",
    )

    origin_position = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Cargo del responsable de origen",
    )

    origin_employee_number = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Legajo del responsable de origen",
    )

    department = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Departamento de destino",
    )

    location = models.CharField(
        max_length=150,
        blank=True,
        verbose_name="Ubicación de destino",
    )

    destination_branch = models.ForeignKey(
        "accounts.Branch",
        on_delete=models.PROTECT,
        related_name="delivery_batches_received",
        blank=True,
        null=True,
        verbose_name="Sede de destino",
    )

    delivery_date = models.DateTimeField(
        default=timezone.now,
        verbose_name="Fecha de entrega",
    )

    observations = models.TextField(
        blank=True,
        verbose_name="Observaciones",
    )

    director_signature = models.ImageField(
        upload_to="deliveries/batches/signatures/director/%Y/%m/",
        blank=True,
        null=True,
        verbose_name="Firma del director",
    )

    responsible_signature = models.ImageField(
        upload_to="deliveries/batches/signatures/responsible/%Y/%m/",
        blank=True,
        null=True,
        verbose_name="Firma del responsable",
    )

    recipient_signature = models.ImageField(
        upload_to="deliveries/batches/signatures/recipient/%Y/%m/",
        blank=True,
        null=True,
        verbose_name="Firma del receptor",
    )

    signed_document = models.FileField(
        upload_to="deliveries/batches/documents/%Y/%m/",
        blank=True,
        null=True,
        verbose_name="Acta agrupada firmada",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_delivery_batches",
        verbose_name="Registrado por",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de registro",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Última actualización",
    )

    class Meta:
        verbose_name = "Acta agrupada de entrega"
        verbose_name_plural = "Actas agrupadas de entrega"
        ordering = [
            "-delivery_date",
            "-created_at",
        ]

    def save(self, *args, **kwargs):
        if not self.batch_number:
            last_batch = (
                DeliveryBatch.objects
                .filter(
                    batch_number__startswith="ENTG-"
                )
                .order_by("-created_at")
                .first()
            )

            if last_batch and last_batch.batch_number:
                try:
                    last_number = int(
                        last_batch
                        .batch_number
                        .split("-")[-1]
                    )
                except ValueError:
                    last_number = 0
            else:
                last_number = 0

            next_number = next_business_number("delivery-batch", seed=last_number)
            self.batch_number = f"ENTG-{next_number:06d}"

        super().save(*args, **kwargs)

    @property
    def asset_count(self):
        return self.movements.count()

    def __str__(self):
        return (
            f"{self.batch_number} - "
            f"{self.get_status_display()}"
        )


class DeliveryBatchDocument(models.Model):
    class DocumentType(models.TextChoices):
        INTERNAL_DELIVERY = "INTERNAL_DELIVERY", "Acta interna de entrega DTI firmada"
        PATRIMONIAL_MOVEMENT = "PATRIMONIAL_MOVEMENT", "Movimiento patrimonial firmado"
        OTHER = "OTHER", "Otro documento"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    delivery_batch = models.ForeignKey(
        DeliveryBatch,
        on_delete=models.PROTECT,
        related_name="audit_documents",
        verbose_name="Acta agrupada",
    )
    document_type = models.CharField(
        max_length=30,
        choices=DocumentType.choices,
        verbose_name="Tipo de documento",
    )
    file = models.FileField(
        upload_to="deliveries/batches/audit_documents/%Y/%m/",
        verbose_name="Archivo",
    )
    observations = models.CharField(max_length=255, blank=True, verbose_name="Observaciones")
    signatures_verified = models.BooleanField(
        default=False,
        verbose_name="Firmas verificadas",
        help_text="Confirma que el documento contiene las firmas requeridas.",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_delivery_batch_documents",
        verbose_name="Cargado por",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["document_type", "-uploaded_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["delivery_batch", "document_type"],
                condition=models.Q(
                    document_type__in=["INTERNAL_DELIVERY", "PATRIMONIAL_MOVEMENT"]
                ),
                name="unique_required_document_per_delivery_batch",
            )
        ]

    def __str__(self):
        return f"{self.delivery_batch.batch_number} - {self.get_document_type_display()}"


class AssetCustodyMovement(models.Model):

    class MovementType(models.TextChoices):
        DELIVERY = (
            "DELIVERY",
            "Entrega",
        )
        RETURN = (
            "RETURN",
            "Devolución",
        )
        REASSIGNMENT = (
            "REASSIGNMENT",
            "Reasignación",
        )
        RESERVATION = (
            "RESERVATION",
            "Reserva",
        )
        CANCELLATION = (
            "CANCELLATION",
            "Cancelación",
        )

    class MovementStatus(models.TextChoices):
        IN_DELIVERY_PROCESS = (
            "IN_DELIVERY_PROCESS",
            "En proceso de entrega",
        )
        PREPARED = (
            "PREPARED",
            "Preparado",
        )
        PENDING_SIGNATURE = (
            "PENDING_SIGNATURE",
            "Pendiente de firma",
        )
        DELIVERED = (
            "DELIVERED",
            "Entregado",
        )
        CANCELLED = (
            "CANCELLED",
            "Cancelado",
        )

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    movement_number = models.CharField(
        max_length=25,
        unique=True,
        blank=True,
        verbose_name="Número de movimiento",
    )

    delivery_batch = models.ForeignKey(
        DeliveryBatch,
        on_delete=models.PROTECT,
        related_name="movements",
        blank=True,
        null=True,
        verbose_name="Acta agrupada",
    )

    asset = models.ForeignKey(
        "inventory.Asset",
        on_delete=models.PROTECT,
        related_name="custody_movements",
        verbose_name="Activo",
    )

    movement_type = models.CharField(
        max_length=20,
        choices=MovementType.choices,
        default=MovementType.DELIVERY,
        verbose_name="Tipo de movimiento",
    )

    status = models.CharField(
        max_length=25,
        choices=MovementStatus.choices,
        default=MovementStatus.IN_DELIVERY_PROCESS,
        verbose_name="Estado del movimiento",
    )

    previous_custodian = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="custody_movements_released",
        blank=True,
        null=True,
        verbose_name="Custodio anterior",
    )

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="custody_movements_received",
        blank=True,
        null=True,
        verbose_name="Receptor",
    )

    recipient_employee_number = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Legajo del receptor",
    )

    recipient_position = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Cargo del receptor",
    )

    recipient_area = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Área del receptor",
    )

    recipient_unit = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Unidad del receptor",
    )

    recipient_section = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Sección del receptor",
    )

    delivery_responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="custody_movements_delivered",
        verbose_name="Responsable de entrega",
    )

    authorizing_director = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="custody_movements_authorized",
        blank=True,
        null=True,
        verbose_name="Director que autoriza",
    )

    department = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Departamento de destino",
    )

    location = models.CharField(
        max_length=150,
        blank=True,
        verbose_name="Ubicación de destino",
    )

    destination_branch = models.ForeignKey(
        "accounts.Branch",
        on_delete=models.PROTECT,
        related_name="custody_movements_received",
        blank=True,
        null=True,
        verbose_name="Sede de destino",
    )

    movement_date = models.DateTimeField(
        default=timezone.now,
        verbose_name="Fecha del movimiento",
    )

    accessories = models.TextField(
        blank=True,
        verbose_name="Accesorios entregados",
    )

    asset_condition = models.TextField(
        blank=True,
        verbose_name="Estado físico del equipo",
    )

    observations = models.TextField(
        blank=True,
        verbose_name="Observaciones",
    )

    director_signature = models.ImageField(
        upload_to="deliveries/signatures/director/%Y/%m/",
        blank=True,
        null=True,
        verbose_name="Firma del director",
    )

    responsible_signature = models.ImageField(
        upload_to="deliveries/signatures/responsible/%Y/%m/",
        blank=True,
        null=True,
        verbose_name="Firma del responsable",
    )

    recipient_signature = models.ImageField(
        upload_to="deliveries/signatures/recipient/%Y/%m/",
        blank=True,
        null=True,
        verbose_name="Firma del receptor",
    )

    signed_document = models.FileField(
        upload_to="deliveries/documents/%Y/%m/",
        blank=True,
        null=True,
        verbose_name="Acta firmada",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_custody_movements",
        verbose_name="Registrado por",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de registro",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Última actualización",
    )

    class Meta:
        verbose_name = "Movimiento de custodia"
        verbose_name_plural = "Movimientos de custodia"
        ordering = [
            "-movement_date",
            "-created_at",
        ]

    def save(self, *args, **kwargs):
        if not self.movement_number:
            prefix_by_type = {
                self.MovementType.DELIVERY: "ENT",
                self.MovementType.RETURN: "DEV",
                self.MovementType.REASSIGNMENT: "REA",
                self.MovementType.RESERVATION: "RES",
                self.MovementType.CANCELLATION: "CAN",
            }

            prefix = prefix_by_type.get(
                self.movement_type,
                "MOV",
            )

            last_movement = (
                AssetCustodyMovement.objects
                .filter(
                    movement_number__startswith=f"{prefix}-"
                )
                .order_by("-created_at")
                .first()
            )

            if (
                last_movement
                and last_movement.movement_number
            ):
                try:
                    last_number = int(
                        last_movement
                        .movement_number
                        .split("-")[-1]
                    )
                except ValueError:
                    last_number = 0
            else:
                last_number = 0

            next_number = next_business_number(
                f"custody-movement-{prefix.lower()}",
                seed=last_number,
            )
            self.movement_number = f"{prefix}-{next_number:06d}"

        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.movement_number} - "
            f"{self.asset.internal_code} - "
            f"{self.get_movement_type_display()}"
        )


class DeliveryDocument(models.Model):

    class DocumentType(models.TextChoices):
        DELIVERY_FORM = (
            "DELIVERY_FORM",
            "Hoja de entrega firmada",
        )
        PATRIMONIAL_FORM = (
            "PATRIMONIAL_FORM",
            "Hoja patrimonial firmada",
        )
        OTHER = (
            "OTHER",
            "Otro documento",
        )

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    movement = models.ForeignKey(
        AssetCustodyMovement,
        on_delete=models.PROTECT,
        related_name="delivery_documents",
        verbose_name="Movimiento de entrega",
    )

    document_type = models.CharField(
        max_length=30,
        choices=DocumentType.choices,
        verbose_name="Tipo de documento",
    )

    file = models.FileField(
        upload_to="deliveries/audit_documents/%Y/%m/",
        verbose_name="Archivo",
    )

    observations = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Observaciones",
    )

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_delivery_documents",
        verbose_name="Cargado por",
    )

    uploaded_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de carga",
    )

    class Meta:
        verbose_name = "Documento de entrega"
        verbose_name_plural = "Documentos de entrega"
        ordering = [
            "-uploaded_at",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "movement",
                    "document_type",
                ],
                condition=models.Q(
                    document_type__in=[
                        "DELIVERY_FORM",
                        "PATRIMONIAL_FORM",
                    ]
                ),
                name="unique_required_document_per_movement",
            ),
        ]

    def __str__(self):
        return (
            f"{self.movement.movement_number} - "
            f"{self.get_document_type_display()}"
        )
