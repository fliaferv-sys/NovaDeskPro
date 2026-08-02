from django.contrib import admin

from .models import AssetCustodyMovement, DeliveryBatch, DeliveryBatchDocument


class DeliveryBatchDocumentInline(admin.TabularInline):
    model = DeliveryBatchDocument
    extra = 0
    readonly_fields = ("uploaded_by", "uploaded_at")


@admin.register(DeliveryBatch)
class DeliveryBatchAdmin(admin.ModelAdmin):
    list_display = (
        "batch_number",
        "status",
        "recipient",
        "delivery_responsible",
        "department",
        "delivery_date",
        "asset_count",
    )
    list_filter = ("status", "delivery_date", "department")
    search_fields = (
        "batch_number",
        "recipient__first_name",
        "recipient__last_name",
        "department",
        "location",
    )
    readonly_fields = ("batch_number", "created_at", "updated_at")
    inlines = (DeliveryBatchDocumentInline,)


@admin.register(AssetCustodyMovement)
class AssetCustodyMovementAdmin(admin.ModelAdmin):

    list_display = (
        "movement_number",
        "asset",
        "movement_type",
        "status",
        "previous_custodian",
        "recipient",
        "delivery_responsible",
        "movement_date",
    )

    list_filter = (
        "movement_type",
        "status",
        "movement_date",
        "department",
    )

    search_fields = (
        "movement_number",
        "asset__internal_code",
        "asset__serial_number",
        "previous_custodian__first_name",
        "previous_custodian__last_name",
        "recipient__first_name",
        "recipient__last_name",
        "delivery_responsible__first_name",
        "delivery_responsible__last_name",
        "authorizing_director__first_name",
        "authorizing_director__last_name",
        "department",
        "location",
    )

    readonly_fields = (
        "movement_number",
        "created_at",
        "updated_at",
    )

    ordering = (
        "-movement_date",
        "-created_at",
    )

    fieldsets = (
        (
            "Movimiento",
            {
                "fields": (
                    "movement_number",
                    "movement_type",
                    "status",
                    "movement_date",
                ),
            },
        ),
        (
            "Activo y custodia",
            {
                "fields": (
                    "asset",
                    "previous_custodian",
                    "recipient",
                    "delivery_responsible",
                    "authorizing_director",
                ),
            },
        ),
        (
            "Destino",
            {
                "fields": (
                    "department",
                    "location",
                ),
            },
        ),
        (
            "Detalle de entrega",
            {
                "fields": (
                    "accessories",
                    "asset_condition",
                    "observations",
                ),
            },
        ),
        (
            "Firmas y documentación",
            {
                "fields": (
                    "director_signature",
                    "responsible_signature",
                    "recipient_signature",
                    "signed_document",
                ),
            },
        ),
        (
            "Auditoría",
            {
                "fields": (
                    "created_by",
                    "created_at",
                    "updated_at",
                ),
            },
        ),
    )
