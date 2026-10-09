"""Remove only the unconfirmed contract line from the managed import block."""
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.printing.models import PrintingDevice
from apps.printing.printer_import import START_NOTES, END_NOTES, normalize_text

TARGET_LINE = "Contrato: PR/PR N\u00b0 012/22"


def cleaned_notes(notes):
    notes = notes or ""
    if START_NOTES not in notes and END_NOTES not in notes:
        return notes
    if notes.count(START_NOTES) != 1 or notes.count(END_NOTES) != 1:
        raise ValueError("Bloque importado ausente, duplicado o incompleto.")
    start = notes.index(START_NOTES) + len(START_NOTES)
    end = notes.index(END_NOTES)
    if end < start:
        raise ValueError("Marcadores del bloque importado en orden incorrecto.")
    body = notes[start:end]
    kept = [line for line in body.splitlines(keepends=True)
            if normalize_text(line) != TARGET_LINE]
    return notes[:start] + "".join(kept) + notes[end:]


def plan_cleanup(*, lock=False):
    devices = PrintingDevice.objects.only("id", "notes", "updated_at").order_by("pk")
    if lock:
        devices = devices.select_for_update()
    plans = []
    for device in devices:
        try:
            result = cleaned_notes(device.notes)
            status = "ACTUALIZADO" if result != (device.notes or "") else "SIN CAMBIOS"
            plans.append((device, status, result, ""))
        except ValueError as exc:
            plans.append((device, "ERROR", device.notes, str(exc)))
    return plans


def save_cleanup(plans):
    for device, status, notes, _ in plans:
        if status == "ACTUALIZADO":
            device.notes = notes
            device.save(update_fields=["notes", "updated_at"])


class Command(BaseCommand):
    help = "Retira el contrato no confirmado solo del bloque de importacion de impresoras."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Simula sin modificar la base.")

    def report(self, plans, dry_run):
        self.stdout.write("SIMULACION" if dry_run else "LIMPIEZA")
        counts = Counter()
        for device, status, _, error in plans:
            counts[status] += 1
            suffix = ": " + error if error else ""
            self.stdout.write(f"{device.pk}: {status}{suffix}")
        self.stdout.write("Resumen: " + " | ".join(f"{s}={counts[s]}" for s in ("ACTUALIZADO", "SIN CAMBIOS", "ERROR")))
        if dry_run:
            self.stdout.write(f"Impresoras que serian limpiadas={counts['ACTUALIZADO']}")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        try:
            if dry_run:
                plans = plan_cleanup()
            else:
                with transaction.atomic():
                    plans = plan_cleanup(lock=True)
                    if any(status == "ERROR" for _, status, _, _ in plans):
                        self.report(plans, True)
                        raise CommandError("ERROR: bloques incompatibles; ningun registro modificado.")
                    save_cleanup(plans)
        except CommandError:
            raise
        except Exception as exc:
            self.stderr.write("ERROR: fallo critico; ningun cambio confirmado (rollback en limpieza real).")
            raise CommandError("Limpieza cancelada.") from exc
        self.report(plans, dry_run)
        if any(status == "ERROR" for _, status, _, _ in plans):
            raise CommandError("ERROR: revise los bloques indicados antes de ejecutar la limpieza real.")
