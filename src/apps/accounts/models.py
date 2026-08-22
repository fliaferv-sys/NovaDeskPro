import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

from apps.core.models import Department  # ⬅️ IMPORT PARA DEPARTMENT


# ==========================================================
# SEDES, SUCURSALES Y PLANTAS INDUSTRIALES
# ==========================================================

class Branch(models.Model):
    """
    Representa una sede, sucursal o planta industrial
    de la institución.
    """

    class BranchType(models.TextChoices):
        HEADQUARTERS = (
            "HEADQUARTERS",
            "Casa central",
        )
        BRANCH = (
            "BRANCH",
            "Sucursal",
        )
        INDUSTRIAL_PLANT = (
            "INDUSTRIAL_PLANT",
            "Planta industrial",
        )
        OFFICE = (
            "OFFICE",
            "Oficina administrativa",
        )
        OTHER = (
            "OTHER",
            "Otra",
        )

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    code = models.CharField(
        max_length=30,
        unique=True,
        verbose_name="Código",
        help_text=(
            "Código único de la sede. "
            "Ejemplo: PLANTA-01."
        ),
    )

    name = models.CharField(
        max_length=150,
        unique=True,
        verbose_name="Nombre",
    )

    branch_type = models.CharField(
        max_length=30,
        choices=BranchType.choices,
        default=BranchType.INDUSTRIAL_PLANT,
        verbose_name="Tipo de sede",
    )

    address = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Dirección",
    )

    city = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Ciudad",
    )

    phone = models.CharField(
        max_length=30,
        blank=True,
        null=True,
        verbose_name="Teléfono",
    )

    email = models.EmailField(
        blank=True,
        null=True,
        verbose_name="Correo de contacto",
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Sede activa",
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
        verbose_name = "Sede "
        verbose_name_plural = "Sedes"
        ordering = [
            "name",
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"


# ==========================================================
# USUARIO PERSONALIZADO
# ==========================================================

class User(AbstractUser):

    class AvailabilityStatus(models.TextChoices):
        AVAILABLE = "AVAILABLE", "Disponible"
        BUSY = "BUSY", "Ocupado"
        UNAVAILABLE = "UNAVAILABLE", "No disponible"

    last_auto_assignment_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Última asignación automática",
    )

    availability_status = models.CharField(
        max_length=20,
        choices=AvailabilityStatus.choices,
        default=AvailabilityStatus.AVAILABLE,
        verbose_name="Disponibilidad",
    )

    # ======================================================
    # ROLES DEL SISTEMA
    # ======================================================

    class Role(models.TextChoices):
        ADMIN = (
            "ADMIN",
            "Administrador",
        )
        SUPERVISOR = (
            "SUPERVISOR",
            "Supervisor",
        )
        TECHNICIAN = (
            "TECHNICIAN",
            "Técnico",
        )
        AUDITOR = (
            "AUDITOR",
            "Auditor",
        )
        CLIENT = (
            "CLIENT",
            "Usuario final",
        )

    # ======================================================
    # TIPOS DE VÍNCULO LABORAL
    # ======================================================

    class EmploymentType(models.TextChoices):
        PERMANENT = (
            "PERMANENT",
            "Funcionario permanente",
        )
        CONTRACTED = (
            "CONTRACTED",
            "Funcionario contratado",
        )
        OUTSOURCED = (
            "OUTSOURCED",
            "Tercerizado",
        )
        INTERN = (
            "INTERN",
            "Pasante",
        )
        CONSULTANT = (
            "CONSULTANT",
            "Consultor",
        )
        EXTERNAL_PROVIDER = (
            "EXTERNAL_PROVIDER",
            "Proveedor externo",
        )
        OTHER = (
            "OTHER",
            "Otro",
        )

    # ======================================================
    # ESTADO DE APROBACIÓN
    # ======================================================

    class ApprovalStatus(models.TextChoices):
        PENDING = (
            "PENDING",
            "Pendiente de aprobación",
        )
        APPROVED = (
            "APPROVED",
            "Aprobado",
        )
        REJECTED = (
            "REJECTED",
            "Rechazado",
        )
        SUSPENDED = (
            "SUSPENDED",
            "Suspendido",
        )

    # ======================================================
    # IDENTIFICACIÓN
    # ======================================================

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    email = models.EmailField(
        unique=True,
        verbose_name="Correo electrónico",
    )

    alternative_email = models.EmailField(
        blank=True,
        null=True,
        verbose_name="Correo alternativo",
        help_text=(
            "Útil para tercerizados, pasantes "
            "o usuarios sin correo corporativo."
        ),
    )

    document_number = models.CharField(
        max_length=30,
        unique=True,
        blank=True,
        null=True,
        verbose_name="Número de documento",
    )

    employee_number = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        null=True,
        verbose_name="Número de funcionario",
    )

    # ======================================================
    # ROL Y VÍNCULO
    # ======================================================

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.CLIENT,
        verbose_name="Rol",
    )

    employment_type = models.CharField(
        max_length=30,
        choices=EmploymentType.choices,
        default=EmploymentType.PERMANENT,
        verbose_name="Tipo de vínculo",
    )

    approval_status = models.CharField(
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.APPROVED,
        verbose_name="Estado de aprobación",
        help_text=(
            "Los usuarios existentes quedan aprobados "
            "para no bloquear su acceso."
        ),
    )

    # ======================================================
    # UBICACIÓN ORGANIZACIONAL
    # ======================================================

    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="users",
        blank=True,
        null=True,
        verbose_name="Sede",
    )

    position = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Cargo",
    )

        # ======================================================
    # UBICACIÓN ORGANIZACIONAL DEL USUARIO
    # ======================================================

    organizational_unit = models.ForeignKey(
        "institution.OrganizationalUnit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users",
        verbose_name="Dependencia institucional",
        help_text=(
            "Dependencia real del funcionario dentro del organigrama "
            "institucional: Dirección, Gerencia, Unidad, Departamento, "
            "Oficina u otra dependencia."
        ),
    )

    # ======================================================
    # DEPARTAMENTO OPERATIVO
    # ======================================================

    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users",
        verbose_name="Departamento operativo",
        help_text=(
            "Departamento utilizado internamente por NovaDesk Pro "
            "para tickets, categorías, SLA y asignaciones."
        ),
    )

    # ======================================================
    # DATOS DE USUARIOS EXTERNOS
    # ======================================================

    external_company = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        verbose_name="Empresa de origen",
        help_text=(
            "Empresa del tercerizado, consultor "
            "o proveedor externo."
        ),
    )

    internal_responsible = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        related_name="external_users_under_responsibility",
        blank=True,
        null=True,
        verbose_name="Responsable interno",
        help_text=(
            "Funcionario interno responsable del "
            "tercerizado, pasante o proveedor."
        ),
    )

    # ======================================================
    # VIGENCIA LABORAL Y DE ACCESO
    # ======================================================

    employment_start_date = models.DateField(
        blank=True,
        null=True,
        verbose_name="Fecha de ingreso",
    )

    employment_end_date = models.DateField(
        blank=True,
        null=True,
        verbose_name="Fecha de vencimiento",
        help_text=(
            "Especialmente útil para pasantes, "
            "tercerizados y contratados."
        ),
    )

    is_temporary_account = models.BooleanField(
        default=False,
        verbose_name="Cuenta temporal",
    )

    must_change_password = models.BooleanField(
        default=False,
        verbose_name="Debe cambiar la contraseña",
    )

    approved_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Fecha de aprobación",
    )

    approved_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        related_name="approved_user_accounts",
        blank=True,
        null=True,
        verbose_name="Aprobado por",
    )

    # ======================================================
    # CONTACTO Y PERFIL
    # ======================================================

    phone = models.CharField(
        max_length=30,
        blank=True,
        null=True,
        verbose_name="Teléfono",
    )

    profile_image = models.ImageField(
        upload_to="users/profiles/",
        blank=True,
        null=True,
        verbose_name="Imagen de perfil",
    )

    # ======================================================
    # AUDITORÍA
    # ======================================================

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de creación",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Última actualización",
    )

    USERNAME_FIELD = "email"

    REQUIRED_FIELDS = [
        "username",
        "first_name",
        "last_name",
    ]

    class Meta:
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"
        ordering = [
            "first_name",
            "last_name",
        ]

    def __str__(self):
        full_name = self.get_full_name().strip()

        if full_name:
            return f"{full_name} - {self.email}"

        return self.email

    # ======================================================
    # PROPIEDADES ÚTILES
    # ======================================================

    @property
    def is_external_user(self):
        """
        Indica si el usuario pertenece a una empresa externa
        o posee un vínculo no permanente.
        """

        return self.employment_type in {
            self.EmploymentType.OUTSOURCED,
            self.EmploymentType.CONSULTANT,
            self.EmploymentType.EXTERNAL_PROVIDER,
        }

    @property
    def is_account_expired(self):
        """
        Indica si la fecha de vigencia del usuario ya venció.
        """

        if not self.employment_end_date:
            return False

        return self.employment_end_date < timezone.localdate()

    @property
    def is_account_expiring_soon(self):
        """
        Indica si la cuenta vencerá durante los próximos
        treinta días.
        """

        if not self.employment_end_date:
            return False

        today = timezone.localdate()

        days_remaining = (
            self.employment_end_date - today
        ).days

        return 0 <= days_remaining <= 30

    @property
    def can_access_system(self):
        """
        Validación general para saber si la cuenta debería
        tener acceso al sistema.
        """

        return (
            self.is_active
            and self.approval_status
            == self.ApprovalStatus.APPROVED
            and not self.is_account_expired
        )

    # ==========================================================
# TURNOS LABORALES DE TÉCNICOS
# ==========================================================


class WorkShift(models.Model):
    """
    Define los turnos laborales disponibles para los técnicos.

    Ejemplos:
    - Turno 07:00 a 15:00
    - Turno 08:00 a 16:00
    """

    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Nombre del turno",
    )

    start_time = models.TimeField(
        verbose_name="Hora de entrada",
    )

    end_time = models.TimeField(
        verbose_name="Hora de salida",
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Activo",
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
        verbose_name = "Turno laboral"
        verbose_name_plural = "Turnos laborales"
        ordering = [
            "start_time",
            "end_time",
        ]

    def __str__(self):
        return (
            f"{self.name} "
            f"({self.start_time.strftime('%H:%M')} - "
            f"{self.end_time.strftime('%H:%M')})"
        )


# ==========================================================
# JORNADA DIARIA DEL TÉCNICO
# ==========================================================


class TechnicianWorkday(models.Model):
    """
    Registra la presencia diaria de un técnico.

    Cuando el técnico inicia su jornada:
    - se registra la hora real de llegada;
    - se determina el turno correspondiente;
    - se calcula la hora programada de salida.

    Al llegar a la hora de salida, la jornada podrá
    finalizarse automáticamente.
    """

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Presente"
        FINISHED = "FINISHED", "Finalizada"

    technician = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="technician_workdays",
        limit_choices_to={
            "role": "TECHNICIAN",
        },
        verbose_name="Técnico",
    )

    date = models.DateField(
        verbose_name="Fecha",
    )

    shift = models.ForeignKey(
        WorkShift,
        on_delete=models.PROTECT,
        related_name="technician_workdays",
        verbose_name="Turno",
    )

    started_at = models.DateTimeField(
        verbose_name="Inicio real de jornada",
    )

    scheduled_end_at = models.DateTimeField(
        verbose_name="Fin programado de jornada",
    )

    ended_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fin real de jornada",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        verbose_name="Estado de jornada",
    )

    ended_automatically = models.BooleanField(
        default=False,
        verbose_name="Finalizada automáticamente",
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
        verbose_name = "Jornada de técnico"
        verbose_name_plural = "Jornadas de técnicos"
        ordering = [
            "-date",
            "-started_at",
        ]

        

    def __str__(self):
        technician_name = (
            self.technician.get_full_name().strip()
            or self.technician.email
        )

        return (
            f"{technician_name} - "
            f"{self.date.strftime('%d/%m/%Y')} - "
            f"{self.shift.name}"
        )

    @property
    def is_active_workday(self):
        return (
            self.status == self.Status.ACTIVE
            and self.ended_at is None
        )


class TechnicianAvailabilityRequest(models.Model):
    class RequestType(models.TextChoices):
        UNAVAILABLE = "UNAVAILABLE", "No disponible"
        EARLY_WORKDAY_END = "EARLY_WORKDAY_END", "Fin de jornada anticipada"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendiente"
        APPROVED = "APPROVED", "Aprobada"
        REJECTED = "REJECTED", "Rechazada"

    technician = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="availability_requests",
        limit_choices_to={"role": User.Role.TECHNICIAN},
        verbose_name="Técnico",
    )
    workday = models.ForeignKey(
        TechnicianWorkday,
        on_delete=models.PROTECT,
        related_name="availability_requests",
        verbose_name="Jornada",
    )
    request_type = models.CharField(
        max_length=30,
        choices=RequestType.choices,
        verbose_name="Tipo de solicitud",
    )
    reason = models.TextField(verbose_name="Motivo")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="Estado",
    )
    requested_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha y hora de solicitud",
    )
    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha y hora de resolución",
    )
    resolved_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="resolved_availability_requests",
        null=True,
        blank=True,
        verbose_name="Resuelta por",
    )
    resolution_note = models.TextField(
        blank=True,
        verbose_name="Observación de resolución",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Solicitud de disponibilidad de técnico"
        verbose_name_plural = "Solicitudes de disponibilidad de técnicos"
        ordering = ["-requested_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["technician", "workday", "request_type"],
                condition=models.Q(status="PENDING"),
                name="unique_pending_technician_availability_request",
            ),
        ]

    def __str__(self):
        return (
            f"{self.technician.get_full_name() or self.technician.username} - "
            f"{self.get_request_type_display()} - {self.get_status_display()}"
        )

    

    

