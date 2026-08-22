# ==========================================================
# CONFIGURACIÓN INSTITUCIONAL E IDENTIDAD VISUAL
# NOVADESK PRO — SPRINT 19.5
# ==========================================================

from django.core.validators import (
    FileExtensionValidator,
    RegexValidator,
)
from django.db import models


# ==========================================================
# VALIDADORES
# ==========================================================

hex_color_validator = RegexValidator(
    regex=r"^#[0-9A-Fa-f]{6}$",
    message=(
        "Ingrese un color hexadecimal válido. "
        "Ejemplo: #1E40AF."
    ),
)


# ==========================================================
# CONFIGURACIÓN GENERAL DEL SISTEMA
# ==========================================================

class InstitutionSettings(models.Model):

    # ======================================================
    # OPCIONES DE TEMA
    # ======================================================

    class ThemeMode(models.TextChoices):
        LIGHT = (
            "LIGHT",
            "Claro",
        )
        DARK = (
            "DARK",
            "Oscuro",
        )
        SYSTEM = (
            "SYSTEM",
            "Automático según el dispositivo",
        )

    # ======================================================
    # IDENTIDAD DEL SISTEMA
    # ======================================================

    system_name = models.CharField(
        max_length=120,
        default="NovaDesk Pro",
        verbose_name="Nombre del sistema",
    )

    system_short_name = models.CharField(
        max_length=50,
        blank=True,
        default="NovaDesk",
        verbose_name="Nombre corto del sistema",
    )

    system_slogan = models.CharField(
        max_length=220,
        blank=True,
        default=(
            "Gestión integral de soporte "
            "e infraestructura tecnológica"
        ),
        verbose_name="Eslogan del sistema",
    )

    # ======================================================
    # INFORMACIÓN INSTITUCIONAL
    # ======================================================

    institution_name = models.CharField(
        max_length=180,
        default="Petróleos Paraguayos",
        verbose_name="Nombre de la institución",
    )

    institution_short_name = models.CharField(
        max_length=80,
        blank=True,
        default="PETROPAR",
        verbose_name="Nombre corto de la institución",
    )

    department_name = models.CharField(
        max_length=180,
        blank=True,
        default=(
            "Dirección de Tecnología "
            "de la Información"
        ),
        verbose_name="Departamento o dependencia",
    )

    # ======================================================
    # LOGOS E IMÁGENES
    # ======================================================

    logo = models.ImageField(
        upload_to="institution/logo/",
        blank=True,
        null=True,
        verbose_name="Logo principal",
        help_text=(
            "Logo utilizado normalmente en fondos claros."
        ),
    )

    dark_logo = models.ImageField(
        upload_to="institution/logo/dark/",
        blank=True,
        null=True,
        verbose_name="Logo para modo oscuro",
        help_text=(
            "Versión clara o blanca del logo para "
            "fondos oscuros."
        ),
    )

    compact_logo = models.ImageField(
        upload_to="institution/logo/compact/",
        blank=True,
        null=True,
        verbose_name="Logo compacto",
        help_text=(
            "Versión reducida para el menú lateral, "
            "navbar o dispositivos móviles."
        ),
    )

    favicon = models.ImageField(
        upload_to="institution/favicon/",
        blank=True,
        null=True,
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    "ico",
                    "png",
                    "jpg",
                    "jpeg",
                    "webp",
                ]
            ),
        ],
        verbose_name="Icono del navegador",
        help_text=(
            "Se recomienda una imagen cuadrada, "
            "por ejemplo 32 × 32 o 64 × 64 píxeles."
        ),
    )

    login_image = models.ImageField(
        upload_to="institution/login/",
        blank=True,
        null=True,
        verbose_name="Imagen de inicio de sesión",
        help_text=(
            "Imagen principal o fondo de la pantalla "
            "de inicio de sesión."
        ),
    )

    dashboard_image = models.ImageField(
        upload_to="institution/dashboard/",
        blank=True,
        null=True,
        verbose_name="Imagen del dashboard",
        help_text=(
            "Imagen opcional para la portada o encabezado "
            "del dashboard."
        ),
    )

    admin_logo = models.ImageField(
        upload_to="institution/admin/",
        blank=True,
        null=True,
        verbose_name="Logo del panel de administración",
        help_text=(
            "Si queda vacío, se utilizará el logo principal."
        ),
    )

    user_portal_logo = models.ImageField(
        upload_to="institution/portal/",
        blank=True,
        null=True,
        verbose_name="Logo del portal de usuarios",
        help_text=(
            "Si queda vacío, se utilizará el logo principal."
        ),
    )

    monitoring_logo = models.ImageField(
        upload_to="institution/monitoring/",
        blank=True,
        null=True,
        verbose_name="Logo de monitoreo",
        help_text=(
            "Logo específico para pantallas de monitoreo."
        ),
    )

    header_image = models.ImageField(
        upload_to="institution/header/",
        blank=True,
        null=True,
        verbose_name="Imagen de encabezado para documentos",
        help_text=(
            "Encabezado utilizado en actas, reportes y PDF."
        ),
    )

    # ======================================================
    # APARIENCIA Y TEMA
    # ======================================================

    default_theme = models.CharField(
        max_length=10,
        choices=ThemeMode.choices,
        default=ThemeMode.LIGHT,
        verbose_name="Tema predeterminado",
    )

    allow_user_theme_change = models.BooleanField(
        default=True,
        verbose_name=(
            "Permitir que cada usuario cambie el tema"
        ),
    )

    primary_color = models.CharField(
        max_length=7,
        default="#1E40AF",
        validators=[
            hex_color_validator,
        ],
        verbose_name="Color principal",
        help_text=(
            "Formato hexadecimal. Ejemplo: #1E40AF."
        ),
    )

    secondary_color = models.CharField(
        max_length=7,
        default="#0F172A",
        validators=[
            hex_color_validator,
        ],
        verbose_name="Color secundario",
        help_text=(
            "Formato hexadecimal. Ejemplo: #0F172A."
        ),
    )

    accent_color = models.CharField(
        max_length=7,
        default="#38BDF8",
        validators=[
            hex_color_validator,
        ],
        verbose_name="Color de acento",
        help_text=(
            "Se utiliza en enlaces, indicadores "
            "y elementos destacados."
        ),
    )

    success_color = models.CharField(
        max_length=7,
        default="#16A34A",
        validators=[
            hex_color_validator,
        ],
        verbose_name="Color de éxito",
    )

    warning_color = models.CharField(
        max_length=7,
        default="#F59E0B",
        validators=[
            hex_color_validator,
        ],
        verbose_name="Color de advertencia",
    )

    danger_color = models.CharField(
        max_length=7,
        default="#DC2626",
        validators=[
            hex_color_validator,
        ],
        verbose_name="Color de error o peligro",
    )

    # ======================================================
    # INFORMACIÓN DE CONTACTO
    # ======================================================

    address = models.CharField(
        max_length=220,
        blank=True,
        verbose_name="Dirección",
    )

    city = models.CharField(
        max_length=100,
        blank=True,
        default="Villa Elisa",
        verbose_name="Ciudad",
    )

    country = models.CharField(
        max_length=100,
        blank=True,
        default="Paraguay",
        verbose_name="País",
    )

    phone = models.CharField(
        max_length=60,
        blank=True,
        verbose_name="Teléfono",
    )

    email = models.EmailField(
        blank=True,
        verbose_name="Correo institucional",
    )

    website = models.URLField(
        blank=True,
        verbose_name="Sitio web",
    )

    # ======================================================
    # DOCUMENTOS Y REPORTES
    # ======================================================

    director_name = models.CharField(
        max_length=160,
        blank=True,
        verbose_name="Director responsable",
    )

    document_code = models.CharField(
        max_length=50,
        blank=True,
        default="TI-ACT-001",
        verbose_name="Código del documento",
    )

    footer_text = models.CharField(
        max_length=255,
        blank=True,
        default=(
            "Documento generado automáticamente "
            "por NovaDesk Pro."
        ),
        verbose_name="Texto de pie de página",
    )

    show_logo_in_pdf = models.BooleanField(
        default=True,
        verbose_name="Mostrar logo en documentos PDF",
    )

    show_header_in_pdf = models.BooleanField(
        default=True,
        verbose_name=(
            "Mostrar encabezado institucional en PDF"
        ),
    )

    # ======================================================
    # CONFIGURACIÓN REGIONAL
    # ======================================================

    timezone_name = models.CharField(
        max_length=60,
        default="America/Asuncion",
        verbose_name="Zona horaria",
    )

    date_format = models.CharField(
        max_length=30,
        default="d/m/Y",
        verbose_name="Formato de fecha",
        help_text=(
            "Formato de Django. Ejemplo: d/m/Y."
        ),
    )

    currency_code = models.CharField(
        max_length=10,
        default="PYG",
        verbose_name="Moneda",
        help_text=(
            "Ejemplos: PYG, USD o BRL."
        ),
    )

    # ======================================================
    # ESTADO Y AUDITORÍA
    # ======================================================

    is_active = models.BooleanField(
        default=True,
        verbose_name="Configuración activa",
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
        verbose_name = "Configuración del sistema"
        verbose_name_plural = "Configuración del sistema"
        ordering = [
            "-updated_at",
        ]

    def __str__(self):
        return (
            f"{self.system_name} - "
            f"{self.institution_short_name}"
        )

    # ======================================================
    # CONFIGURACIÓN ACTIVA
    # ======================================================

    @classmethod
    def get_active(cls):
        return (
            cls.objects
            .filter(
                is_active=True
            )
            .order_by(
                "-updated_at"
            )
            .first()
        )

    # ======================================================
    # LOGOS DE RESPALDO
    # ======================================================

    @property
    def effective_dark_logo(self):
        """
        Si no hay logo oscuro, devuelve el logo principal.
        """

        return self.dark_logo or self.logo

    @property
    def effective_compact_logo(self):
        """
        Si no hay logo compacto, devuelve el logo principal.
        """

        return self.compact_logo or self.logo

    @property
    def effective_admin_logo(self):
        """
        Si no hay logo específico del administrador,
        devuelve el logo principal.
        """

        return self.admin_logo or self.logo

    @property
    def effective_user_portal_logo(self):
        """
        Si no hay logo específico del portal,
        devuelve el logo principal.
        """

        return self.user_portal_logo or self.logo

    @property
    def effective_monitoring_logo(self):
        """
        Si no hay logo específico de monitoreo,
        devuelve el logo principal.
        """

        return self.monitoring_logo or self.logo


# ==========================================================
# ESTRUCTURA ORGANIZACIONAL INSTITUCIONAL
# ==========================================================

class OrganizationalUnit(models.Model):

    class UnitType(models.TextChoices):
        PRESIDENCY = "PRESIDENCY", "Presidencia"
        GENERAL_MANAGEMENT = "GENERAL_MANAGEMENT", "Gerencia General"
        MANAGEMENT = "MANAGEMENT", "Gerencia"
        DIRECTORATE = "DIRECTORATE", "Dirección"
        DEPUTY_DIRECTORATE = "DEPUTY_DIRECTORATE", "Dirección Adjunta"
        SUB_MANAGEMENT = "SUB_MANAGEMENT", "Sub-Gerencia"
        UNIT = "UNIT", "Unidad"
        OFFICE = "OFFICE", "Oficina"
        DEPARTMENT = "DEPARTMENT", "Departamento"
        OTHER = "OTHER", "Otro"

    name = models.CharField(
        max_length=200,
        verbose_name="Nombre",
    )

    code = models.CharField(
        max_length=80,
        unique=True,
        verbose_name="Código",
    )

    unit_type = models.CharField(
        max_length=30,
        choices=UnitType.choices,
        verbose_name="Tipo de dependencia",
    )

    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
        verbose_name="Dependencia superior",
    )

    operational_department = models.ForeignKey(
        "core.Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="organizational_units",
        verbose_name="Departamento operativo relacionado",
        help_text=(
            "Relación opcional con un departamento operativo "
            "utilizado por tickets, usuarios e inventario."
        ),
    )

    order = models.PositiveIntegerField(
        default=0,
        verbose_name="Orden",
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
        verbose_name = "Dependencia institucional"
        verbose_name_plural = "Dependencias institucionales"
        ordering = [
            "parent_id",
            "order",
            "name",
        ]

    def __str__(self):
        return self.name