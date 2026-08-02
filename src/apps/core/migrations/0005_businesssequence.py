from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0004_department_order")]

    operations = [
        migrations.CreateModel(
            name="BusinessSequence",
            fields=[
                ("key", models.CharField(max_length=50, primary_key=True, serialize=False)),
                ("value", models.PositiveBigIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Secuencia operativa",
                "verbose_name_plural": "Secuencias operativas",
            },
        ),
    ]
