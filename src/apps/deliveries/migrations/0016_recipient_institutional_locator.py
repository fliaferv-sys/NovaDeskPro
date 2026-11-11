from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("deliveries", "0015_assetcustodymovement_recipient_email_and_more")]

    operations = [
        migrations.AddField(
            model_name="deliverybatch", name="recipient_locator",
            field=models.JSONField(blank=True, default=dict, verbose_name="Referencia institucional del receptor"),
        ),
        migrations.AddField(
            model_name="assetcustodymovement", name="recipient_locator",
            field=models.JSONField(blank=True, default=dict, verbose_name="Referencia institucional del receptor"),
        ),
    ]
