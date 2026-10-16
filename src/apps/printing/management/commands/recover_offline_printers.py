import ipaddress
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError

from apps.printing.network_recovery import scan_network_identities, recovery_result, validate_scan_options
from apps.printing.recovery_application import offline_candidates, claim_automatic_attempt, apply_recovery


class Command(BaseCommand):
    help = "Recover eligible OFFLINE printers, once per /24. Read-only unless --apply is explicit."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--apply", action="store_true")
        parser.add_argument("--timeout", type=float, default=1)
        parser.add_argument("--limit", type=int, default=20, help="Maximum eligible printers (default 20).")

    def handle(self, *args, **options):
        if options["apply"] and options["dry_run"]:
            raise CommandError("--apply y --dry-run son mutuamente excluyentes.")
        if options["limit"] <= 0:
            raise CommandError("--limit debe ser positivo.")
        try:
            validate_scan_options("10.0.0.0/24", options["timeout"], 8)
        except (TypeError, ValueError):
            raise CommandError("El timeout debe ser mayor que 0 y no superar 3 segundos.")
        totals = {key: 0 for key in ("SUBREDES_ESCANEADAS", "IMPRESORAS_ELEGIBLES", "ENCONTRADAS",
                  "ACTUALIZADAS", "SIN_CAMBIOS", "NO_ENCONTRADAS", "AMBIGUAS", "CONFLICTOS", "ERRORES")}
        groups = defaultdict(list)
        for device, candidate in offline_candidates(limit=options["limit"]):
            if options["apply"]:
                try:
                    candidate = claim_automatic_attempt(candidate)
                except Exception:
                    totals["ERRORES"] += 1
                    self.stdout.write(f"IMPRESORA={device.pk} ERROR=ATTEMPT_FAILED")
                    continue
                if candidate is None:
                    totals["CONFLICTOS"] += 1
                    continue
            subnet = str(ipaddress.ip_network(f"{candidate.old_ip}/24", strict=False))
            groups[subnet].append((device, candidate))
            totals["IMPRESORAS_ELEGIBLES"] += 1

        for subnet, candidates in groups.items():
            totals["SUBREDES_ESCANEADAS"] += 1
            try:
                scan = scan_network_identities(subnet, timeout=options["timeout"], workers=8)
                if scan["status"] != "COMPLETE" or scan["scanned_hosts"] != 254 or scan["error"]:
                    raise ValueError
            except Exception:
                totals["ERRORES"] += 1
                self.stdout.write(f"SUBRED={subnet} ERROR=INCOMPLETE_SCAN")
                continue
            for device, candidate in candidates:
                result = recovery_result(scan, candidate.expected_mac)
                status = result["status"]
                self.stdout.write(f"IMPRESORA={device.pk} ESTADO={status} IP_PROPUESTA={result['found_ip']}")
                if status == "NOT_FOUND":
                    totals["NO_ENCONTRADAS"] += 1
                elif status == "AMBIGUOUS":
                    totals["AMBIGUAS"] += 1
                elif status != "FOUND":
                    totals["ERRORES"] += 1
                else:
                    totals["ENCONTRADAS"] += 1
                    if not options["apply"]:
                        if result["found_ip"] == candidate.old_ip:
                            totals["SIN_CAMBIOS"] += 1
                        continue
                    try:
                        applied = apply_recovery(candidate, result, subnet=subnet, automatic=True)
                    except Exception:
                        totals["ERRORES"] += 1
                        self.stdout.write(f"IMPRESORA={device.pk} ERROR=APPLY_FAILED")
                        continue
                    if applied["updated"]:
                        totals["ACTUALIZADAS"] += 1
                    elif applied["unchanged"]:
                        totals["SIN_CAMBIOS"] += 1
                    else:
                        totals["CONFLICTOS"] += 1
                        self.stdout.write(f"IMPRESORA={device.pk} ERROR={applied['error']}")
        for key, value in totals.items():
            self.stdout.write(f"{key}={value}")
        self.stdout.write(f"SOLO_LECTURA={not options['apply']}")
