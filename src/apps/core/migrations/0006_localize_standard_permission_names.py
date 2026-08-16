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
            content_type__app_label="core",
            codename=f"{action}_businesssequence",
        ).update(name=f"{label} Secuencia operativa")


class Migration(migrations.Migration):
    dependencies = [("core", "0005_businesssequence")]
    operations = [
        migrations.RunPython(localize_permission_names, migrations.RunPython.noop),
    ]
