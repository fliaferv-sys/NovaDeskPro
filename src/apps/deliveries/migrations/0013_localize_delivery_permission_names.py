from django.db import migrations


DELIVERY_PERMISSION_NAMES = {
    "add_assetcustodymovement": "Puede agregar Movimiento de custodia",
    "change_assetcustodymovement": "Puede modificar Movimiento de custodia",
    "delete_assetcustodymovement": "Puede eliminar Movimiento de custodia",
    "view_assetcustodymovement": "Puede ver Movimiento de custodia",
    "add_deliverybatch": "Puede agregar Acta agrupada de entrega",
    "change_deliverybatch": "Puede modificar Acta agrupada de entrega",
    "delete_deliverybatch": "Puede eliminar Acta agrupada de entrega",
    "view_deliverybatch": "Puede ver Acta agrupada de entrega",
    "add_deliverydocument": "Puede agregar Documento de entrega",
    "change_deliverydocument": "Puede modificar Documento de entrega",
    "delete_deliverydocument": "Puede eliminar Documento de entrega",
    "view_deliverydocument": "Puede ver Documento de entrega",
    "add_deliverybatchdocument": "Puede agregar Documento de acta agrupada",
    "change_deliverybatchdocument": "Puede modificar Documento de acta agrupada",
    "delete_deliverybatchdocument": "Puede eliminar Documento de acta agrupada",
    "view_deliverybatchdocument": "Puede ver Documento de acta agrupada",
}


def localize_delivery_permission_names(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")

    for codename, name in DELIVERY_PERMISSION_NAMES.items():
        Permission.objects.filter(
            content_type__app_label="deliveries",
            codename=codename,
        ).update(name=name)


class Migration(migrations.Migration):
    dependencies = [
        ("deliveries", "0012_assetcustodymovement_destination_branch_and_more"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="deliverybatchdocument",
            options={
                "ordering": ["document_type", "-uploaded_at"],
                "verbose_name": "Documento de acta agrupada",
                "verbose_name_plural": "Documentos de actas agrupadas",
            },
        ),
        migrations.RunPython(
            localize_delivery_permission_names,
            migrations.RunPython.noop,
        ),
    ]
