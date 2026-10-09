"""Backfill IPv4 only from the bounded printer-import notes block."""
from collections import Counter
from ipaddress import IPv4Address

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.printing.models import PrintingDevice
from apps.printing.printer_import import START_NOTES, END_NOTES


def resolve_note_ip(notes, current_ip):
    notes = notes or ""
    if START_NOTES not in notes and END_NOTES not in notes:
        return "SIN CAMBIOS", None, "Sin bloque importado"
    if notes.count(START_NOTES) != 1 or notes.count(END_NOTES) != 1:
        return "ERROR", None, "Marcadores incompletos o duplicados"
    start = notes.index(START_NOTES) + len(START_NOTES)
    end = notes.index(END_NOTES)
    if end < start:
        return "ERROR", None, "Marcadores en orden incorrecto"
    values = []
    for line in notes[start:end].splitlines():
        label, separator, value = line.strip().partition(":")
        if separator and label.strip() == "IP actual":
            values.append(value.strip())
    if not values:
        return "SIN CAMBIOS", None, "Sin IP actual importada"
    if len(values) != 1:
        return "REVISAR", None, "Varias lineas IP actual; no se elige una"
    if not values[0]:
        return "SIN CAMBIOS", None, "IP actual vacia"
    try:
        parsed = str(IPv4Address(values[0]))
    except ValueError:
        return "REVISAR", None, "IP actual no es IPv4 valida"
    if current_ip:
        if current_ip == parsed:
            return "SIN CAMBIOS", None, "IP estructurada ya coincide"
        return "REVISAR", None, "Conflicto con IP estructurada existente; no se sobrescribe"
    return "ACTUALIZADO", parsed, "IP estructurada vacia; IPv4 valida en bloque importado"


def plan_ip_migration(*, lock=False):
    devices = PrintingDevice.objects.only("id", "notes", "ip_address").order_by("pk")
    if lock:
        devices = devices.select_for_update()
    return [(device, *resolve_note_ip(device.notes, device.ip_address)) for device in devices]


def save_ip_migration(plans):
    for device, status, value, _ in plans:
        if status == "ACTUALIZADO":
            device.ip_address = value
            # Do not touch notes, timestamps, or any other device field.
            device.save(update_fields=["ip_address"])


class Command(BaseCommand):
    help = "Migra IPv4 desde el bloque de importacion a ip_address sin sobrescribir valores existentes."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Simula sin escrituras.")

    def report(self, plans, dry_run):
        self.stdout.write("SIMULACION" if dry_run else "MIGRACION DE IP")
        counts = Counter()
        for device, status, _, reason in plans:
            counts[status] += 1
            self.stdout.write(f"{device.pk}: {status} | {reason}")
        self.stdout.write("Resumen: " + " | ".join(f"{s}={counts[s]}" for s in ("ACTUALIZADO", "SIN CAMBIOS", "REVISAR", "ERROR")))
        if dry_run:
            self.stdout.write(f"Impresoras que recibirian IP={counts['ACTUALIZADO']}")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        try:
            if dry_run:
                plans = plan_ip_migration()
            else:
                with transaction.atomic():
                    plans = plan_ip_migration(lock=True)
                    if any(status == "ERROR" for _, status, _, _ in plans):
                        self.report(plans, True)
                        raise CommandError("ERROR: bloques incompatibles; ningun registro modificado.")
                    save_ip_migration(plans)
        except CommandError:
            raise
        except Exception as exc:
            self.stderr.write("ERROR: fallo critico; ningun cambio confirmado (rollback en ejecucion real).")
            raise CommandError("Migracion de IP cancelada; verifique que la migracion de esquema este aplicada.") from exc
        self.report(plans, dry_run)
        if any(status == "ERROR" for _, status, _, _ in plans):
            raise CommandError("ERROR: revise los bloques indicados antes de ejecutar la migracion real.")
