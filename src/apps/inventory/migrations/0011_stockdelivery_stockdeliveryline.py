import django.db.models.deletion
import django.utils.timezone
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0009_seed_default_work_shifts'),
        ('core', '0005_businesssequence'),
        ('inventory', '0010_stockentryoperation_stockentrydocument_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name='StockDelivery',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('number', models.CharField(editable=False, max_length=30, unique=True, verbose_name='Número')),
                ('status', models.CharField(choices=[('DRAFT', 'Borrador'), ('PREPARED', 'Preparado'), ('PENDING_SIGNATURE', 'Pendiente de firma'), ('COMPLETED', 'Entregado'), ('CANCELLED', 'Cancelado')], default='DRAFT', max_length=20, verbose_name='Estado')),
                ('recipient_name', models.CharField(blank=True, max_length=180, verbose_name='Nombre histórico del receptor')),
                ('recipient_document', models.CharField(blank=True, max_length=50, verbose_name='Documento del receptor')),
                ('department_name', models.CharField(blank=True, max_length=180, verbose_name='Departamento histórico')),
                ('delivery_date', models.DateField(default=django.utils.timezone.localdate, verbose_name='Fecha')),
                ('observations', models.TextField(blank=True, verbose_name='Observaciones')),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('signed_document', models.FileField(blank=True, upload_to='inventory/stock_deliveries/signed/%Y/%m/', verbose_name='Acta firmada')),
                ('signed_document_uploaded_at', models.DateTimeField(blank=True, null=True)),
                ('signed_document_verified', models.BooleanField(default=False, verbose_name='Acta verificada')),
                ('created_at', models.DateTimeField(auto_now_add=True)), ('updated_at', models.DateTimeField(auto_now=True)),
                ('authorized_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='authorized_stock_deliveries', to=settings.AUTH_USER_MODEL)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='stock_deliveries', to='accounts.branch')),
                ('completed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='completed_stock_deliveries', to=settings.AUTH_USER_MODEL)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='created_stock_deliveries', to=settings.AUTH_USER_MODEL)),
                ('delivery_responsible', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='responsible_stock_deliveries', to=settings.AUTH_USER_MODEL)),
                ('department', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='stock_deliveries', to='core.department')),
                ('location', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='stock_deliveries', to='inventory.organizationallocation')),
                ('recipient', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='received_stock_deliveries', to=settings.AUTH_USER_MODEL)),
                ('signed_document_uploaded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='uploaded_stock_delivery_acts', to=settings.AUTH_USER_MODEL)),
            ], options={'verbose_name': 'Entrega de stock', 'verbose_name_plural': 'Entregas de stock', 'ordering': ['-delivery_date', '-created_at']},
        ),
        migrations.CreateModel(
            name='StockDeliveryLine',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('quantity', models.PositiveIntegerField(verbose_name='Cantidad')),
                ('product_name', models.CharField(blank=True, max_length=200, verbose_name='Producto histórico')),
                ('product_sku', models.CharField(blank=True, max_length=100, verbose_name='SKU histórico')),
                ('product_unit', models.CharField(blank=True, max_length=80, verbose_name='Unidad histórica')),
                ('product_brand_model', models.CharField(blank=True, max_length=300, verbose_name='Marca/modelo histórico')),
                ('created_at', models.DateTimeField(auto_now_add=True)), ('updated_at', models.DateTimeField(auto_now=True)),
                ('delivery', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='lines', to='inventory.stockdelivery')),
                ('movement', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='stock_delivery_line', to='inventory.stockmovement')),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='delivery_lines', to='inventory.stockproduct')),
                ('source_branch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='stock_delivery_lines', to='accounts.branch')),
                ('source_location', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='stock_delivery_lines', to='inventory.organizationallocation')),
            ], options={'ordering': ['created_at'], 'constraints': [models.CheckConstraint(condition=models.Q(('quantity__gt', 0)), name='stock_delivery_line_quantity_positive')]},
        ),
    ]
