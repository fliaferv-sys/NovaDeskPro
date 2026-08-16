from django.db import migrations


def localize_permission_names(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    actions = {
        "add": "Puede agregar",
        "change": "Puede modificar",
        "delete": "Puede eliminar",
        "view": "Puede ver",
    }
    for action, label in actions.items():
        Permission.objects.filter(
            content_type__app_label="notifications",
            codename=f"{action}_pushsubscription",
        ).update(name=f"{label} Suscripción Push")


class Migration(migrations.Migration):
    dependencies = [("notifications", "0005_pushsubscription")]
    operations = [
        migrations.RunPython(localize_permission_names, migrations.RunPython.noop),
    ]
