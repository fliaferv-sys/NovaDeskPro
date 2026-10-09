"""Diagnostic only: this command has no database mutation path."""
import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.printing.location_analysis import analyze_locations, analysis_summary

CSV_FIELDS = ("sede", "dependencia_original", "dependencia_normalizada", "cantidad_equipos",
              "ids_fotocopiadora", "series", "ubicacion_actual", "estado", "candidato_existente")


class Command(BaseCommand):
    help = "Analiza dependencias de impresoras sin crear ubicaciones ni modificar registros."

    def add_arguments(self, parser):
        parser.add_argument("--output", help="Ruta CSV opcional; se crea solo si se solicita y no existe.")

    def handle(self, *args, **options):
        groups = analyze_locations()
        branch_label = None
        for group in groups:
            if group.branch_label != branch_label:
                branch_label = group.branch_label
                self.stdout.write("\n" + branch_label.upper())
            row = group.csv_row()
            self.stdout.write("\nDependencia original: " + (row["dependencia_original"] or "(vacia)"))
            self.stdout.write(f"  Equipos: {row['cantidad_equipos']}")
            self.stdout.write(f"  IDs: {row['ids_fotocopiadora']}")
            self.stdout.write(f"  Series: {row['series']}")
            self.stdout.write(f"  Sede en notes: {' | '.join(sorted(group.note_branches))}")
            self.stdout.write(f"  Ubicacion actual: {row['ubicacion_actual']}")
            self.stdout.write(f"  Estado: {row['estado']}")
            self.stdout.write(f"  Coincidencia existente: {row['candidato_existente'] or 'Ninguna'}")
            for warning in sorted(group.warnings):
                self.stdout.write("  Advertencia: " + warning)
        self.stdout.write("\nResumen: " + " | ".join(f"{key}={value}" for key, value in analysis_summary(groups).items()))
        self.stdout.write("Solo diagnostico: no se crearon ni actualizaron ubicaciones, impresoras o asociaciones.")
        if options.get("output"):
            path = Path(options["output"])
            try:
                # Never overwrite an existing workbook/report or source file.
                with path.open("x", encoding="utf-8-sig", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
                    writer.writeheader()
                    writer.writerows(group.csv_row() for group in groups)
            except OSError as exc:
                raise CommandError("No se pudo crear el CSV; verifique la ruta y que no exista otro archivo.") from exc
            self.stdout.write(f"CSV: {path}")
