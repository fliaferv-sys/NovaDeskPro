from decimal import Decimal

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("inventory", "0013_localize_standard_permission_names")]

    operations = [
        migrations.AddField(
            model_name="asset",
            name="disk_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("HDD", "HDD"),
                    ("SSD", "SSD"),
                    ("NVME", "NVMe"),
                    ("SSHD", "SSHD"),
                    ("OTHER", "Otro"),
                ],
                max_length=10,
                verbose_name="Tipo de disco",
            ),
        ),
        migrations.AddField(
            model_name="asset",
            name="ram_gb",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=8,
                null=True,
                validators=[django.core.validators.MinValueValidator(Decimal("0.01"))],
                verbose_name="Memoria RAM (GB)",
            ),
        ),
        migrations.AddField(
            model_name="asset",
            name="storage_capacity_gb",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=10,
                null=True,
                validators=[django.core.validators.MinValueValidator(Decimal("0.01"))],
                verbose_name="Capacidad de almacenamiento (GB)",
            ),
        ),
    ]
