from django.db import migrations


MODEL_NAMES = {
    "accessidentitydocument": "Documento de identidad para acceso",
    "authorizationdocument": "Documento de autorización",
    "generatedauthorizationform": "Formulario de autorización generado",
    "systemaccessrequest": "Solicitud de acceso a sistema",
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
                content_type__app_label="tickets",
                codename=f"{action}_{model_name}",
            ).update(name=f"{label} {verbose_name}")


class Migration(migrations.Migration):
    dependencies = [("tickets", "0019_ticket_reactivation_requested_at")]
    operations = [
        migrations.AlterModelOptions(
            name="accessidentitydocument",
            options={
                "ordering": ["-version", "-created_at"],
                "verbose_name": "Documento de identidad para acceso",
                "verbose_name_plural": "Documentos de identidad para acceso",
            },
        ),
        migrations.RunPython(localize_permission_names, migrations.RunPython.noop),
    ]
