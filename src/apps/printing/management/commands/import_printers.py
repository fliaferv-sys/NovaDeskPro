from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.printing.printer_import import (
    PrinterImportError, PrinterImportPlanner, read_import_rows, save_import_row,
)


class Command(BaseCommand):
    help = "Importa IMPORTACION_PRINTING al módulo Printing existente, por serie."

    def add_arguments(self, parser):
        parser.add_argument("archivo", help="Ruta del Excel .xlsx")
        parser.add_argument("--dry-run", action="store_true", help="Valida y simula sin ninguna escritura en BD.")
        parser.add_argument("--brand", default="", help="Marca opcional de confirmación; solo se admiten las familias Lexmark aprobadas.")

    def handle(self, *args, **options):
        try:
            rows = read_import_rows(options["archivo"])
            if options["dry_run"]:
                plans = PrinterImportPlanner(brand=options["brand"]).plan(rows)
            else:
                with transaction.atomic():
                    plans = PrinterImportPlanner(brand=options["brand"], lock=True).plan(rows)
                    for plan in plans:
                        if plan.status in {"NUEVO", "ACTUALIZADO"}:
                            save_import_row(plan)
        except PrinterImportError as exc:
            raise CommandError(str(exc)) from exc
        except Exception as exc:
            # Never emit DB errors, row contents or personal-data details.
            raise CommandError("Error crítico: no se confirmó ningún cambio (rollback en importación real).") from exc
        prefix = "SIMULACIÓN" if options["dry_run"] else "IMPORTACIÓN"
        counts = Counter(plan.status for plan in plans)
        self.stdout.write(prefix)
        for plan in plans:
            # Row numbers provide traceability without printing responsible names/IPs.
            details = plan.errors or plan.pending
            suffix = " | " + "; ".join(details) if details else ""
            self.stdout.write(f"Fila {plan.number}: {plan.status}{suffix}")
        self.stdout.write("Resumen: " + " | ".join(f"{status}={counts[status]}" for status in ("NUEVO", "ACTUALIZADO", "SIN CAMBIOS", "RECHAZADO", "IGNORADO")))
        self.stdout.write(f"Filas con datos pendientes={sum(bool(plan.pending) for plan in plans)}")
        if counts["RECHAZADO"]:
            self.stdout.write("Las filas rechazadas no se guardaron; revise los números de fila indicados.")
