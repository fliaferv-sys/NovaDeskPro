"""Report-only proposals: no persistence or application option exists."""
import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.printing.location_proposals import propose_locations, proposal_summary

CSV_FIELDS = ("sede", "dependencia_original", "dependencia_normalizada", "cantidad_equipos",
              "ids_fotocopiadora", "series", "ubicacion_actual", "clasificacion", "motivo", "candidato_relacionado")


class Command(BaseCommand):
    help = "Propone clasificaciones de dependencias, sin crear ni modificar ubicaciones o impresoras."

    def add_arguments(self, parser):
        parser.add_argument("--output", help="Ruta CSV opcional; no sobrescribe archivos existentes.")

    def handle(self, *args, **options):
        proposals = propose_locations()
        for proposal in proposals:
            row = proposal.csv_row()
            self.stdout.write("\nSede: " + row["sede"])
            self.stdout.write("Dependencia original: " + (row["dependencia_original"] or "(vacia)"))
            for key, label in (("cantidad_equipos", "Equipos"), ("ids_fotocopiadora", "IDs"), ("series", "Series"), ("ubicacion_actual", "Ubicacion actual"), ("clasificacion", "Clasificacion"), ("motivo", "Motivo"), ("candidato_relacionado", "Candidato relacionado")):
                self.stdout.write(f"  {label}: {row[key]}")
        self.stdout.write("\nResumen: " + " | ".join(f"{key}={value}" for key, value in proposal_summary(proposals).items()))
        self.stdout.write("Solo propuestas: no se crearon ni modificaron ubicaciones, impresoras, notas o asociaciones.")
        if options.get("output"):
            path = Path(options["output"])
            try:
                with path.open("x", encoding="utf-8-sig", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
                    writer.writeheader()
                    writer.writerows(proposal.csv_row() for proposal in proposals)
            except OSError as exc:
                raise CommandError("No se pudo crear el CSV; verifique la ruta y que no exista un archivo previo.") from exc
            self.stdout.write(f"CSV: {path}")
