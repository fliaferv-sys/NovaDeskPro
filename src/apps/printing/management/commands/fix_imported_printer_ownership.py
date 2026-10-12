"""Correct only the ownership of devices with a valid managed import block."""
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.printing.models import PrintingDevice
from apps.printing.printer_import import START_NOTES, END_NOTES


def ownership_plan(lock=False):
    devices = PrintingDevice.objects.filter(notes__contains=START_NOTES).only(
        "pk", "notes", "asset_id", "ownership_type"
    ).order_by("pk")
    if lock:
        devices = devices.select_for_update()
    plans = []
    for device in devices:
        notes = device.notes
        if (notes.count(START_NOTES) != 1 or notes.count(END_NOTES) != 1
                or notes.index(END_NOTES) < notes.index(START_NOTES)):
            status, reason = "REVISAR", "Bloque importado incompleto, duplicado o fuera de orden"
        elif device.ownership_type == PrintingDevice.OwnershipType.RENTED:
            status, reason = "SIN CAMBIOS", "Ya es Alquilado"
        elif device.asset_id:
            status, reason = "REVISAR", "Equipo vinculado a un activo patrimonial"
        elif device.ownership_type == PrintingDevice.OwnershipType.OWNED:
            status, reason = "ACTUALIZADO", "Propio -> Alquilado (RENTED)"
        else:
            status, reason = "REVISAR", f"Modalidad incompatible: {device.ownership_type}"
        plans.append((device, status, reason))
    return plans


class Command(BaseCommand):
    help = "Corrige a RENTED los equipos importados con modalidad OWNED, sin tocar otros campos."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        try:
            if dry_run:
                plans = ownership_plan()
            else:
                with transaction.atomic():
                    plans = ownership_plan(lock=True)
                    for device, status, _ in plans:
                        if status == "ACTUALIZADO":
                            device.ownership_type = PrintingDevice.OwnershipType.RENTED
                            device.save(update_fields=["ownership_type"])
        except Exception as exc:
            self.stderr.write("ERROR=1 | Operacion cancelada; ningun cambio confirmado.")
            raise CommandError("No se pudo completar la correccion de propiedad.") from exc
        counts = Counter(status for _, status, _ in plans)
        self.stdout.write("SIMULACION: sin escrituras" if dry_run else "CORRECCION DE PROPIEDAD")
        for device, status, reason in plans:
            self.stdout.write(f"{device.pk}: {status} | {reason}")
        self.stdout.write(f"Total importados={len(plans)}")
        self.stdout.write("Resumen: " + " | ".join(f"{status}={counts[status]}" for status in ("ACTUALIZADO", "SIN CAMBIOS", "REVISAR", "ERROR")))
        if dry_run:
            self.stdout.write(f"Impresoras que cambiarian a Alquilado={counts['ACTUALIZADO']}")
