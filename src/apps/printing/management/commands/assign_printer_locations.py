from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.printing.location_assignment import assignment_plan, STATES


class Command(BaseCommand):
    help = "Asigna ubicaciones existentes exactas y unicas a impresoras importadas; no crea ubicaciones."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def report(self, plans, dry_run):
        self.stdout.write("SIMULACION: sin escrituras" if dry_run else "ASIGNACION DE UBICACIONES")
        for device, status, _, reason in plans:
            self.stdout.write(f"{device.pk}: {status} | {reason}")
        counts = Counter(status for _, status, _, _ in plans)
        self.stdout.write(f"Total importados={len(plans)}")
        self.stdout.write("Resumen: " + " | ".join(f"{s}={counts[s]}" for s in STATES))

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        try:
            if dry_run:
                plans = assignment_plan()
            else:
                with transaction.atomic():
                    plans = assignment_plan(lock=True)
                    if any(status == "ERROR" for _, status, _, _ in plans):
                        self.report(plans, True)
                        raise CommandError("Bloques invalidos: ninguna asignacion confirmada.")
                    for device, status, candidate, _ in plans:
                        if status == "ACTUALIZADO":
                            device.organizational_location = candidate
                            device.save(update_fields=["organizational_location"])
        except CommandError:
            raise
        except Exception as exc:
            self.stderr.write("ERROR: operacion cancelada; ningun cambio confirmado.")
            raise CommandError("No se pudo completar la asignacion de ubicaciones.") from exc
        self.report(plans, dry_run)
        if any(status == "ERROR" for _, status, _, _ in plans):
            raise CommandError("Revise los bloques importados invalidos.")
