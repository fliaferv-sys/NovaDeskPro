"""Initial MAC enrollment is deliberately separate from discovery --apply."""
import csv
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from django.core.management.base import BaseCommand, CommandError

from .discover_printers_network import csv_value
from apps.printing.initial_identity import load_inventory, snapshot, evaluate, apply_initial_binding
from apps.printing.network_discovery import discover_networks
from apps.printing.network_map import SITES, select_networks
from apps.printing.network_recovery import validate_scan_options
from apps.printing.network_identity import normalize_mac

FIELDS = ("device_id", "photocopier_id", "serial", "mac", "ip", "source", "serial_source",
          "snmp_status", "snmp_error", "status", "reason", "observed_at")


class Command(BaseCommand):
    help = "Report initial physical identities; enroll MAC only with --apply-bindings. Never changes inventory IP."

    def add_arguments(self, parser):
        # argparse otherwise accepts --apply as an abbreviation of --apply-bindings.
        parser.allow_abbrev = False
        scope = parser.add_mutually_exclusive_group(required=True)
        scope.add_argument("--all-authorized", action="store_true")
        scope.add_argument("--subnet", action="append")
        scope.add_argument("--site", choices=SITES)
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--apply-bindings", action="store_true")
        parser.add_argument("--timeout", type=float, default=1)
        parser.add_argument("--workers", type=int, default=8)
        parser.add_argument("--output")
        parser.add_argument("--overwrite", action="store_true")

    def handle(self, *args, **options):
        if options["apply_bindings"] and options["dry_run"]:
            raise CommandError("Use --dry-run o --apply-bindings.")
        try:
            entries = select_networks(subnets=options["subnet"], site=options["site"], all_authorized=options["all_authorized"])
            for entry in entries:
                validate_scan_options(entry.subnet, options["timeout"], options["workers"])
        except (TypeError, ValueError):
            raise CommandError("Ámbito u opciones inválidas.")
        output = Path(options["output"]).expanduser() if options["output"] else (
            Path.home() / "NovaDeskProReports" / "Printing" /
            f"initial-identity-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid4().hex[:8]}.csv")
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            report = output.open("w" if options["overwrite"] else "x", encoding="utf-8-sig", newline="")
        except OSError:
            raise CommandError("No se pudo crear el CSV; un archivo existente requiere --overwrite.")
        bound = 0
        with report:
            writer = csv.writer(report)
            writer.writerow(FIELDS)
            report.flush()
            devices, detections = load_inventory()
            baseline = snapshot(devices, detections)
            try:
                scans = discover_networks([e.subnet for e in entries], timeout=options["timeout"], workers=options["workers"])
            except Exception:
                raise CommandError("DISCOVERY_FAILED: no se aplicaron asociaciones.")
            findings = [f for scan in scans for f in scan["findings"]]
            complete = len(scans) == len(entries) and all(s["status"] == "COMPLETE" and s["scanned_hosts"] == 254 for s in scans)
            serials = Counter(f.get("serial") for f in findings if f.get("serial"))
            macs = Counter(normalize_mac(f.get("mac")) for f in findings if normalize_mac(f.get("mac")))
            for finding in findings:
                finding = {**finding, "scan_complete": complete and finding.get("scan_complete", False)}
                row = evaluate(finding, devices, detections)
                if serials[finding.get("serial")] > 1 or macs[normalize_mac(finding.get("mac"))] > 1:
                    row.update(status="BLOCKED", reason="DUPLICATE_NETWORK_IDENTITY")
                if options["apply_bindings"] and row["status"] == "PENDING_INITIAL_BINDING":
                    try:
                        result = apply_initial_binding(finding, baseline, timeout=options["timeout"])
                    except Exception:
                        result = "BINDING_FAILED"
                    row.update(status="BOUND" if result == "BOUND" else "BLOCKED", reason=result)
                    if result == "BOUND":
                        bound += 1
                row["observed_at"] = datetime.now(timezone.utc).isoformat()
                writer.writerow([csv_value(row.get(field, "")) for field in FIELDS])
                report.flush()
        self.stdout.write(f"VINCULADAS={bound}")
        self.stdout.write(f"SOLO_LECTURA_BD={not options['apply_bindings']}")
        self.stdout.write(f"CSV={output}")
