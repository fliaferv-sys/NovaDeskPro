import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tickets", "0015_create_generated_authorization_form"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemaccessrequest",
            name="affected_document_number",
            field=models.CharField(
                blank=True,
                default="",
                max_length=30,
                verbose_name="Numero de cedula",
            ),
        ),
        migrations.AddField(
            model_name="systemaccessrequest",
            name="requested_email",
            field=models.EmailField(
                blank=True,
                max_length=254,
                verbose_name="Correo solicitado",
            ),
        ),
        migrations.CreateModel(
            name="AccessIdentityDocument",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "file",
                    models.FileField(
                        upload_to="tickets/identity_documents/%Y/%m/",
                        verbose_name="Fotocopia de cedula",
                    ),
                ),
                ("original_name", models.CharField(max_length=255)),
                ("content_type", models.CharField(blank=True, max_length=150)),
                ("size", models.PositiveBigIntegerField(default=0)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "access_request",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="identity_documents",
                        to="tickets.systemaccessrequest",
                        verbose_name="Solicitud de acceso",
                    ),
                ),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="uploaded_access_identity_documents",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-version", "-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="accessidentitydocument",
            constraint=models.UniqueConstraint(
                fields=("access_request", "version"),
                name="unique_access_identity_document_version",
            ),
        ),
    ]
