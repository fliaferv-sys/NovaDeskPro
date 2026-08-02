# ==========================================================
# ADMINISTRACIÓN DEL INVENTARIO
# NOVADESK PRO — SPRINT 19
# ==========================================================

from django.contrib import admin


from .models import (
    Asset,
    AssetTechnicalHistory,
    OrganizationalLocation,
    AcquisitionBatch,
    AcquisitionBatchDocument,
)


# ==========================================================
# UBICACIONES ORGANIZACIONALES
# ==========================================================

@admin.register(OrganizationalLocation)
class OrganizationalLocationAdmin(admin.ModelAdmin):

    list_display = (
        "code",
        "name",
        "location_type",
        "branch",
        "parent",
        "is_active",
        
    )

    list_filter = (
        "branch",
        "location_type",
        "is_active",
    )

    search_fields = (
        "code",
        "name",
        "description",
        "branch__code",
        "branch__name",
        "parent__code",
        "parent__name",
    )

    ordering = (
        "branch__name",
        "name",
    )

    list_select_related = (
        "branch",
        "parent",
    )

    autocomplete_fields = (
        "branch",
        "parent",
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
                    "branch",
                    "code",
                    "name",
                    "location_type",
                    "is_active",
                ),
            },
        ),
        (
            "Jerarquía de ubicación",
            {
                "fields": (
                    "parent",
                    "full_path_display",
                ),
                "description": (
                    "Puede relacionar una oficina con un piso, "
                    "un piso con un edificio y así sucesivamente."
                ),
            },
        ),
        (
            "Descripción",
            {
                "fields": (
                    "description",
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

    # ==========================================================
# LOTES DE ADQUISICIÓN
# ==========================================================

class AcquisitionBatchDocumentInline(admin.TabularInline):
    model = AcquisitionBatchDocument
    extra = 1
    fields = ("document_type", "file", "observations", "verified", "uploaded_by")
    readonly_fields = ("uploaded_by",)


@admin.register(AcquisitionBatch)
class AcquisitionBatchAdmin(admin.ModelAdmin):

    list_display = (
        "code",
        "date",
        "supplier",
        "expected_quantity",
        "registered_quantity_display",
        "status",
    )

    list_filter = ("status", "date")

    search_fields = (
        "code",
        "description",
        "supplier",
        "reference",
    )

    inlines = (AcquisitionBatchDocumentInline,)

    @admin.display(description="Registrados")
    def registered_quantity_display(self, obj):
        return obj.registered_quantity

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            if isinstance(instance, AcquisitionBatchDocument) and not instance.uploaded_by_id:
                instance.uploaded_by = request.user
            instance.save()
        for instance in formset.deleted_objects:
            instance.delete()
        formset.save_m2m()
# ==========================================================
# ACTIVOS INFORMÁTICOS
# ==========================================================

@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):

    list_display = (
        "internal_code",
        "asset_type",
        "brand",
        "model",
        "branch",
        "physical_location",
        "assigned_user",
        "acquisition_batch",
        "operational_status",
        "connection_status",
        "health_score_display",
        
    )

    list_filter = (
        "asset_type",
        "branch",
        "physical_location",
        "operational_status",
        "connection_status",
        "department",
        "purchase_date",
        "warranty_expiration",
    )

    search_fields = (
        "internal_code",
        "patrimonial_code",
        "serial_number",
        "hostname",
        "brand",
        "model",
        "department",
        "location",
        "branch__code",
        "branch__name",
        "physical_location__code",
        "physical_location__name",
        "assigned_user__first_name",
        "assigned_user__last_name",
        "assigned_user__email",
    )

    ordering = (
        "internal_code",
    )

    list_select_related = (
        "branch",
        "physical_location",
        "assigned_user",
    )

    autocomplete_fields = (
        "branch",
        "physical_location",
        "assigned_user",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
        "full_location_display",
        "health_score_display",
        "health_label_display",
    )

    fieldsets = (
        (
            "Identificación del activo",
            {
                "fields": (
                    "internal_code",
                    "patrimonial_code",
                    "asset_type",
                    "brand",
                    "model",
                    "serial_number",
                    "hostname",
                ),
            },
        ),
        (
            "Custodio responsable",
            {
                "fields": (
                    "assigned_user",
                ),
                "description": (
                    "El custodio es la persona responsable "
                    "del equipo y puede ser diferente de su "
                    "ubicación física."
                ),
            },
        ),
        (
            "Ubicación física",
            {
                "fields": (
                    "branch",
                    "physical_location",
                    "department",
                    "location",
                    "full_location_display",
                ),
                "description": (
                    "Seleccione la sede o planta y luego "
                    "la ubicación física detallada del activo."
                ),
            },
        ),
        (
            "Estado operativo y conectividad",
            {
                "fields": (
                    "operational_status",
                    "connection_status",
                    "operating_system",
                    "current_ip",
                    "mac_address",
                ),
            },
        ),
        (
            "Compra, garantía y proveedor",
            {
                "fields": (
                    "purchase_date",
                    "warranty_expiration",
                    "supplier",
                ),
            },
        ),
        (
            "Salud del equipo",
            {
                "fields": (
                    "health_score_display",
                    "health_label_display",
                ),
                "classes": (
                    "collapse",
                ),
            },
        ),
        (
            "Observaciones",
            {
                "fields": (
                    "notes",
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
        description="Ubicación completa",
    )
    def full_location_display(self, obj):
        if not obj.pk:
            return (
                "La ubicación completa estará disponible "
                "después de guardar."
            )

        return obj.full_location

    @admin.display(
        description="Salud",
        ordering="operational_status",
    )
    def health_score_display(self, obj):
        return f"{obj.health_score}%"

    @admin.display(
        description="Clasificación de salud",
    )
    def health_label_display(self, obj):
        return obj.health_label


# ==========================================================
# HISTORIAL TÉCNICO
# ==========================================================

@admin.register(AssetTechnicalHistory)
class AssetTechnicalHistoryAdmin(admin.ModelAdmin):

    list_display = (
        "asset",
        "intervention_type",
        "technician",
        "ticket",
        "intervention_date",
        "duration_minutes",
        "cost",
    )

    list_filter = (
        "intervention_type",
        "intervention_date",
        "technician",
        "asset__branch",
    )

    search_fields = (
        "asset__internal_code",
        "asset__patrimonial_code",
        "asset__serial_number",
        "ticket__ticket_number",
        "technician__first_name",
        "technician__last_name",
        "technician__email",
        "diagnosis",
        "action_taken",
        "components_replaced",
        "notes",
    )

    list_select_related = (
        "asset",
        "technician",
        "ticket",
    )

    autocomplete_fields = (
        "asset",
        "technician",
        "ticket",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    ordering = (
        "-intervention_date",
    )

    fieldsets = (
        (
            "Información principal",
            {
                "fields": (
                    "asset",
                    "ticket",
                    "technician",
                    "intervention_type",
                    "intervention_date",
                ),
            },
        ),
        (
            "Detalle técnico",
            {
                "fields": (
                    "diagnosis",
                    "action_taken",
                    "components_replaced",
                    "duration_minutes",
                    "cost",
                    "notes",
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
