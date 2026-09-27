# ==========================================================
# ADMINISTRACIÓN DEL INVENTARIO
# NOVADESK PRO — SPRINT 19
# ==========================================================

from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet


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
    Tool,
    ToolLoan,
    ToolLoanItem,
)
from .services.tool_loans import register_tool_loan, register_tool_return


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
    	"full_path_display",
    	"created_at",
    	"updated_at",
    )

    @admin.display(description="Ruta completa")
    def full_path_display(self, obj):
        if not obj:
            return "-"
        return obj.full_path

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
            "Especificaciones técnicas",
            {
                "fields": (
                    "operating_system",
                    "ram_gb",
                    "disk_type",
                    "storage_capacity_gb",
                    "current_ip",
                    "mac_address",
                ),
            },
        ),
        (
            "Estado operativo y conectividad",
            {
                "fields": (
                    "operational_status",
                    "connection_status",
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
    readonly_fields = ("number", "status", "created_by", "confirmed_by", "confirmed_at", "created_at", "updated_at")
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
    readonly_fields = ("number", "status", "recipient_name", "department_name", "created_by", "completed_by", "completed_at", "signed_document_uploaded_by", "signed_document_uploaded_at", "created_at", "updated_at")
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
    readonly_fields = ("ticket_number", "status", "registered_by", "registered_at", "confirmed_by", "confirmed_at", "updated_at")
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


# ==========================================================
# HERRAMIENTAS DTI
# ==========================================================

class ToolAdminForm(forms.ModelForm):
    class Meta:
        model = Tool
        fields = "__all__"

    def clean_status(self):
        status = self.cleaned_data.get("status")
        if (
            self.instance.pk
            and status == Tool.Status.AVAILABLE
            and self.instance.loan_items.filter(
                loan__status=ToolLoan.Status.ACTIVE, returned_at__isnull=True
            ).exists()
        ):
            raise ValidationError(
                "No puede marcarse como disponible una herramienta que "
                "pertenece a un préstamo activo."
            )
        return status


@admin.register(Tool)
class ToolAdmin(admin.ModelAdmin):
    form = ToolAdminForm
    list_display = (
        "code",
        "name",
        "category",
        "brand",
        "model",
        "branch",
        "organizational_location",
        "status",
        "is_active",
    )
    list_filter = (
        "status",
        "is_active",
        "category",
        "branch",
        "organizational_location",
    )
    search_fields = (
        "code",
        "name",
        "category",
        "brand",
        "model",
        "serial_number",
        "branch__code",
        "branch__name",
        "organizational_location__code",
        "organizational_location__name",
    )
    list_select_related = (
        "branch",
        "organizational_location",
    )
    autocomplete_fields = (
        "branch",
        "organizational_location",
    )
    readonly_fields = (
        "code",
        "created_at",
        "updated_at",
    )
    ordering = ("name", "code")


class ToolLoanItemAdminForm(forms.ModelForm):
    class Meta:
        model = ToolLoanItem
        fields = "__all__"

    def __init__(self, *args, parent_loan=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent_loan = parent_loan

    def clean_tool(self):
        tool = self.cleaned_data.get("tool")
        loan = self.parent_loan
        if not tool or not loan:
            return tool

        if self.instance.pk and self.instance.tool_id == tool.pk:
            return tool

        duplicate = False
        if loan.pk and not loan._state.adding:
            duplicate = (
                ToolLoanItem.objects
                .filter(loan=loan, tool=tool)
                .exclude(pk=self.instance.pk)
                .exists()
            )
        if duplicate:
            raise ValidationError(
                f"La herramienta {tool.code} ya está incluida en este préstamo."
            )

        if loan.status == ToolLoan.Status.ACTIVE:
            candidate = ToolLoanItem(loan=loan, tool=tool)
            try:
                candidate.validate_for_active_loan()
            except ValidationError as error:
                raise ValidationError(error.message_dict["tool"]) from error

        return tool


class ToolLoanItemInlineFormSet(BaseInlineFormSet):
    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs["parent_loan"] = self.instance
        return kwargs

    def clean(self):
        seen_tools = set()
        for form in self.forms:
            if not hasattr(form, "cleaned_data") or form.cleaned_data.get("DELETE"):
                continue

            tool = form.cleaned_data.get("tool")
            if not tool:
                continue

            if tool.pk in seen_tools:
                form.add_error(
                    "tool",
                    f"La herramienta {tool.code} ya está incluida en este préstamo.",
                )
            else:
                seen_tools.add(tool.pk)

        super().clean()


class ToolLoanItemInline(admin.TabularInline):
    model = ToolLoanItem
    form = ToolLoanItemAdminForm
    formset = ToolLoanItemInlineFormSet
    verbose_name = "Herramienta prestada"
    verbose_name_plural = "HERRAMIENTAS PRESTADAS"
    extra = 1
    autocomplete_fields = ("tool",)
    readonly_fields = ("created_at", "returned_at", "received_by", "return_observations")
    can_delete = False


class ToolLoanAdminForm(forms.ModelForm):
    class Meta:
        model = ToolLoan
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get("status") == ToolLoan.Status.RETURNED
            and not cleaned_data.get("received_by")
        ):
            self.add_error(
                "received_by",
                "Debe indicar quién recibe la devolución.",
            )
        return cleaned_data


@admin.register(ToolLoan)
class ToolLoanAdmin(admin.ModelAdmin):
    form = ToolLoanAdminForm
    list_display = (
        "number",
        "borrower",
        "tools_display",
        "loaned_at",
        "expected_return_at",
        "status",
        "overdue_display",
        "returned_at",
    )
    list_filter = (
        "status",
        "loaned_at",
        "expected_return_at",
        "returned_at",
        "items__tool__branch",
    )
    search_fields = (
        "number",
        "items__tool__code",
        "items__tool__name",
        "items__tool__serial_number",
        "borrower_name",
        "borrower__username",
        "borrower__first_name",
        "borrower__last_name",
        "borrower__email",
        "purpose",
    )
    list_select_related = (
        "borrower",
        "delivered_by",
        "received_by",
    )
    autocomplete_fields = (
        "borrower",
        "delivered_by",
        "received_by",
    )
    readonly_fields = (
        "number",
        "borrower_name",
        "overdue_display",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            "PRÉSTAMO",
            {
                "fields": (
                    "number",
                    "borrower",
                    "borrower_name",
                    "delivered_by",
                    "loaned_at",
                    "expected_return_at",
                    "purpose",
                    "observations",
                ),
            },
        ),
        (
            "DEVOLUCIÓN",
            {
                "fields": (
                    "returned_at",
                    "received_by",
                    "return_observations",
                    "status",
                    "overdue_display",
                ),
            },
        ),
        (
            "AUDITORÍA",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )
    ordering = ("-loaned_at", "-created_at")
    inlines = (ToolLoanItemInline,)

    def save_model(self, request, obj, form, change):
        obj._tool_loan_return_data = None
        obj._previously_loaned_tool_ids = set()

        if change:
            previous = ToolLoan.objects.get(pk=obj.pk)
            if previous.status == ToolLoan.Status.ACTIVE:
                obj._previously_loaned_tool_ids = set(
                    previous.items.values_list("tool_id", flat=True)
                )

            if (
                previous.status == ToolLoan.Status.ACTIVE
                and obj.status == ToolLoan.Status.RETURNED
            ):
                obj._tool_loan_return_data = {
                    "received_by": obj.received_by,
                    "return_observations": obj.return_observations,
                    "returned_at": obj.returned_at,
                }
                obj.status = ToolLoan.Status.ACTIVE
                obj.received_by = previous.received_by
                obj.returned_at = previous.returned_at
                obj.return_observations = previous.return_observations

        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        obj = form.instance
        return_data = getattr(obj, "_tool_loan_return_data", None)

        if return_data:
            register_tool_return(loan=obj, **return_data)
        elif obj.status == ToolLoan.Status.ACTIVE:
            register_tool_loan(
                loan=obj,
                already_loaned_tool_ids=getattr(
                    obj, "_previously_loaned_tool_ids", set()
                ),
            )

        obj.refresh_from_db()

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("items__tool").distinct()

    @admin.display(description="Herramientas")
    def tools_display(self, obj):
        return ", ".join(item.tool.code for item in obj.items.all()) or "-"

    @admin.display(description="Vencido", boolean=True)
    def overdue_display(self, obj):
        if not obj:
            return False
        return obj.is_overdue
