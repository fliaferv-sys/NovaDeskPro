from django.db import migrations


def move_assigned_open_tickets_to_in_progress(apps, schema_editor):
    Ticket = apps.get_model("tickets", "Ticket")
    Ticket.objects.filter(
        assigned_to__isnull=False,
        status="OPEN",
    ).update(status="IN_PROGRESS")


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0016_systemaccessrequest_identity_documents"),
    ]

    operations = [
        migrations.RunPython(
            move_assigned_open_tickets_to_in_progress,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
