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
            content_type__app_label="printing",
            codename=f"{action}_printingdevicenetworkdetection",
        ).update(name=f"{label} Detección de red de equipo de impresión")


class Migration(migrations.Migration):
    dependencies = [("printing", "0008_printingdevicenetworkdetection")]
    operations = [
        migrations.RunPython(localize_permission_names, migrations.RunPython.noop),
    ]
