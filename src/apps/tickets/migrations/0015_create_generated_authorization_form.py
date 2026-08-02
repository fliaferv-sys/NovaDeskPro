import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(
            settings.AUTH_USER_MODEL
        ),
        (
            "tickets",
            "0014_alter_systemaccessrequest_options",
        ),
    ]

    operations = [
        migrations.CreateModel(
            name="GeneratedAuthorizationForm",
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
                        upload_to=(
                            "tickets/"
                            "generated_authorization_forms/"
                            "%Y/%m/"
                        ),
                        verbose_name="Formulario generado",
                    ),
                ),
                (
                    "original_name",
                    models.CharField(
                        max_length=255,
                        verbose_name="Nombre del formulario",
                    ),
                ),
                (
                    "version",
                    models.PositiveIntegerField(
                        default=1,
                        verbose_name="Versión",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        verbose_name="Fecha de generación",
                    ),
                ),
                (
                    "access_request",
                    models.ForeignKey(
                        on_delete=(
                            django.db.models.deletion.CASCADE
                        ),
                        related_name="generated_forms",
                        to="tickets.systemaccessrequest",
                        verbose_name="Solicitud de acceso",
                    ),
                ),
                (
                    "generated_by",
                    models.ForeignKey(
                        on_delete=(
                            django.db.models.deletion.PROTECT
                        ),
                        related_name=(
                            "generated_authorization_forms"
                        ),
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Generado por",
                    ),
                ),
            ],
            options={
                "verbose_name": (
                    "Formulario de autorización generado"
                ),
                "verbose_name_plural": (
                    "Formularios de autorización generados"
                ),
                "ordering": [
                    "-version",
                    "-created_at",
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="generatedauthorizationform",
            constraint=models.UniqueConstraint(
                fields=(
                    "access_request",
                    "version",
                ),
                name=(
                    "unique_generated_"
                    "authorization_form_version"
                ),
            ),
        ),
    ]