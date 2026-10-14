from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.printing.connectivity import valid_ip, with_connectivity, probe_device, persist_result
from apps.printing.models import PrintingDevice


class Command(BaseCommand):
    help = "Check registered printer IPs with bounded TCP probes (no GLPI, ICMP or SNMP)."

    def add_arguments(self, parser):
        selector = parser.add_mutually_exclusive_group()
        selector.add_argument("--id")
        selector.add_argument("--serial")
        selector.add_argument("--ip")
        selector.add_argument("--all", action="store_true")
        parser.add_argument("--expected-ip", help="Abort pilot if the registered IP differs; never change it.")
        parser.add_argument("--dry-run", action="store_true", help="Perform probes but persist nothing.")
        parser.add_argument("--timeout", type=float)

    def handle(self, *args, **options):
        if not any(options[key] for key in ("id", "serial", "ip", "all")):
            raise CommandError("Select --id, --serial, --ip or explicitly --all.")
        if options["timeout"] is not None and not 0 < options["timeout"] <= 10:
            raise CommandError("Timeout must be between 0 and 10 seconds.")
        if options["expected_ip"] and (options["all"] or not valid_ip(options["expected_ip"])):
            raise CommandError("--expected-ip requires an individual pilot and a valid IPv4.")
        devices = PrintingDevice.objects.filter(is_active=True)
        try:
            if options["id"]:
                devices = devices.filter(pk=options["id"])
            elif options["serial"]:
                devices = devices.filter(serial_number=options["serial"])
            elif options["ip"]:
                if not valid_ip(options["ip"]):
                    raise CommandError("--ip must be an exact valid IPv4, not a hostname or range.")
                devices = devices.filter(ip_address=options["ip"])
            devices = list(with_connectivity(devices))
        except (ValidationError, ValueError) as exc:
            raise CommandError("Invalid device selector.") from exc
        if not devices:
            raise CommandError("No active printer matches the selector.")
        if not options["all"] and len(devices) != 1 and not options["ip"]:
            raise CommandError("Ambiguous pilot selector; use --id.")
        if options["expected_ip"] and any(d.ip_address != options["expected_ip"] for d in devices):
            raise CommandError("Registered IP differs from --expected-ip. Review manually; nothing probed or changed.")
        for device in devices:
            checked_at = timezone.now()
            result = probe_device(device, timeout=options["timeout"])
            written = False if options["dry_run"] else persist_result(device, result, checked_at)
            self.stdout.write(f"{device.pk} {device.serial_number} {device.ip_address or '-'} "
                              f"{result['connection_status']} {result['monitor_error'] or '-'} "
                              f"{'DRY_RUN' if options['dry_run'] else 'SAVED' if written else 'SKIPPED'}")
