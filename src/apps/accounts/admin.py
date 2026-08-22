# ==========================================================
# ADMINISTRACIÓN DE USUARIOS, SEDES Y ACCESOS
# NOVADESK PRO — SPRINT 19
# ==========================================================

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.utils import timezone

from .models import Branch, User


# ==========================================================
# ADMINISTRACIÓN DE SEDES Y PLANTAS
# ==========================================================

@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "branch_type",
        "city",
        "is_active",
        "user_count",
        "updated_at",
    )

    list_filter = (
        "branch_type",
        "is_active",
        "city",
    )

    search_fields = (
        "code",
        "name",
        "city",
        "address",
        "email",
    )

    ordering = (
        "name",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (
            "Información principal",
            {
                "fields": (
                    "code",
                    "name",
                    "branch_type",
                    "is_active",
                ),
            },
        ),
        (
            "Ubicación y contacto",
            {
                "fields": (
                    "address",
                    "city",
                    "phone",
                    "email",
                ),
            },
        ),
        (
            "Auditoría",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                ),
                "classes": (
                    "collapse",
                ),
            },
        ),
    )

    @admin.display(
        description="Usuarios",
        ordering="users__count",
    )
    def user_count(self, obj):
        return obj.users.count()


# ==========================================================
# ADMINISTRACIÓN DE USUARIOS
# ==========================================================

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User

    # ======================================================
    # LISTADO
    # ======================================================

    list_display = (
        "email",
        "full_name",
        "role",
        "employment_type",
        "branch",
        "organizational_unit",
        "department",
        "approval_status",
        "access_status",
        "employment_end_date",
        "is_active",
        "is_staff",
    )

    list_filter = (
        "role",
        "employment_type",
        "approval_status",
        "branch",
        "organizational_unit",
        "department",
        "is_temporary_account",
        "must_change_password",
        "is_active",
        "is_staff",
        "is_superuser",
    )

    search_fields = (
        "email",
        "alternative_email",
        "username",
        "first_name",
        "last_name",
        "document_number",
        "employee_number",
        "organizational_unit__name",
        "organizational_unit__code",
        "department__name",
        "department__code",
        "position",
        "external_company",
        "branch__name",
        "branch__code",
    )

    ordering = (
        "first_name",
        "last_name",
        "email",
    )

    list_select_related = (
        "branch",
        "organizational_unit",
        "department",
        "internal_responsible",
        "approved_by",
    )

    date_hierarchy = "created_at"

    readonly_fields = (
        "created_at",
        "updated_at",
        "last_login",
        "date_joined",
        "approved_at",
        "access_status_detail",
    )

    autocomplete_fields = (
        "branch",
        "organizational_unit",
        "department",
        "internal_responsible",
        "approved_by",
    )

    actions = (
        "approve_selected_users",
        "suspend_selected_users",
        "reject_selected_users",
        "activate_selected_users",
        "deactivate_selected_users",
        "require_password_change",
        "remove_password_change_requirement",
    )

    # ======================================================
    # EDICIÓN DE USUARIO
    # ======================================================

    fieldsets = (
        (
            "Información principal",
            {
                "fields": (
                    "email",
                    "username",
                    "password",
                    "first_name",
                    "last_name",
                    "document_number",
                    "employee_number",
                    "profile_image",
                ),
            },
        ),
        (
            "Rol y vínculo laboral",
            {
                "fields": (
                    "role",
                    "employment_type",
                    "approval_status",
                    "branch",
                    "organizational_unit",                    
                    "department",
                    "position",
                ),
            },
        ),
        (
            "Contacto",
            {
                "fields": (
                    "phone",
                    "alternative_email",
                ),
            },
        ),
        (
            "Datos de usuarios externos",
            {
                "fields": (
                    "external_company",
                    "internal_responsible",
                ),
                "description": (
                    "Complete estos campos para tercerizados, "
                    "pasantes, consultores o proveedores externos."
                ),
            },
        ),
        (
            "Vigencia laboral y de acceso",
            {
                "fields": (
                    "employment_start_date",
                    "employment_end_date",
                    "is_temporary_account",
                    "must_change_password",
                    "access_status_detail",
                ),
            },
        ),
        (
            "Aprobación de cuenta",
            {
                "fields": (
                    "approved_at",
                    "approved_by",
                ),
                "classes": (
                    "collapse",
                ),
            },
        ),
        (
            "Permisos del sistema",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (
            "Fechas y auditoría",
            {
                "fields": (
                    "last_login",
                    "date_joined",
                    "created_at",
                    "updated_at",
                ),
                "classes": (
                    "collapse",
                ),
            },
        ),
    )

    # ======================================================
    # CREACIÓN DE USUARIO
    # ======================================================

    add_fieldsets = (
        (
            "Información de acceso",
            {
                "classes": (
                    "wide",
                ),
                "fields": (
                    "email",
                    "username",
                    "password1",
                    "password2",
                ),
            },
        ),
        (
            "Información personal",
            {
                "classes": (
                    "wide",
                ),
                "fields": (
                    "first_name",
                    "last_name",
                    "document_number",
                    "employee_number",
                    "phone",
                    "alternative_email",
                ),
            },
        ),
        (
            "Información laboral",
            {
                "classes": (
                    "wide",
                ),
                "fields": (
                    "role",
                    "employment_type",
                    "branch",
                    "organizational_unit",
                    "department",
                    "position",
                    "external_company",
                    "internal_responsible",
                    "employment_start_date",
                    "employment_end_date",
                    "is_temporary_account",
                ),
            },
        ),
        (
            "Aprobación y permisos",
            {
                "classes": (
                    "wide",
                ),
                "fields": (
                    "approval_status",
                    "must_change_password",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                ),
            },
        ),
    )

    # ======================================================
    # COLUMNAS CALCULADAS
    # ======================================================

    @admin.display(
        description="Nombre completo",
        ordering="first_name",
    )
    def full_name(self, obj):
        full_name = obj.get_full_name().strip()

        return full_name or "Sin nombre registrado"

    @admin.display(
        description="Estado de acceso",
    )
    def access_status(self, obj):
        if not obj.is_active:
            return "Inactiva"

        if obj.approval_status == User.ApprovalStatus.PENDING:
            return "Pendiente"

        if obj.approval_status == User.ApprovalStatus.REJECTED:
            return "Rechazada"

        if obj.approval_status == User.ApprovalStatus.SUSPENDED:
            return "Suspendida"

        if obj.is_account_expired:
            return "Vencida"

        if obj.is_account_expiring_soon:
            return "Próxima a vencer"

        if obj.can_access_system:
            return "Acceso habilitado"

        return "Sin acceso"

    @admin.display(
        description="Detalle del acceso",
    )
    def access_status_detail(self, obj):
        if not obj.pk:
            return "El estado estará disponible después de guardar."

        if not obj.is_active:
            return "La cuenta está desactivada."

        if obj.approval_status == User.ApprovalStatus.PENDING:
            return "La cuenta está pendiente de aprobación."

        if obj.approval_status == User.ApprovalStatus.REJECTED:
            return "La solicitud de acceso fue rechazada."

        if obj.approval_status == User.ApprovalStatus.SUSPENDED:
            return "La cuenta se encuentra suspendida."

        if obj.is_account_expired:
            return (
                "La cuenta venció el "
                f"{obj.employment_end_date:%d/%m/%Y}."
            )

        if obj.is_account_expiring_soon:
            return (
                "La cuenta está habilitada, pero vencerá el "
                f"{obj.employment_end_date:%d/%m/%Y}."
            )

        if obj.can_access_system:
            return "La cuenta puede acceder al sistema."

        return "La cuenta no cumple las condiciones de acceso."

    # ======================================================
    # ACCIONES MASIVAS
    # ======================================================

    @admin.action(
        description="Aprobar usuarios seleccionados",
    )
    def approve_selected_users(self, request, queryset):
        updated = queryset.update(
            approval_status=User.ApprovalStatus.APPROVED,
            approved_at=timezone.now(),
            approved_by=request.user,
            is_active=True,
        )

        self.message_user(
            request,
            (
                f"{updated} usuario(s) aprobado(s) "
                "correctamente."
            ),
            messages.SUCCESS,
        )

    @admin.action(
        description="Suspender usuarios seleccionados",
    )
    def suspend_selected_users(self, request, queryset):
        queryset = queryset.exclude(
            pk=request.user.pk
        )

        updated = queryset.update(
            approval_status=User.ApprovalStatus.SUSPENDED,
            is_active=False,
        )

        self.message_user(
            request,
            (
                f"{updated} usuario(s) suspendido(s)."
            ),
            messages.WARNING,
        )

    @admin.action(
        description="Rechazar usuarios seleccionados",
    )
    def reject_selected_users(self, request, queryset):
        queryset = queryset.exclude(
            pk=request.user.pk
        )

        updated = queryset.update(
            approval_status=User.ApprovalStatus.REJECTED,
            is_active=False,
        )

        self.message_user(
            request,
            (
                f"{updated} usuario(s) rechazado(s)."
            ),
            messages.WARNING,
        )

    @admin.action(
        description="Activar cuentas seleccionadas",
    )
    def activate_selected_users(self, request, queryset):
        updated = queryset.update(
            is_active=True,
        )

        self.message_user(
            request,
            (
                f"{updated} cuenta(s) activada(s)."
            ),
            messages.SUCCESS,
        )

    @admin.action(
        description="Desactivar cuentas seleccionadas",
    )
    def deactivate_selected_users(self, request, queryset):
        queryset = queryset.exclude(
            pk=request.user.pk
        )

        updated = queryset.update(
            is_active=False,
        )

        self.message_user(
            request,
            (
                f"{updated} cuenta(s) desactivada(s)."
            ),
            messages.WARNING,
        )

    @admin.action(
        description="Exigir cambio de contraseña",
    )
    def require_password_change(self, request, queryset):
        updated = queryset.update(
            must_change_password=True,
        )

        self.message_user(
            request,
            (
                f"{updated} usuario(s) deberá(n) "
                "cambiar su contraseña."
            ),
            messages.SUCCESS,
        )

    @admin.action(
        description="Quitar exigencia de cambio de contraseña",
    )
    def remove_password_change_requirement(
        self,
        request,
        queryset,
    ):
        updated = queryset.update(
            must_change_password=False,
        )

        self.message_user(
            request,
            (
                f"Se eliminó la exigencia para "
                f"{updated} usuario(s)."
            ),
            messages.SUCCESS,
        )

    # ======================================================
    # SEGURIDAD ADICIONAL
    # ======================================================

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                "branch",
                "internal_responsible",
                "approved_by",
            )
        )

    def save_model(
        self,
        request,
        obj,
        form,
        change,
    ):
        previous_status = None

        if change and obj.pk:
            previous_status = (
                User.objects
                .filter(pk=obj.pk)
                .values_list(
                    "approval_status",
                    flat=True,
                )
                .first()
            )

        if (
            obj.approval_status
            == User.ApprovalStatus.APPROVED
            and previous_status
            != User.ApprovalStatus.APPROVED
        ):
            obj.approved_at = timezone.now()
            obj.approved_by = request.user

        if obj.approval_status in {
            User.ApprovalStatus.REJECTED,
            User.ApprovalStatus.SUSPENDED,
        }:
            obj.is_active = False

        super().save_model(
            request,
            obj,
            form,
            change,
        )