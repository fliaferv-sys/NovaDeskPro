from django.db import migrations, models


def remove_duplicate_keys(apps, schema_editor):
    Notification = apps.get_model("notifications", "Notification")
    keys = (
        Notification.objects.exclude(unique_key="")
        .values_list("unique_key", flat=True)
        .distinct()
    )
    for key in keys.iterator():
        duplicates = Notification.objects.filter(unique_key=key).order_by("-updated_at")
        keep_id = duplicates.values_list("pk", flat=True).first()
        duplicates.exclude(pk=keep_id).delete()


class Migration(migrations.Migration):
    dependencies = [("notifications", "0002_notification_reopened_at_notification_reopened_by_and_more")]

    operations = [
        migrations.RunPython(remove_duplicate_keys, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="notification",
            constraint=models.UniqueConstraint(
                fields=("unique_key",),
                condition=~models.Q(unique_key=""),
                name="unique_nonempty_notification_key",
            ),
        ),
    ]
