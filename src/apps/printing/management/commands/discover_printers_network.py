import csv
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from django.core.management.base import BaseCommand, CommandError

from apps.printing.network_map import SITES, select_networks
from apps.printing.network_discovery import discover_networks
from apps.printing.network_recovery import validate_scan_options
from apps.printing.network_reconciliation import STATUSES, load_records, reconcile_findings
from apps.printing.recovery_application import DiscoveryCandidate, apply_discovery_change

CSV_FIELDS = (
    ("SEDE", "site"), ("SECTOR_RED", "sector"), ("SUBRED", "subnet"), ("IP", "ip"),
    ("MAC", "mac"), ("HOSTNAME", "hostname"), ("FABRICANTE", "manufacturer"),
    ("MODELO", "model"), ("SERIAL", "serial"), ("ESTADO_CONCILIACION", "status"),
    ("PRINTING_DEVICE_ID", "device_id"), ("ID_FOTOCOPIADORA", "photocopier_id"),
    ("IP_NOVADESK", "novadesk_ip"), ("ACCION_PROPUESTA", "action"),
    ("MOTIVO", "reason"), ("ERROR", "error"), ("ACTUALIZADO", "updated"),
    ("ESTADO_SNMP", "snmp_status"), ("ERROR_SNMP", "snmp_error"),
    ("ORIGEN_SERIAL", "serial_source"),
)


def csv_value(value):
    value = str(value if value is not None else "")
    return "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else value


class Command(BaseCommand):
    help = "Discover authorized printer networks and export reconciliation; writes existing IPs only with --apply."

    def add_arguments(self, parser):
        scope = parser.add_mutually_exclusive_group(required=True)
        scope.add_argument("--all-authorized", action="store_true")
        scope.add_argument("--subnet", action="append", help="Authorized /24; repeat for multiple networks.")
        scope.add_argument("--site", choices=SITES)
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--apply", action="store_true")
        parser.add_argument("--timeout", type=float, default=1)
        parser.add_argument("--workers", type=int, default=8)
        parser.add_argument("--output", help="CSV file. Default: ~/NovaDeskProReports/Printing (outside the repository).")
        parser.add_argument("--overwrite", action="store_true", help="Explicitly permit replacing the output CSV.")

    def handle(self, *args, **options):
        if options["apply"] and options["dry_run"]:
            raise CommandError("--apply y --dry-run son mutuamente excluyentes.")
        try:
            entries = select_networks(subnets=options["subnet"], site=options["site"], all_authorized=options["all_authorized"])
            for entry in entries:
                validate_scan_options(entry.subnet, options["timeout"], options["workers"])
        except (TypeError, ValueError):
            raise CommandError("Ámbito no autorizado u opciones inválidas. Solo /24 del mapa; timeout <= 3 y workers <= 8.")
        output = Path(options["output"]).expanduser() if options["output"] else (
            Path.home() / "NovaDeskProReports" / "Printing" /
            f"discovery-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid4().hex[:8]}.csv")
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            # Reserve output before any scan or DB mutation; no silent overwrite.
            report = output.open("w" if options["overwrite"] else "x", encoding="utf-8-sig", newline="")
        except OSError:
            raise CommandError("No se pudo crear el CSV; un archivo existente requiere --overwrite.")
        totals = {key: 0 for key in ("SUBREDES_ESCANEADAS", "HOSTS_CONSULTADOS", "IMPRESORAS_IDENTIFICADAS",
                                    *STATUSES, "ACTUALIZADAS", "ERRORES")}
        with report:
            writer = csv.writer(report)
            writer.writerow([header for header, _ in CSV_FIELDS])
            report.flush()
            devices, detections = load_records()
            candidates = {str(device.pk): DiscoveryCandidate.capture(device, detections.get(device.pk, [])) for device in devices}
            try:
                scans = discover_networks([entry.subnet for entry in entries], timeout=options["timeout"], workers=options["workers"])
            except Exception:
                raise CommandError("DISCOVERY_FAILED: no se aplicaron cambios.")
            totals["SUBREDES_ESCANEADAS"] = len(scans)
            totals["HOSTS_CONSULTADOS"] = sum(scan["scanned_hosts"] for scan in scans)
            totals["ERRORES"] = sum(scan["status"] != "COMPLETE" for scan in scans)
            findings = [finding for scan in scans for finding in scan["findings"]]
            rows = reconcile_findings(findings, devices, detections)
            totals["IMPRESORAS_IDENTIFICADAS"] = sum(bool(f.get("supported")) for f in findings)
            for row in rows:
                totals[row["status"]] += 1
                row["updated"] = False
                if options["apply"] and row["status"] == "IP_CHANGED":
                    try:
                        applied = apply_discovery_change(candidates[row["device_id"]], row, timeout=options["timeout"])
                        row["updated"] = applied["updated"]
                        if not applied["updated"]:
                            row.update(reason=applied["error"], action="ABORTED")
                            totals["ERRORES"] += 1
                    except Exception:
                        row.update(reason="APPLY_FAILED", action="ABORTED")
                        totals["ERRORES"] += 1
                if row["updated"]:
                    totals["ACTUALIZADAS"] += 1
                    row["action"] = "IP_UPDATED"
                writer.writerow([csv_value(row.get(field, "")) for _, field in CSV_FIELDS])
            report.flush()
        for key, value in totals.items():
            self.stdout.write(f"{key}={value}")
        self.stdout.write(f"CSV={output}")
        self.stdout.write(f"SOLO_LECTURA_BD={not options['apply']}")
