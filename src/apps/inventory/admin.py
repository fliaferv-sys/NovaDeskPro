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
    StockBalance,
    StockCategory,
    StockMovement,
    StockProduct,
    StockEntryOperation,
    StockEntryLine,
    StockEntryDocument,
    StockDelivery,
    StockDeliveryLine,
    TicketStockUsage,
    TicketStockUsageLine,
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


@admin.register(StockCategory)
class StockCategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("code", "name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(StockProduct)
class StockProductAdmin(admin.ModelAdmin):
    list_display = (
        "reference_code",
        "name",
        "category",
        "brand",
        "model",
        "unit_of_measure",
        "minimum_stock",
        "is_active",
    )
    list_filter = ("category", "is_active", "unit_of_measure")
    search_fields = ("reference_code", "name", "brand", "model")
    autocomplete_fields = ("category", "default_location")
    readonly_fields = ("created_at", "updated_at")


@admin.register(StockBalance)
class StockBalanceAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "branch",
        "organizational_location",
        "quantity",
        "minimum_stock",
        "updated_at",
    )
    list_filter = ("product", "branch", "organizational_location")
    search_fields = (
        "product__reference_code",
        "product__name",
        "branch__name",
        "organizational_location__name",
    )
    autocomplete_fields = ("product", "branch", "organizational_location")
    readonly_fields = ("quantity", "created_at", "updated_at")

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj:
            fields.extend(("product", "branch", "organizational_location"))
        return fields


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        "movement_date",
        "product",
        "direction",
        "reason",
        "quantity",
        "ticket",
        "performed_by",
        "recipient",
    )
    list_filter = ("direction", "reason", "product", "movement_date")
    search_fields = (
        "product__reference_code",
        "product__name",
        "document_reference",
    )
    list_select_related = (
        "product",
        "balance",
        "performed_by",
        "recipient",
        "department",
    )
    readonly_fields = tuple(
        field.name for field in StockMovement._meta.fields
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in {"GET", "HEAD"} and super().has_change_permission(
            request, obj
        )

    def has_delete_permission(self, request, obj=None):
        return False


class StockEntryLineInline(admin.TabularInline):
    model = StockEntryLine
    extra = 0
    readonly_fields = ("movement", "created_at")

    def has_change_permission(self, request, obj=None):
        return not obj or obj.status == StockEntryOperation.Status.DRAFT

    def has_add_permission(self, request, obj=None):
        return not obj or obj.status == StockEntryOperation.Status.DRAFT

    def has_delete_permission(self, request, obj=None):
        return not obj or obj.status == StockEntryOperation.Status.DRAFT


class StockEntryDocumentInline(admin.TabularInline):
    model = StockEntryDocument
    extra = 0
    readonly_fields = ("uploaded_by", "uploaded_at")

    def has_change_permission(self, request, obj=None):
        return not obj or obj.status == StockEntryOperation.Status.DRAFT

    def has_add_permission(self, request, obj=None):
        return not obj or obj.status == StockEntryOperation.Status.DRAFT

    def has_delete_permission(self, request, obj=None):
        return not obj or obj.status == StockEntryOperation.Status.DRAFT


@admin.register(StockEntryOperation)
class StockEntryOperationAdmin(admin.ModelAdmin):
    list_display = ("number", "entry_date", "reason", "supplier", "status", "created_by", "confirmed_by")
    list_filter = ("status", "reason", "entry_date")
    search_fields = ("number", "supplier", "invoice_number", "purchase_order_number", "delivery_note_number")
    readonly_fields = ("number", "created_by", "confirmed_by", "confirmed_at", "created_at", "updated_at")
    inlines = (StockEntryLineInline, StockEntryDocumentInline)

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj and obj.status == StockEntryOperation.Status.CONFIRMED:
            fields.extend(field.name for field in StockEntryOperation._meta.fields)
        return tuple(dict.fromkeys(fields))

    def has_delete_permission(self, request, obj=None):
        return bool(obj and obj.status == StockEntryOperation.Status.DRAFT and super().has_delete_permission(request, obj))

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            if isinstance(instance, StockEntryDocument) and not instance.uploaded_by_id:
                instance.uploaded_by = request.user
            instance.save()
        for instance in formset.deleted_objects:
            instance.delete()
        formset.save_m2m()


class StockDeliveryLineInline(admin.TabularInline):
    model = StockDeliveryLine
    extra = 0
    readonly_fields = ("movement", "product_name", "product_sku", "product_unit", "product_brand_model", "created_at", "updated_at")

    def has_add_permission(self, request, obj=None):
        return not obj or obj.status == StockDelivery.Status.DRAFT

    def has_change_permission(self, request, obj=None):
        return not obj or obj.status == StockDelivery.Status.DRAFT

    def has_delete_permission(self, request, obj=None):
        return not obj or obj.status == StockDelivery.Status.DRAFT


@admin.register(StockDelivery)
class StockDeliveryAdmin(admin.ModelAdmin):
    list_display = ("number", "delivery_date", "recipient", "department", "status", "delivery_responsible", "completed_by")
    list_filter = ("status", "department", "branch", "delivery_date")
    search_fields = ("number", "recipient_name", "department_name", "recipient__username")
    readonly_fields = ("number", "recipient_name", "department_name", "created_by", "completed_by", "completed_at", "signed_document_uploaded_by", "signed_document_uploaded_at", "created_at", "updated_at")
    inlines = (StockDeliveryLineInline,)

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj and obj.status == StockDelivery.Status.COMPLETED:
            fields.extend(field.name for field in StockDelivery._meta.fields)
        return tuple(dict.fromkeys(fields))

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        return bool(obj and obj.status == StockDelivery.Status.DRAFT and super().has_delete_permission(request, obj))


class TicketStockUsageLineInline(admin.TabularInline):
    model = TicketStockUsageLine
    extra = 0
    readonly_fields = ("stock_movement", "product_name", "product_sku", "product_unit", "product_brand_model", "created_at")

    def has_add_permission(self, request, obj=None):
        return not obj or obj.status == TicketStockUsage.Status.DRAFT

    def has_change_permission(self, request, obj=None):
        return not obj or obj.status == TicketStockUsage.Status.DRAFT

    def has_delete_permission(self, request, obj=None):
        return not obj or obj.status == TicketStockUsage.Status.DRAFT


@admin.register(TicketStockUsage)
class TicketStockUsageAdmin(admin.ModelAdmin):
    list_display = ("ticket", "status", "registered_by", "registered_at", "confirmed_by", "confirmed_at")
    list_filter = ("status", "registered_at")
    search_fields = ("ticket__ticket_number", "ticket_number", "ticket__title")
    readonly_fields = ("ticket_number", "registered_by", "registered_at", "confirmed_by", "confirmed_at", "updated_at")
    inlines = (TicketStockUsageLineInline,)

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj and obj.status == TicketStockUsage.Status.CONFIRMED:
            fields.extend(field.name for field in TicketStockUsage._meta.fields)
        return tuple(dict.fromkeys(fields))

    def save_model(self, request, obj, form, change):
        if not obj.registered_by_id:
            obj.registered_by = request.user
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        return bool(obj and obj.status == TicketStockUsage.Status.DRAFT and super().has_delete_permission(request, obj))
