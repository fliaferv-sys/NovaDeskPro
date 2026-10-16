import math

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.printing.connectivity import valid_ip
from apps.printing.models import PrintingDevice
from apps.printing.network_identity import fetch_network_identity, normalize_mac


class Command(BaseCommand):
    help = "Read one printer's Lexmark EWS identity and compare its current detection MAC; never writes."

    def add_arguments(self, parser):
        selectors = parser.add_mutually_exclusive_group(required=True)
        selectors.add_argument("--id", help="PrintingDevice UUID")
        selectors.add_argument("--photocopier-id", help="Visible photocopier ID")
        selectors.add_argument("--serial")
        selectors.add_argument("--ip")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--timeout", type=float)

    def handle(self, *args, **options):
        selectors = {field: options[option] for field, option in (
            ("pk", "id"), ("photocopier_id", "photocopier_id"),
            ("serial_number", "serial"), ("ip_address", "ip")) if options[option] is not None}
        if len(selectors) != 1:
            raise CommandError("Seleccione exactamente uno: --id, --photocopier-id, --serial o --ip.")
        if options["timeout"] is not None and (not math.isfinite(options["timeout"]) or not 0 < options["timeout"] <= 30):
            raise CommandError("El timeout debe ser mayor que 0 y no superar 30 segundos.")
        if options["ip"] is not None and not valid_ip(options["ip"]):
            raise CommandError("--ip requiere una IPv4 exacta; no se admiten rangos ni hostnames.")
        try:
            devices = list(PrintingDevice.objects.filter(is_active=True, **selectors)[:2])
        except (ValidationError, ValueError) as exc:
            raise CommandError("Selector inválido.") from exc
        if len(devices) != 1:
            raise CommandError("El selector debe identificar exactamente una impresora activa.")
        device = devices[0]
        current = list(device.network_detections.filter(is_current=True)[:2])
        expected = current[0].detected_mac if len(current) == 1 else ""
        result = fetch_network_identity(device.ip_address, expected_mac=expected, timeout=options["timeout"])
        if len(current) > 1 and result["error"] == "NO_VALID_EXPECTED_MAC":
            result["error"] = "AMBIGUOUS_CURRENT_DETECTION"
        for key, value in (
            ("ID_FOTOCOPIADORA", device.photocopier_id or ""),
            ("SERIAL", device.serial_number), ("IP_REGISTRADA", device.ip_address or ""),
            ("MAC_ESPERADA", normalize_mac(expected)), ("MAC_DETECTADA", result["mac"]),
            ("HOSTNAME", result["hostname"]), ("IDENTIDAD", result["identity_status"]),
            ("ORIGEN", result["source"]), ("ERROR", result["error"]),
            ("DRY_RUN", options["dry_run"]),
        ):
            self.stdout.write(f"{key}={value}")
