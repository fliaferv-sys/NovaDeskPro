import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("inventory", "0009_alter_stockmovement_reason"),
    ]

    operations = [
        migrations.CreateModel(
            name="StockEntryOperation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("number", models.CharField(editable=False, max_length=30, unique=True, verbose_name="Número")),
                ("reason", models.CharField(choices=[("PURCHASE", "Compra"), ("RETURN", "Devolución"), ("INITIAL_ENTRY", "Ingreso inicial"), ("DELIVERY", "Entrega"), ("REPAIR", "Uso en reparación"), ("CONSUMPTION", "Consumo"), ("WRITE_OFF", "Baja"), ("ADJUSTMENT", "Ajuste"), ("POSITIVE_ADJUSTMENT", "Ajuste positivo"), ("NEGATIVE_ADJUSTMENT", "Ajuste negativo"), ("TRANSFER", "Transferencia"), ("OTHER", "Otro")], max_length=20, verbose_name="Motivo")),
                ("entry_date", models.DateField(default=django.utils.timezone.localdate, verbose_name="Fecha")),
                ("supplier", models.CharField(blank=True, max_length=150, verbose_name="Proveedor")),
                ("invoice_number", models.CharField(blank=True, max_length=100, verbose_name="Número de factura")),
                ("purchase_order_number", models.CharField(blank=True, max_length=100, verbose_name="Orden de compra")),
                ("delivery_note_number", models.CharField(blank=True, max_length=100, verbose_name="Número de remisión")),
                ("external_reference", models.CharField(blank=True, max_length=120, verbose_name="Referencia externa")),
                ("observations", models.TextField(blank=True, verbose_name="Observaciones")),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("status", models.CharField(choices=[("DRAFT", "Borrador"), ("CONFIRMED", "Confirmado"), ("CANCELLED", "Cancelado")], default="DRAFT", max_length=12, verbose_name="Estado")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("confirmed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="confirmed_stock_entries", to=settings.AUTH_USER_MODEL)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_stock_entries", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "Entrada documentada de stock", "verbose_name_plural": "Entradas documentadas de stock", "ordering": ["-entry_date", "-created_at"]},
        ),
        migrations.CreateModel(
            name="StockEntryDocument",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("document_type", models.CharField(choices=[("PURCHASE_ORDER", "Orden de compra"), ("INVOICE", "Factura"), ("DELIVERY_NOTE", "Remisión"), ("REPORT", "Acta"), ("RECEIPT", "Nota de recepción"), ("VOUCHER", "Comprobante"), ("OTHER", "Otro")], max_length=30, verbose_name="Tipo")),
                ("file", models.FileField(upload_to="inventory/stock_entries/%Y/%m/", verbose_name="Archivo")),
                ("description", models.CharField(blank=True, max_length=180, verbose_name="Nombre o descripción")),
                ("observation", models.TextField(blank=True, verbose_name="Observación")),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                ("verified", models.BooleanField(default=False, verbose_name="Verificado")),
                ("entry", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="documents", to="inventory.stockentryoperation")),
                ("uploaded_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="uploaded_stock_entry_documents", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["document_type", "-uploaded_at"]},
        ),
        migrations.CreateModel(
            name="StockEntryLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("quantity", models.PositiveIntegerField(verbose_name="Cantidad")),
                ("observation", models.TextField(blank=True, verbose_name="Observación")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("branch", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="stock_entry_lines", to="accounts.branch")),
                ("entry", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="lines", to="inventory.stockentryoperation")),
                ("movement", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="documented_entry_line", to="inventory.stockmovement")),
                ("organizational_location", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="stock_entry_lines", to="inventory.organizationallocation")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="documented_entry_lines", to="inventory.stockproduct")),
            ],
            options={"ordering": ["created_at"]},
        ),
        migrations.AddConstraint(model_name="stockentryline", constraint=models.CheckConstraint(condition=models.Q(("quantity__gt", 0)), name="stock_entry_line_quantity_positive")),
    ]
