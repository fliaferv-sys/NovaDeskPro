from django.contrib import admin
from django.db.models import IntegerField, Sum
from django.db.models.functions import Coalesce
from django.utils.html import format_html

from .models import (
    Consumable,
    ConsumableCompatibility,
    MeterReading,
    PrintingContract,
    PrintingDevice,
    PrintingDeviceNetworkDetection,
    StockMovement,
    MaintenanceRecord,
)


@admin.register(PrintingDevice)
class PrintingDeviceAdmin(admin.ModelAdmin):
    list_display = (
        "asset",
        "device_type",
        "technology",
        "color_mode",
        "ownership_type",
        "is_active",
    )
    
    list_filter = (
        "device_type",
        "technology",
        "color_mode",
        "ownership_type",
        "supports_duplex",
        "supports_network",
        "is_active",
    )
    
    search_fields = (
        "asset__internal_code",
        "asset__brand",
        "asset__model",
        "asset__serial_number",
    )
    
    autocomplete_fields = ("asset", "responsible_user")
    
    readonly_fields = ("created_at", "updated_at")
    
    fieldsets = (
        (
            "Identificación",
            {
                "fields": (
                    "asset",
                    "device_type",
                    "technology",
                    "color_mode",
                    "ownership_type",
                    "is_active",
                )
            },
        ),
        (
            "Capacidades",
            {
                "fields": (
                    "supports_duplex",
                    "supports_network",
                    "supports_scan",
                    "supports_copy",
                    "supports_fax",
                )
            },
        ),
        (
            "Configuración de red",
            {
                "fields": (
                    "web_interface_url",
                    "network_port",
                    "snmp_enabled",
                    "snmp_community",
                )
            },
        ),
        (
            "Control",
            {
                "fields": (
                    "monthly_print_limit",
                    "responsible_user",
                )
            },
        ),
        (
            "Información adicional",
            {
                "fields": ("notes",),
            },
        ),
        (
            "Auditoría",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )
@admin.register(PrintingDeviceNetworkDetection)
class PrintingDeviceNetworkDetectionAdmin(admin.ModelAdmin):
    list_display = (
        "printing_device",
        "detected_ip",
        "detected_mac",
        "switch_name",
        "switch_port",
        "vlan",
        "detected_location",
        "is_current",
        "detected_at",
    )

    list_filter = (
        "is_current",
        "vlan",
        "detection_source",
        "detected_at",
    )

    search_fields = (
        "printing_device__asset__internal_code",
        "printing_device__asset__brand",
        "printing_device__asset__model",
        "detected_ip",
        "detected_mac",
        "switch_name",
        "switch_port",
        "vlan",
        "detected_location",
    )

    autocomplete_fields = (
        "printing_device",
    )

    readonly_fields = (
        "detected_at",
    )

    ordering = (
        "-detected_at",
    )

    fieldsets = (
        (
            "Equipo detectado",
            {
                "fields": (
                    "printing_device",
                    "detected_ip",
                    "detected_mac",
                )
            },
        ),
        (
            "Ubicación en la red",
            {
                "fields": (
                    "switch_name",
                    "switch_port",
                    "vlan",
                    "detected_location",
                    "detection_source",
                )
            },
        ),
        (
            "Estado de la detección",
            {
                "fields": (
                    "is_current",
                    "detected_at",
                    "notes",
                )
            },
        ),
    )

@admin.register(PrintingContract)
class PrintingContractAdmin(admin.ModelAdmin):
    list_display = (
        "contract_number",
        "provider",
        "contract_type",
        "start_date",
        "end_date",
        "monthly_cost",
        "status",
        "is_active",
    )
    
    list_filter = (
        "contract_type",
        "status",
        "is_active",
        "start_date",
        "end_date",
    )
    
    search_fields = (
        "contract_number",
        "provider",
        "contact_name",
        "contact_email",
    )
    
    filter_horizontal = ("devices",)
    
    readonly_fields = ("created_at", "updated_at")
    
    fieldsets = (
        (
            "Identificación",
            {
                "fields": (
                    "contract_number",
                    "contract_type",
                    "provider",
                    "status",
                    "is_active",
                )
            },
        ),
        (
            "Datos del contrato",
            {
                "fields": (
                    "devices",
                    "start_date",
                    "end_date",
                    "monthly_cost",
                )
            },
        ),
        (
            "Límites de impresión",
            {
                "fields": (
                    "included_prints_bw",
                    "included_prints_color",
                    "excess_cost_bw",
                    "excess_cost_color",
                )
            },
        ),
        (
            "SLA",
            {
                "fields": (
                    "response_time_hours",
                    "resolution_time_hours",
                )
            },
        ),
        (
            "Contacto",
            {
                "fields": (
                    "contact_name",
                    "contact_phone",
                    "contact_email",
                )
            },
        ),
        (
            "Información adicional",
            {
                "fields": ("notes",),
            },
        ),
        (
            "Auditoría",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )
class StockStatusFilter(admin.SimpleListFilter):
    title = "Estado del stock"
    parameter_name = "stock_status"

    def lookups(self, request, _model_admin):
        return (
            ("out", "Sin stock"),
            ("low", "Stock bajo"),
            ("normal", "Disponible"),
            ("over", "Sobrestock"),
        )

    def queryset(self, request, queryset):
        selected = self.value()

        if not selected:
            return queryset

        matched_ids = []

        for consumable in queryset:
            stock = consumable.current_stock

            if selected == "out" and stock <= 0:
                matched_ids.append(consumable.pk)

            elif (
                selected == "low"
                and stock > 0
                and stock <= consumable.minimum_stock
            ):
                matched_ids.append(consumable.pk)

            elif (
                selected == "over"
                and consumable.maximum_stock is not None
                and stock > consumable.maximum_stock
            ):
                matched_ids.append(consumable.pk)

            elif (
                selected == "normal"
                and stock > consumable.minimum_stock
                and (
                    consumable.maximum_stock is None
                    or stock <= consumable.maximum_stock
                )
            ):
                matched_ids.append(consumable.pk)

        return queryset.filter(pk__in=matched_ids)

@admin.register(Consumable)
class ConsumableAdmin(admin.ModelAdmin):
    list_display = (
        "reference_code",
        "name",
        "consumable_type",
        "manufacturer",
        "model",
        "color",
        "stock_actual",
        "minimum_stock",
        "maximum_stock",
        "estado_stock",
        "faltante_minimo",
        "reposicion_sugerida",
        "costo_reposicion",
        "is_active",
    )

    list_filter = (
        StockStatusFilter,
        "consumable_type",
        "color",
        "manufacturer",
        "is_active",
    )

    search_fields = (
        "name",
        "reference_code",
        "manufacturer",
        "model",
    )

    ordering = (
        "name",
        "manufacturer",
        "model",
    )

    fieldsets = (
        (
            "Identificación",
            {
                "fields": (
                    "name",
                    "consumable_type",
                    "reference_code",
                    "manufacturer",
                    "model",
                    "color",
                    "is_active",
                )
            },
        ),
        (
            "Control de existencias",
            {
                "fields": (
                    "initial_stock",
                    "minimum_stock",
                    "maximum_stock",
                    "estimated_yield_pages",
                )
            },
        ),
        (
            "Información comercial",
            {
                "fields": (
                    "unit_price",
                )
            },
        ),
        (
            "Información de reposición",
            {
                "fields": (
                    "faltante_minimo",
                    "reposicion_sugerida",
                    "costo_reposicion",
                )
            },
        ),
        (
            "Información adicional",
            {
                "fields": (
                    "notes",
                )
            },
        ),
        (
            "Auditoría",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    readonly_fields = (
        "created_at",
        "updated_at",
        "faltante_minimo",
        "reposicion_sugerida",
        "costo_reposicion",
    )

    @admin.display(
        description="Stock actual",
        ordering="initial_stock",
    )
    def stock_actual(self, obj):
        stock = obj.current_stock

        if stock <= 0:
            return format_html(
                '<strong style="color:#dc3545;">{}</strong>',
                str(stock),
            )

        if stock <= obj.minimum_stock:
            return format_html(
                '<strong style="color:#fd7e14;">{}</strong>',
                str(stock),
            )

        return format_html(
            '<strong style="color:#198754;">{}</strong>',
            str(stock),
        )

    @admin.display(description="Estado del stock")
    def estado_stock(self, obj):
        stock = obj.current_stock

        if stock <= 0:
            return format_html(
                '<strong style="color:#dc3545;">{}</strong>',
                "SIN STOCK"
            )

        if stock <= obj.minimum_stock:
            return format_html(
                '<strong style="color:#fd7e14;">{}</strong>',
                "STOCK BAJO"
            )

        if (
            obj.maximum_stock is not None
            and stock > obj.maximum_stock
        ):
            return format_html(
                '<strong style="color:#6f42c1;">{}</strong>',
                "SOBRESTOCK"
            )

        return format_html(
            '<strong style="color:#198754;">{}</strong>',
            "DISPONIBLE"
        )

    @admin.display(description="Faltante mínimo")
    def faltante_minimo(self, obj):
        return obj.quantity_to_minimum

    @admin.display(description="Reposición sugerida")
    def reposicion_sugerida(self, obj):
        return obj.suggested_reorder_quantity

    @admin.display(description="Costo reposición")
    def costo_reposicion(self, obj):
        return f"${obj.estimated_reorder_cost:,.2f}"


@admin.register(ConsumableCompatibility)
class ConsumableCompatibilityAdmin(admin.ModelAdmin):
    list_display = (
        "printing_device",
        "consumable",
        "compatibility_type",
        "is_primary",
        "is_active",
    )

    list_filter = (
        "compatibility_type",
        "is_primary",
        "is_active",
    )

    search_fields = (
        "printing_device__asset__internal_code",
        "printing_device__asset__brand",
        "printing_device__asset__model",
        "printing_device__asset__serial_number",
        "consumable__name",
        "consumable__reference_code",
        "consumable__manufacturer",
        "consumable__model",
    )

    autocomplete_fields = (
        "printing_device",
        "consumable",
    )

    fieldsets = (
        (
            "Compatibilidad",
            {
                "fields": (
                    "printing_device",
                    "consumable",
                    "compatibility_type",
                    "is_primary",
                    "is_active",
                )
            },
        ),
        (
            "Información adicional",
            {
                "fields": (
                    "notes",
                )
            },
        ),
        (
            "Auditoría",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        "movement_date",
        "consumable",
        "movement_type",
        "quantity",
        "printing_device",
        "performed_by",
        "stock_resultante",
        "document_reference",
    )

    list_filter = (
        "movement_type",
        "movement_date",
        "consumable__consumable_type",
        "consumable__manufacturer",
    )

    search_fields = (
        "consumable__reference_code",
        "consumable__name",
        "consumable__manufacturer",
        "consumable__model",
        "printing_device__asset__internal_code",
        "printing_device__asset__serial_number",
        "printing_device__asset__brand",
        "printing_device__asset__model",
        "performed_by__username",
        "performed_by__first_name",
        "performed_by__last_name",
        "document_reference",
        "notes",
    )

    autocomplete_fields = (
        "consumable",
        "printing_device",
    )

    ordering = (
        "-movement_date",
        "-created_at",
    )

    date_hierarchy = "movement_date"

    actions = ['exportar_movimientos']

    fieldsets = (
        (
            "Movimiento",
            {
                "fields": (
                    "consumable",
                    "movement_type",
                    "quantity",
                    "movement_date",
                )
            },
        ),
        (
            "Destino o utilización",
            {
                "fields": (
                    "printing_device",
                    "source_location",
                    "destination_location",
                )
            },
        ),
        (
            "Información económica y documental",
            {
                "fields": (
                    "unit_cost",
                    "document_reference",
                )
            },
        ),
        (
            "Registro",
            {
                "fields": (
                    "performed_by",
                    "notes",
                )
            },
        ),
        (
            "Auditoría",
            {
                "fields": (
                    "created_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    readonly_fields = (
        "performed_by",
        "created_at",
    )

    def save_model(self, request, obj, form, change):
        if not obj.performed_by_id:
            obj.performed_by = request.user

        obj.full_clean()
        super().save_model(request, obj, form, change)

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return (
                "consumable",
                "movement_type",
                "quantity",
                "printing_device",
                "performed_by",
                "movement_date",
                "unit_cost",
                "source_location",
                "destination_location",
                "document_reference",
                "notes",
                "created_at",
            )

        return (
            "performed_by",
            "created_at",
        )

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(
        description="Stock resultante",
    )
    def stock_resultante(self, obj):
        # Calcular el stock resultante después de este movimiento
        movements = StockMovement.objects.filter(
            consumable=obj.consumable,
            created_at__lte=obj.created_at
        ).order_by('created_at')
        
        stock = obj.consumable.initial_stock
        for mov in movements:
            if mov.movement_type in [
                StockMovement.MovementType.ENTRY,
                StockMovement.MovementType.RETURN,
                StockMovement.MovementType.POSITIVE_ADJUSTMENT,
            ]:
                stock += mov.quantity
            else:
                stock -= mov.quantity
            if mov.id == obj.id:
                break
        return stock

    def exportar_movimientos(self, request, queryset):
        import csv
        from django.http import HttpResponse
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="movimientos_stock.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Fecha', 'Consumible', 'Tipo', 'Cantidad', 'Equipo', 'Usuario', 'Documento'])
        
        for movimiento in queryset:
            writer.writerow([
                movimiento.movement_date,
                str(movimiento.consumable),
                movimiento.get_movement_type_display(),
                movimiento.quantity,
                str(movimiento.printing_device) if movimiento.printing_device else '',
                str(movimiento.performed_by),
                movimiento.document_reference
            ])
        
        return response
    
    exportar_movimientos.short_description = "📥 Exportar movimientos seleccionados"


@admin.register(MeterReading)
class MeterReadingAdmin(admin.ModelAdmin):
    list_display = (
        "reading_date",
        "printing_device",
        "contrato_vigente",
        "consumo_bn",
        "excedente_bn",
        "consumo_color",
        "excedente_color",
        "costo_excedente",
        "costo_estimado",
        "registered_by",
    )

    list_filter = (
        "reading_date",
        "printing_device",
        "registered_by",
    )

    search_fields = (
        "printing_device__asset__internal_code",
        "printing_device__asset__brand",
        "printing_device__asset__model",
        "printing_device__asset__serial_number",
        "registered_by__username",
        "registered_by__first_name",
        "registered_by__last_name",
        "notes",
    )

    autocomplete_fields = (
        "printing_device",
        "registered_by",
    )

    ordering = (
        "-reading_date",
        "-created_at",
    )

    date_hierarchy = "reading_date"

    fieldsets = (
        (
            "Lectura de contadores",
            {
                "fields": (
                    "printing_device",
                    "reading_date",
                    "total_counter",
                    "black_white_counter",
                    "color_counter",
                    "copy_counter",
                    "scan_counter",
                )
            },
        ),
        (
            "Consumos y excedentes",
            {
                "fields": (
                    "consumo_total",
                    "consumo_bn",
                    "excedente_bn",
                    "consumo_color",
                    "excedente_color",
                )
            },
        ),
        (
            "Información de costos",
            {
                "fields": (
                    "contrato_vigente",
                    "costo_excedente",
                    "costo_estimado",
                )
            },
        ),
        (
            "Información adicional",
            {
                "fields": (
                    "registered_by",
                    "notes",
                )
            },
        ),
        (
            "Auditoría",
            {
                "fields": ("created_at",),
                "classes": ("collapse",),
            },
        ),
    )

    readonly_fields = (
        "registered_by",
        "created_at",
        "consumo_total",
        "consumo_bn",
        "consumo_color",
        "contrato_vigente",
        "excedente_bn",
        "excedente_color",
        "costo_excedente",
        "costo_estimado",
    )

    @admin.display(description="Consumo total")
    def consumo_total(self, obj):
        return obj.total_consumption

    @admin.display(description="Consumo B/N")
    def consumo_bn(self, obj):
        return obj.black_white_consumption

    @admin.display(description="Consumo color")
    def consumo_color(self, obj):
        return obj.color_consumption

    @admin.display(description="Contrato")
    def contrato_vigente(self, obj):
        contract = obj.active_contract

        if not contract:
            return "Sin contrato"

        return contract.contract_number

    @admin.display(description="Excedente B/N")
    def excedente_bn(self, obj):
        return obj.excess_black_white

    @admin.display(description="Excedente color")
    def excedente_color(self, obj):
        return obj.excess_color

    @admin.display(description="Costo excedente")
    def costo_excedente(self, obj):
        return f"${obj.total_excess_cost:,.2f}"

    @admin.display(description="Costo estimado")
    def costo_estimado(self, obj):
        return f"${obj.estimated_period_cost:,.2f}"

    def save_model(self, request, obj, form, change):
        if not obj.registered_by_id:
            obj.registered_by = request.user

        obj.full_clean()
        super().save_model(request, obj, form, change)

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return (
                "printing_device",
                "reading_date",
                "total_counter",
                "black_white_counter",
                "color_counter",
                "copy_counter",
                "scan_counter",
                "registered_by",
                "created_at",
                "consumo_total",
                "consumo_bn",
                "consumo_color",
                "contrato_vigente",
                "excedente_bn",
                "excedente_color",
                "costo_excedente",
                "costo_estimado",
            )

        return (
            "registered_by",
            "created_at",
            "consumo_total",
            "consumo_bn",
            "consumo_color",
            "contrato_vigente",
            "excedente_bn",
            "excedente_color",
            "costo_excedente",
            "costo_estimado",
        )

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MaintenanceRecord)
class MaintenanceRecordAdmin(admin.ModelAdmin):
    list_display = (
        "scheduled_date",
        "printing_device",
        "maintenance_type",
        "status",
        "technician_name",
        "costo_total",
        "performed_date",
    )

    list_filter = (
        "maintenance_type",
        "status",
        "performed_date",
        "scheduled_date",
    )

    search_fields = (
        "printing_device__asset__internal_code",
        "printing_device__asset__brand",
        "printing_device__asset__model",
        "printing_device__asset__serial_number",
        "technician_name",
        "provider",
        "description",
        "diagnosis",
        "solution",
        "notes",
    )

    autocomplete_fields = (
        "printing_device",
        "registered_by",
    )

    ordering = (
        "-performed_date",
        "-scheduled_date",
        "-created_at",
    )

    date_hierarchy = "performed_date"

    fieldsets = (
        (
            "Información del mantenimiento",
            {
                "fields": (
                    "printing_device",
                    "maintenance_type",
                    "status",
                    "scheduled_date",
                    "performed_date",
                )
            },
        ),
        (
            "Técnico y proveedor",
            {
                "fields": (
                    "technician_name",
                    "provider",
                )
            },
        ),
        (
            "Detalles del trabajo",
            {
                "fields": (
                    "description",
                    "diagnosis",
                    "solution",
                    "replaced_parts",
                    "meter_counter",
                )
            },
        ),
        (
            "Costos",
            {
                "fields": (
                    "labor_cost",
                    "parts_cost",
                    "costo_total",
                )
            },
        ),
        (
            "Programación futura",
            {
                "fields": (
                    "next_maintenance_date",
                )
            },
        ),
        (
            "Información adicional",
            {
                "fields": (
                    "registered_by",
                    "notes",
                )
            },
        ),
        (
            "Auditoría",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    readonly_fields = (
        "registered_by",
        "created_at",
        "updated_at",
        "costo_total",
    )

    @admin.display(description="Costo total")
    def costo_total(self, obj):
        return f"${obj.total_cost:,.2f}"

    def save_model(self, request, obj, form, change):
        if not obj.registered_by_id:
            obj.registered_by = request.user

        obj.full_clean()
        super().save_model(request, obj, form, change)

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return (
                "printing_device",
                "maintenance_type",
                "scheduled_date",
                "performed_date",
                "technician_name",
                "provider",
                "description",
                "diagnosis",
                "solution",
                "replaced_parts",
                "meter_counter",
                "labor_cost",
                "parts_cost",
                "registered_by",
                "notes",
                "created_at",
                "updated_at",
                "costo_total",
            )

        return (
            "registered_by",
            "created_at",
            "updated_at",
            "costo_total",
        )

    def has_delete_permission(self, request, obj=None):
        return False
