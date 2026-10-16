from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.printing.models import PrintingDevice
from apps.printing.network_identity import normalize_mac
from apps.printing.network_recovery import recover_network_identity


class Command(BaseCommand):
    help = "Propose a Lexmark printer IP within an explicit IPv4 /24; never writes, even without --dry-run."

    def add_arguments(self, parser):
        selectors = parser.add_mutually_exclusive_group(required=True)
        selectors.add_argument("--id", help="PrintingDevice UUID")
        selectors.add_argument("--photocopier-id")
        selectors.add_argument("--serial")
        parser.add_argument("--subnet", required=True, help="Explicit IPv4 /24, e.g. 10.11.42.0/24")
        parser.add_argument("--dry-run", action="store_true", help="Read-only with or without this flag.")
        parser.add_argument("--timeout", type=float, default=0.4, help="Per-host timeout, > 0 and <= 3 seconds.")

    def handle(self, *args, **options):
        selectors = {field: options[option] for field, option in (
            ("pk", "id"), ("photocopier_id", "photocopier_id"), ("serial_number", "serial"))
            if options[option] is not None}
        if len(selectors) != 1:
            raise CommandError("Seleccione exactamente uno: --id, --photocopier-id o --serial.")
        if not options["subnet"]:
            raise CommandError("Se requiere --subnet IPv4 /24 explícita.")
        try:
            devices = list(PrintingDevice.objects.filter(is_active=True, **selectors)[:2])
        except (ValidationError, ValueError) as exc:
            raise CommandError("Selector inválido.") from exc
        if len(devices) != 1:
            raise CommandError("El selector debe identificar exactamente una impresora activa.")
        device = devices[0]
        detections = list(device.network_detections.filter(is_current=True)[:2])
        if len(detections) != 1:
            raise CommandError("Se requiere exactamente una detección actual; revise las detecciones manualmente.")
        expected = normalize_mac(detections[0].detected_mac)
        if not expected:
            raise CommandError("La detección actual no contiene una MAC válida.")
        result = recover_network_identity(options["subnet"], expected, timeout=options["timeout"])
        for key, value in (
            ("ID_FOTOCOPIADORA", device.photocopier_id or ""), ("SERIAL", device.serial_number),
            ("IP_REGISTRADA", device.ip_address or ""), ("MAC_ESPERADA", expected),
            ("SUBRED", result["subnet"]), ("ESTADO", result["status"]),
            ("IP_PROPUESTA", result["found_ip"]), ("MAC_CONFIRMADA", result["found_mac"]),
            ("HOSTNAME", result["hostname"]), ("ORIGEN", result["source"]),
            ("HOSTS_CONSULTADOS", result["scanned_hosts"]), ("HOSTS_RESPONSIVOS", result["responsive_hosts"]),
            ("ERROR", result["error"]), ("DRY_RUN", options["dry_run"]),
        ):
            self.stdout.write(f"{key}={value}")
        if result["status"] == "FOUND" and result["found_ip"] == device.ip_address:
            self.stdout.write("IP_SIN_CAMBIOS=True (coincide con la IP registrada)")
        self.stdout.write("SOLO_LECTURA=True; no se modificaron IPs ni detecciones.")
