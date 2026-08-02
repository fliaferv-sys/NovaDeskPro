import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_alter_user_department"),
        ("deliveries", "0011_deliverybatchdocument"),
    ]

    operations = [
        migrations.AddField(
            model_name="assetcustodymovement",
            name="destination_branch",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="custody_movements_received", to="accounts.branch", verbose_name="Sede de destino"),
        ),
        migrations.AddField(
            model_name="deliverybatch",
            name="destination_branch",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="delivery_batches_received", to="accounts.branch", verbose_name="Sede de destino"),
        ),
    ]
