from datetime import time

from django.db import migrations


def create_default_work_shifts(apps, schema_editor):
    WorkShift = apps.get_model(
        "accounts",
        "WorkShift",
    )

    WorkShift.objects.update_or_create(
        name="Turno 07:00 - 15:00",
        defaults={
            "start_time": time(7, 0),
            "end_time": time(15, 0),
            "is_active": True,
        },
    )

    WorkShift.objects.update_or_create(
        name="Turno 08:00 - 16:00",
        defaults={
            "start_time": time(8, 0),
            "end_time": time(16, 0),
            "is_active": True,
        },
    )


def remove_default_work_shifts(apps, schema_editor):
    WorkShift = apps.get_model(
        "accounts",
        "WorkShift",
    )

    WorkShift.objects.filter(
        name__in=[
            "Turno 07:00 - 15:00",
            "Turno 08:00 - 16:00",
        ]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        (
            "accounts",
            "0008_remove_technicianworkday_unique_technician_workday_per_date",
        ),
    ]

    operations = [
        migrations.RunPython(
            create_default_work_shifts,
            remove_default_work_shifts,
        ),
    ]