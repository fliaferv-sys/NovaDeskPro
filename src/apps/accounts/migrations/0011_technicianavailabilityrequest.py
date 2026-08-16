import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0010_localize_standard_permission_names"),
    ]

    operations = [
        migrations.CreateModel(
            name="TechnicianAvailabilityRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("request_type", models.CharField(choices=[("UNAVAILABLE", "No disponible"), ("EARLY_WORKDAY_END", "Fin de jornada anticipada")], max_length=30, verbose_name="Tipo de solicitud")),
                ("reason", models.TextField(verbose_name="Motivo")),
                ("status", models.CharField(choices=[("PENDING", "Pendiente"), ("APPROVED", "Aprobada"), ("REJECTED", "Rechazada")], default="PENDING", max_length=20, verbose_name="Estado")),
                ("requested_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha y hora de solicitud")),
                ("resolved_at", models.DateTimeField(blank=True, null=True, verbose_name="Fecha y hora de resolución")),
                ("resolution_note", models.TextField(blank=True, verbose_name="Observación de resolución")),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("resolved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="resolved_availability_requests", to=settings.AUTH_USER_MODEL, verbose_name="Resuelta por")),
                ("technician", models.ForeignKey(limit_choices_to={"role": "TECHNICIAN"}, on_delete=django.db.models.deletion.PROTECT, related_name="availability_requests", to=settings.AUTH_USER_MODEL, verbose_name="Técnico")),
                ("workday", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="availability_requests", to="accounts.technicianworkday", verbose_name="Jornada")),
            ],
            options={
                "verbose_name": "Solicitud de disponibilidad de técnico",
                "verbose_name_plural": "Solicitudes de disponibilidad de técnicos",
                "ordering": ["-requested_at"],
                "constraints": [
                    models.UniqueConstraint(condition=models.Q(("status", "PENDING")), fields=("technician", "workday", "request_type"), name="unique_pending_technician_availability_request"),
                ],
            },
        ),
    ]
