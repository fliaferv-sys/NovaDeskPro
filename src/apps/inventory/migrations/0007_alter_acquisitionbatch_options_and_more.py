import django.db.models.deletion
import django.utils.timezone
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0006_asset_acquisition_batch"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterModelOptions(name="acquisitionbatch", options={"ordering": ["-date", "-created_at"]}),
        migrations.AlterField(model_name="acquisitionbatch", name="code", field=models.CharField(max_length=50, unique=True, verbose_name="Código del lote")),
        migrations.AddField(model_name="acquisitionbatch", name="created_at", field=models.DateTimeField(default=django.utils.timezone.now, editable=False)),
        migrations.AddField(model_name="acquisitionbatch", name="expected_quantity", field=models.PositiveIntegerField(default=0, verbose_name="Cantidad esperada")),
        migrations.AddField(model_name="acquisitionbatch", name="received_by", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="acquisition_batches_received", to=settings.AUTH_USER_MODEL, verbose_name="Responsable de recepción")),
        migrations.AddField(model_name="acquisitionbatch", name="reference", field=models.CharField(blank=True, max_length=120, verbose_name="Orden de compra, contrato o referencia")),
        migrations.AddField(model_name="acquisitionbatch", name="status", field=models.CharField(choices=[("DRAFT", "Borrador"), ("PENDING_DOCUMENTS", "Pendiente de documentación"), ("VALIDATED", "Validado"), ("CLOSED", "Cerrado"), ("CANCELLED", "Cancelado")], default="DRAFT", max_length=25, verbose_name="Estado")),
        migrations.AddField(model_name="acquisitionbatch", name="supplier", field=models.CharField(blank=True, max_length=150, verbose_name="Proveedor")),
        migrations.AddField(model_name="acquisitionbatch", name="updated_at", field=models.DateTimeField(auto_now=True)),
        migrations.AlterField(model_name="acquisitionbatch", name="document", field=models.FileField(blank=True, help_text="Campo heredado. Use Documentos del lote para nuevas cargas.", upload_to="batches/", verbose_name="Documento principal anterior")),
        migrations.CreateModel(
            name="AcquisitionBatchDocument",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("document_type", models.CharField(choices=[("PURCHASE_ORDER", "Orden de compra o contrato"), ("INVOICE", "Factura"), ("DELIVERY_NOTE", "Remisión"), ("RECEIPT_REPORT", "Acta de recepción"), ("WARRANTY", "Garantía"), ("OTHER", "Otro documento")], max_length=30, verbose_name="Tipo de documento")),
                ("file", models.FileField(upload_to="inventory/acquisition_batches/%Y/%m/", verbose_name="Archivo")),
                ("observations", models.CharField(blank=True, max_length=255, verbose_name="Observaciones")),
                ("verified", models.BooleanField(default=False, help_text="Confirma que el archivo fue revisado y corresponde al lote.", verbose_name="Documento verificado")),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                ("batch", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="audit_documents", to="inventory.acquisitionbatch", verbose_name="Lote")),
                ("uploaded_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="uploaded_acquisition_documents", to=settings.AUTH_USER_MODEL, verbose_name="Cargado por")),
            ],
            options={"ordering": ["document_type", "-uploaded_at"]},
        ),
    ]
