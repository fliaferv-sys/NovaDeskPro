from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("printing", "0014_alter_printingdevice_options_printingdevice_branch_and_more"),
    ]

    operations = [
        migrations.RenameField(
            model_name="printingticketstockusagecontext",
            old_name="asset_id_snapshot",
            new_name="device_id_snapshot",
        ),
        migrations.RenameField(
            model_name="printingticketstockusagecontext",
            old_name="asset_internal_code_snapshot",
            new_name="device_identifier_snapshot",
        ),
        migrations.RenameField(
            model_name="printingticketstockusagecontext",
            old_name="asset_brand_snapshot",
            new_name="device_brand_snapshot",
        ),
        migrations.RenameField(
            model_name="printingticketstockusagecontext",
            old_name="asset_model_snapshot",
            new_name="device_model_snapshot",
        ),
        migrations.RenameField(
            model_name="printingticketstockusagecontext",
            old_name="asset_serial_snapshot",
            new_name="device_serial_snapshot",
        ),
        migrations.AlterField(
            model_name="printingticketstockusagecontext",
            name="device_id_snapshot",
            field=models.CharField(max_length=36, verbose_name="ID histórico del equipo"),
        ),
        migrations.AlterField(
            model_name="printingticketstockusagecontext",
            name="device_identifier_snapshot",
            field=models.CharField(max_length=150, verbose_name="Identificador histórico"),
        ),
    ]
