from django.db import migrations


MODEL_NAMES = {
    "technicianworkday": "Jornada de técnico",
    "workshift": "Turno laboral",
}

ACTIONS = {
    "add": "Puede agregar",
    "change": "Puede modificar",
    "delete": "Puede eliminar",
    "view": "Puede ver",
}


def localize_permission_names(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    for model_name, verbose_name in MODEL_NAMES.items():
        for action, label in ACTIONS.items():
            Permission.objects.filter(
                content_type__app_label="accounts",
                codename=f"{action}_{model_name}",
            ).update(name=f"{label} {verbose_name}")


class Migration(migrations.Migration):
    dependencies = [("accounts", "0009_seed_default_work_shifts")]
    operations = [
        migrations.RunPython(localize_permission_names, migrations.RunPython.noop),
    ]
