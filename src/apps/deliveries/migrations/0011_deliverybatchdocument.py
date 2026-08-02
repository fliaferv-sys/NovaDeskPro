import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("deliveries", "0010_deliverybatch_assetcustodymovement_delivery_batch"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DeliveryBatchDocument",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("document_type", models.CharField(choices=[("INTERNAL_DELIVERY", "Acta interna de entrega DTI firmada"), ("PATRIMONIAL_MOVEMENT", "Movimiento patrimonial firmado"), ("OTHER", "Otro documento")], max_length=30, verbose_name="Tipo de documento")),
                ("file", models.FileField(upload_to="deliveries/batches/audit_documents/%Y/%m/", verbose_name="Archivo")),
                ("observations", models.CharField(blank=True, max_length=255, verbose_name="Observaciones")),
                ("signatures_verified", models.BooleanField(default=False, help_text="Confirma que el documento contiene las firmas requeridas.", verbose_name="Firmas verificadas")),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                ("delivery_batch", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="audit_documents", to="deliveries.deliverybatch", verbose_name="Acta agrupada")),
                ("uploaded_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="uploaded_delivery_batch_documents", to=settings.AUTH_USER_MODEL, verbose_name="Cargado por")),
            ],
            options={
                "ordering": ["document_type", "-uploaded_at"],
                "constraints": [models.UniqueConstraint(condition=models.Q(document_type__in=["INTERNAL_DELIVERY", "PATRIMONIAL_MOVEMENT"]), fields=("delivery_batch", "document_type"), name="unique_required_document_per_delivery_batch")],
            },
        ),
    ]
