"""Backfill photocopier IDs exclusively from managed printer-import notes."""
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.printing.models import PrintingDevice
from apps.printing.printer_import import START_NOTES, END_NOTES
from apps.printing.printer_ids import origin_id, id_key, existing_id_owners, resolve_origin_id


def extract_origin_id(notes):
    if notes.count(START_NOTES) != 1 or notes.count(END_NOTES) != 1:
        return "ERROR", None, "Marcadores del bloque importado incompletos o duplicados"
    start = notes.index(START_NOTES) + len(START_NOTES)
    end = notes.index(END_NOTES)
    if end < start:
        return "ERROR", None, "Marcadores del bloque importado en orden incorrecto"
    values = []
    for line in notes[start:end].splitlines():
        label, separator, value = line.strip().partition(":")
        if separator and label.strip() == "ID origen":
            values.append(value.strip())
    if len(values) > 1:
        return "REVISAR", None, "Varias lineas ID origen; no se elige una"
    try:
        return "VALIDADO", origin_id(values[0] if values else None), ""
    except ValueError as exc:
        return "REVISAR", None, str(exc)


def plan_id_migration(*, lock=False):
    queryset = PrintingDevice.objects.only("id", "notes", "photocopier_id").order_by("pk")
    if lock:
        queryset = queryset.select_for_update()
    devices = list(queryset)
    owners = existing_id_owners(devices)
    extracted = [(device, *extract_origin_id(device.notes)) for device in devices
                 if START_NOTES in (device.notes or "")]
    counts = Counter(id_key(value) for _, status, value, _ in extracted if status == "VALIDADO" and value)
    plans = []
    for device, status, value, reason in extracted:
        if status == "VALIDADO":
            status, value, reason = resolve_origin_id(value, device.photocopier_id, device.pk, owners, counts)
        plans.append((device, status, value, reason))
    return plans


def save_id_migration(plans):
    for device, status, value, _ in plans:
        if status == "ACTUALIZADO":
            device.photocopier_id = value
            device.save(update_fields=["photocopier_id"])


class Command(BaseCommand):
    help = "Migra ID origen desde el bloque importado, sin reemplazar IDs ni generar nuevos."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Simula sin escrituras.")

    def report(self, plans, dry_run):
        self.stdout.write("SIMULACION" if dry_run else "MIGRACION DE ID")
        counts = Counter()
        for device, status, _, reason in plans:
            counts[status] += 1
            self.stdout.write(f"{device.pk}: {status} | {reason}")
        self.stdout.write(f"Total impresoras con bloque importado={len(plans)}")
        self.stdout.write("Resumen: " + " | ".join(f"{s}={counts[s]}" for s in ("ACTUALIZADO", "SIN CAMBIOS", "REVISAR", "ERROR")))
        if dry_run:
            self.stdout.write(f"Impresoras que recibirian ID={counts['ACTUALIZADO']}")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        try:
            if dry_run:
                plans = plan_id_migration()
            else:
                with transaction.atomic():
                    plans = plan_id_migration(lock=True)
                    if any(status == "ERROR" for _, status, _, _ in plans):
                        self.report(plans, True)
                        raise CommandError("ERROR: bloques incompatibles; ningun registro modificado.")
                    save_id_migration(plans)
        except CommandError:
            raise
        except Exception as exc:
            self.stderr.write("ERROR: fallo critico; ningun cambio confirmado (rollback en ejecucion real).")
            raise CommandError("Migracion de IDs cancelada; revise conflictos concurrentes y restricciones de la base.") from exc
        self.report(plans, dry_run)
        if any(status == "ERROR" for _, status, _, _ in plans):
            raise CommandError("ERROR: revise los bloques indicados antes de ejecutar la migracion real.")
