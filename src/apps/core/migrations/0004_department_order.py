from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_ticketcategory"),
    ]

    operations = [
        migrations.AddField(
            model_name="department",
            name="order",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Los departamentos con un número menor se muestran primero.",
                verbose_name="Orden",
            ),
        ),
        migrations.AlterModelOptions(
            name="department",
            options={"ordering": ["order", "name"]},
        ),
    ]
