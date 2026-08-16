from django.db import migrations


MODEL_NAMES = {
    "acquisitionbatch": "Lote de adquisición",
    "acquisitionbatchdocument": "Documento de lote de adquisición",
    "stockbalance": "Saldo de stock",
    "stockcategory": "Categoría de stock",
    "stockdelivery": "Entrega de stock",
    "stockdeliveryline": "Línea de entrega de stock",
    "stockentrydocument": "Documento de entrada de stock",
    "stockentryline": "Línea de entrada de stock",
    "stockentryoperation": "Entrada documentada de stock",
    "stockmovement": "Movimiento de stock",
    "stockproduct": "Producto de stock",
    "ticketstockusage": "Consumo de stock por ticket",
    "ticketstockusageline": "Línea de consumo de stock por ticket",
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
                content_type__app_label="inventory",
                codename=f"{action}_{model_name}",
            ).update(name=f"{label} {verbose_name}")


class Migration(migrations.Migration):
    dependencies = [("inventory", "0012_stockmovement_ticket_ticketstockusage_and_more")]
    operations = [
        migrations.AlterModelOptions(
            name="acquisitionbatch",
            options={
                "ordering": ["-date", "-created_at"],
                "verbose_name": "Lote de adquisición",
                "verbose_name_plural": "Lotes de adquisición",
            },
        ),
        migrations.AlterModelOptions(
            name="acquisitionbatchdocument",
            options={
                "ordering": ["document_type", "-uploaded_at"],
                "verbose_name": "Documento de lote de adquisición",
                "verbose_name_plural": "Documentos de lotes de adquisición",
            },
        ),
        migrations.AlterModelOptions(
            name="stockentryline",
            options={
                "ordering": ["created_at"],
                "verbose_name": "Línea de entrada de stock",
                "verbose_name_plural": "Líneas de entrada de stock",
            },
        ),
        migrations.AlterModelOptions(
            name="stockentrydocument",
            options={
                "ordering": ["document_type", "-uploaded_at"],
                "verbose_name": "Documento de entrada de stock",
                "verbose_name_plural": "Documentos de entrada de stock",
            },
        ),
        migrations.AlterModelOptions(
            name="stockdeliveryline",
            options={
                "ordering": ["created_at"],
                "verbose_name": "Línea de entrega de stock",
                "verbose_name_plural": "Líneas de entrega de stock",
            },
        ),
        migrations.AlterModelOptions(
            name="ticketstockusageline",
            options={
                "ordering": ["created_at"],
                "verbose_name": "Línea de consumo de stock por ticket",
                "verbose_name_plural": "Líneas de consumo de stock por ticket",
            },
        ),
        migrations.RunPython(localize_permission_names, migrations.RunPython.noop),
    ]
