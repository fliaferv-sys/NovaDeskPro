import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0009_seed_default_work_shifts'),
        ('inventory', '0011_stockdelivery_stockdeliveryline'),
        ('tickets', '0019_ticket_reactivation_requested_at'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.AddField(
            model_name='stockmovement', name='ticket',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='stock_movements', to='tickets.ticket', verbose_name='Ticket relacionado'),
        ),
        migrations.CreateModel(
            name='TicketStockUsage',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('ticket_number', models.CharField(blank=True, max_length=50, verbose_name='Número histórico del ticket')),
                ('observation', models.TextField(blank=True, verbose_name='Observación')),
                ('status', models.CharField(choices=[('DRAFT', 'Borrador'), ('CONFIRMED', 'Confirmado'), ('CANCELLED', 'Cancelado')], default='DRAFT', max_length=12, verbose_name='Estado')),
                ('registered_at', models.DateTimeField(auto_now_add=True)), ('confirmed_at', models.DateTimeField(blank=True, null=True)), ('updated_at', models.DateTimeField(auto_now=True)),
                ('confirmed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='confirmed_ticket_stock_usages', to=settings.AUTH_USER_MODEL)),
                ('registered_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='registered_ticket_stock_usages', to=settings.AUTH_USER_MODEL)),
                ('ticket', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='stock_usages', to='tickets.ticket')),
            ], options={'verbose_name': 'Consumo de stock por ticket', 'verbose_name_plural': 'Consumos de stock por tickets', 'ordering': ['-registered_at']},
        ),
        migrations.CreateModel(
            name='TicketStockUsageLine',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('quantity', models.PositiveIntegerField(verbose_name='Cantidad')),
                ('product_name', models.CharField(blank=True, max_length=200, verbose_name='Producto histórico')),
                ('product_sku', models.CharField(blank=True, max_length=100, verbose_name='SKU histórico')),
                ('product_unit', models.CharField(blank=True, max_length=80, verbose_name='Unidad histórica')),
                ('product_brand_model', models.CharField(blank=True, max_length=300, verbose_name='Marca/modelo histórico')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='ticket_usage_lines', to='inventory.stockproduct')),
                ('source_branch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='ticket_stock_usage_lines', to='accounts.branch')),
                ('source_location', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='ticket_stock_usage_lines', to='inventory.organizationallocation')),
                ('stock_movement', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='ticket_usage_line', to='inventory.stockmovement')),
                ('usage', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='lines', to='inventory.ticketstockusage')),
            ], options={'ordering': ['created_at'], 'constraints': [models.CheckConstraint(condition=models.Q(('quantity__gt', 0)), name='ticket_stock_usage_line_quantity_positive')]},
        ),
    ]
