import uuid

from datetime import timedelta
from django.conf import settings
from django.db import models
from django.utils import timezone
from apps.core.sequences import next_business_number


class Ticket(models.Model):

    class Status(models.TextChoices):
        OPEN = "OPEN", "Abierto"
        IN_PROGRESS = "IN_PROGRESS", "En proceso"
        WAITING = "WAITING", "En espera"
        RESOLVED = "RESOLVED", "Resuelto"
        CLOSED = "CLOSED", "Cerrado"

    class Priority(models.TextChoices):
        LOW = "LOW", "Baja"
        MEDIUM = "MEDIUM", "Media"
        HIGH = "HIGH", "Alta"
        CRITICAL = "CRITICAL", "Crítica"

    class Category(models.TextChoices):
        HARDWARE = "HARDWARE", "Hardware"
        SOFTWARE = "SOFTWARE", "Software"
        NETWORK = "NETWORK", "Red"
        PRINTER = "PRINTER", "Impresora"
        ELECTRICITY = "ELECTRICITY", "Electricidad"
        OTHER = "OTHER", "Otro"

    class Group(models.TextChoices):
        SUPPORT = "SUPPORT", "Soporte"
        SYSTEMS = "SYSTEMS", "Sistemas"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    ticket_number = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        verbose_name="Número de ticket",
    )

    title = models.CharField(
        max_length=200,
        verbose_name="Título",
    )

    description = models.TextField(
        verbose_name="Descripción",
    )

    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_tickets",
        verbose_name="Solicitante",
    )

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="assigned_tickets",
        blank=True,
        null=True,
        verbose_name="Técnico asignado",
    )

    asset = models.ForeignKey(
        "inventory.Asset",
        on_delete=models.SET_NULL,
        related_name="tickets",
        blank=True,
        null=True,
        verbose_name="Equipo relacionado",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
        verbose_name="Estado",
    )

    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.MEDIUM,
        verbose_name="Prioridad",
    )

    category = models.CharField(
        max_length=20,
        choices=Category.choices,
        default=Category.OTHER,
        verbose_name="Categoría",
    )

    department = models.ForeignKey(
        "core.Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets",
        verbose_name="Departamento"
    )

    assigned_group = models.CharField(
        max_length=20,
        choices=Group.choices,
        default=Group.SUPPORT,
        verbose_name="Grupo asignado",
    )

    due_date = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Fecha límite (SLA)",
    )

    sla_status = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name="Estado del SLA",
        help_text="OK, WARNING o EXPIRED"
    )

    resolved_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Fecha de resolución",
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
        verbose_name = "Ticket"
        verbose_name_plural = "Tickets"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.ticket_number:
            last_ticket = Ticket.objects.order_by("-created_at").first()

            if last_ticket and last_ticket.ticket_number:
                try:
                    last_number = int(last_ticket.ticket_number.replace("TKT-", ""))
                    new_number = last_number + 1
                except (ValueError, AttributeError):
                    new_number = 1
            else:
                new_number = 1

            new_number = next_business_number("ticket", seed=new_number - 1)
            self.ticket_number = f"TKT-{new_number:06d}"

        if self.department and self.department.sla_hours:
            if not self.due_date:
                self.due_date = timezone.now() + timedelta(hours=self.department.sla_hours)

        self.update_sla_status()

        super().save(*args, **kwargs)

    def update_sla_status(self):
        if self.due_date:
            now = timezone.now()
            if self.due_date < now:
                self.sla_status = "EXPIRED"
            elif self.due_date < now + timedelta(hours=4):
                self.sla_status = "WARNING"
            else:
                self.sla_status = "OK"
        else:
            self.sla_status = None
        return self.sla_status

    def __str__(self):
        return f"{self.ticket_number} - {self.title}"

class QuickAction(models.Model):
    """
    Accesos rápidos para precargar tickets.
    Se gestionan desde el admin sin tocar código.
    """
    
    title = models.CharField(
        max_length=200,
        verbose_name="Título del ticket"
    )
    
    description = models.TextField(
        verbose_name="Descripción del ticket"
    )
    
    department = models.ForeignKey(
        "core.Department",
        on_delete=models.CASCADE,
        related_name="quick_actions",
        verbose_name="Departamento"
    )
    
    icon = models.CharField(
        max_length=50,
        blank=True,
        default="bi-tag",
        verbose_name="Icono",
        help_text="Clase de Bootstrap Icons (ej: bi-printer, bi-laptop, bi-lightning)"
    )
    
    label = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="Etiqueta",
        help_text="Texto corto que aparece debajo (ej: Hardware, Red, Electricidad)"
    )
    
    is_active = models.BooleanField(
        default=True,
        verbose_name="Activo"
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
        verbose_name = "Acceso rápido"
        verbose_name_plural = "Accesos rápidos"
        ordering = ["department", "order", "title"]
    
    def __str__(self):
        return f"{self.department.name} - {self.title}"

    
class TicketComment(models.Model):

    class CommentType(models.TextChoices):
        COMMENT = "COMMENT", "Comentario"
        ASSIGN = "ASSIGN", "Asignación"
        STATUS = "STATUS", "Cambio de estado"
        ATTACHMENT = "ATTACHMENT", "Adjunto"
        SYSTEM = "SYSTEM", "Sistema"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="comments",
        verbose_name="Ticket",
    )

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ticket_comments",
        verbose_name="Autor",
    )

    message = models.TextField(
        verbose_name="Comentario",
    )

    is_system = models.BooleanField(
        default=False,
        verbose_name="Comentario del sistema",
    )

    comment_type = models.CharField(
        max_length=20,
        choices=CommentType.choices,
        default=CommentType.COMMENT,
        verbose_name="Tipo de comentario",
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
        verbose_name = "Comentario de Ticket"
        verbose_name_plural = "Comentarios de Tickets"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.author} - {self.ticket.ticket_number}"


class TicketAttachment(models.Model):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="attachments",
        verbose_name="Ticket",
    )

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ticket_attachments",
        verbose_name="Subido por",
    )

    file = models.FileField(
        upload_to="tickets/attachments/%Y/%m/",
        verbose_name="Archivo",
    )

    original_name = models.CharField(
        max_length=255,
        verbose_name="Nombre original",
    )

    content_type = models.CharField(
        max_length=150,
        blank=True,
        verbose_name="Tipo de archivo",
    )

    size = models.PositiveBigIntegerField(
        default=0,
        verbose_name="Tamaño en bytes",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de carga",
    )

    class Meta:
        verbose_name = "Archivo adjunto"
        verbose_name_plural = "Archivos adjuntos"
        ordering = ["created_at"]

    def __str__(self):
        return self.original_name

 # ==========================================================
# SOLICITUDES DE ACCESO A SISTEMAS
# ALTA, BAJA, MODIFICACIÓN Y PERMISOS
# ==========================================================

class SystemAccessRequest(models.Model):

    class RequestOperation(models.TextChoices):
        USER_CREATION = "USER_CREATION", "Alta de usuario"
        USER_DELETION = "USER_DELETION", "Baja de usuario"
        USER_MODIFICATION = "USER_MODIFICATION", "Modificación de usuario"
        PERMISSION_CHANGE = "PERMISSION_CHANGE", "Asignación o modificación de permisos"

    class AuthorizationStatus(models.TextChoices):
        DRAFT = "DRAFT", "Borrador"
        PENDING_FORM = "PENDING_FORM", "Pendiente de formulario"
        FORM_ATTACHED = "FORM_ATTACHED", "Formulario adjuntado"
        PENDING_VALIDATION = "PENDING_VALIDATION", "Pendiente de validación"
        AUTHORIZED = "AUTHORIZED", "Autorizado para procesar"
        REJECTED = "REJECTED", "Formulario rechazado"

    ticket = models.OneToOneField(
        Ticket,
        on_delete=models.CASCADE,
        related_name="system_access_request",
        verbose_name="Ticket",
    )

    requested_system = models.CharField(
        max_length=100,
        verbose_name="Sistema solicitado",
    )

    operation = models.CharField(
        max_length=30,
        choices=RequestOperation.choices,
        verbose_name="Tipo de operación",
    )

    affected_employee = models.CharField(
        max_length=200,
        verbose_name="Funcionario afectado",
    )

    employee_number = models.CharField(
        max_length=50,
        verbose_name="Legajo",
    )

    affected_document_number = models.CharField(
        max_length=30,
        blank=True,
        default="",
        verbose_name="Numero de cedula",
    )

    requested_email = models.EmailField(
        blank=True,
        verbose_name="Correo solicitado",
    )

    employee_department = models.CharField(
        max_length=150,
        verbose_name="Departamento del funcionario",
    )

    employee_position = models.CharField(
        max_length=150,
        blank=True,
        verbose_name="Cargo",
    )

    requested_permissions = models.TextField(
        blank=True,
        verbose_name="Permisos solicitados",
    )

    justification = models.TextField(
        verbose_name="Justificación",
    )

    authorizing_director = models.CharField(
        max_length=200,
        verbose_name="Director autorizante",
    )

    observations = models.TextField(
        blank=True,
        verbose_name="Observaciones",
    )

    authorization_status = models.CharField(
        max_length=30,
        choices=AuthorizationStatus.choices,
        default=AuthorizationStatus.DRAFT,
        verbose_name="Estado de autorización",
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
        verbose_name = "Solicitud de acceso a sistema"
        verbose_name_plural = "Solicitudes de acceso a sistemas"
        ordering = ["-created_at"]

        permissions = [
            (
                "validate_access_request",
                "Puede validar solicitudes de acceso",
            ),
        ]

    def __str__(self):
        return (
            f"{self.ticket.ticket_number} - "
            f"{self.get_operation_display()} - "
            f"{self.requested_system}"
        )   

# ==========================================================
# FORMULARIOS GENERADOS POR NOVADESK
# DOCUMENTOS SIN FIRMA PARA DESCARGAR
# ==========================================================

class GeneratedAuthorizationForm(models.Model):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    access_request = models.ForeignKey(
        SystemAccessRequest,
        on_delete=models.CASCADE,
        related_name="generated_forms",
        verbose_name="Solicitud de acceso",
    )

    file = models.FileField(
        upload_to="tickets/generated_authorization_forms/%Y/%m/",
        verbose_name="Formulario generado",
    )

    original_name = models.CharField(
        max_length=255,
        verbose_name="Nombre del formulario",
    )

    version = models.PositiveIntegerField(
        default=1,
        verbose_name="Versión",
    )

    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="generated_authorization_forms",
        verbose_name="Generado por",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de generación",
    )

    class Meta:
        verbose_name = "Formulario de autorización generado"
        verbose_name_plural = "Formularios de autorización generados"
        ordering = ["-version", "-created_at"]

        constraints = [
            models.UniqueConstraint(
                fields=["access_request", "version"],
                name="unique_generated_authorization_form_version",
            )
        ]

    def __str__(self):
        return (
            f"{self.access_request.ticket.ticket_number} - "
            f"Formulario generado - Versión {self.version}"
        )
    
# ==========================================================
# DOCUMENTOS DE AUTORIZACIÓN
# FORMULARIOS FIRMADOS
# ==========================================================

class AuthorizationDocument(models.Model):

    class ValidationStatus(models.TextChoices):
        PENDING = "PENDING", "Pendiente de validación"
        APPROVED = "APPROVED", "Aprobado"
        REJECTED = "REJECTED", "Rechazado"
        REPLACED = "REPLACED", "Reemplazado"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    access_request = models.ForeignKey(
        SystemAccessRequest,
        on_delete=models.CASCADE,
        related_name="authorization_documents",
        verbose_name="Solicitud de acceso",
    )

    file = models.FileField(
        upload_to="tickets/authorization_forms/%Y/%m/",
        verbose_name="Formulario firmado",
    )

    original_name = models.CharField(
        max_length=255,
        verbose_name="Nombre original",
    )

    content_type = models.CharField(
        max_length=150,
        blank=True,
        verbose_name="Tipo de archivo",
    )

    size = models.PositiveBigIntegerField(
        default=0,
        verbose_name="Tamaño en bytes",
    )

    version = models.PositiveIntegerField(
        default=1,
        verbose_name="Versión",
    )

    validation_status = models.CharField(
        max_length=20,
        choices=ValidationStatus.choices,
        default=ValidationStatus.PENDING,
        verbose_name="Estado de validación",
    )

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_authorization_documents",
        verbose_name="Adjuntado por",
    )

    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="validated_authorization_documents",
        blank=True,
        null=True,
        verbose_name="Validado por",
    )

    validated_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Fecha de validación",
    )

    rejection_reason = models.TextField(
        blank=True,
        verbose_name="Motivo del rechazo",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de carga",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Última actualización",
    )

    class Meta:
        verbose_name = "Documento de autorización"
        verbose_name_plural = "Documentos de autorización"
        ordering = ["-version", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["access_request", "version"],
                name="unique_authorization_document_version",
            )
        ]

    def __str__(self):
        return (
            f"{self.access_request.ticket.ticket_number} - "
            f"Versión {self.version} - "
            f"{self.get_validation_status_display()}"
        )    


class AccessIdentityDocument(models.Model):
    """Copia de identidad presentada con cada formulario firmado."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    access_request = models.ForeignKey(
        SystemAccessRequest,
        on_delete=models.CASCADE,
        related_name="identity_documents",
        verbose_name="Solicitud de acceso",
    )
    file = models.FileField(
        upload_to="tickets/identity_documents/%Y/%m/",
        verbose_name="Fotocopia de cedula",
    )
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=150, blank=True)
    size = models.PositiveBigIntegerField(default=0)
    version = models.PositiveIntegerField(default=1)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_access_identity_documents",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["access_request", "version"],
                name="unique_access_identity_document_version",
            ),
        ]

    def __str__(self):
        return (
            f"{self.access_request.ticket.ticket_number} - "
            f"Cedula - Version {self.version}"
        )
