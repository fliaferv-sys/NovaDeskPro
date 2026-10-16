import ipaddress
import json
from io import StringIO
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from django.core.management import call_command, CommandError
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext

from .models import PrintingDevice, PrintingDeviceNetworkDetection
from .network_recovery import recover_network_identity

MAC = "00:21:B7:EF:1D:AA"
SUBNET = "10.11.42.0/24"


class EWSResponses:
    """Mock HTTP transport, preserving the real GET/parser/MAC comparison path."""
    def start_http(self):
        self.responses = {}
        self.http_patch = patch("apps.printing.network_identity.build_opener")
        self.opener = self.http_patch.start().return_value
        self.addCleanup(self.http_patch.stop)
        self.opener.open.side_effect = self.http_response

    def http_response(self, request, *, timeout):
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertEqual(urlsplit(request.full_url).path, "/webglue/rawcontent")
        ip = urlsplit(request.full_url).hostname
        value = self.responses.get(ip, TimeoutError("private network diagnostic"))
        if isinstance(value, Exception):
            raise value
        response = MagicMock()
        response.__enter__.return_value.read.return_value = value
        return response

    def printer(self, ip, mac=MAC):
        self.responses[ip] = json.dumps({"nodes": {"nodes": {
            "EthernetUAA": {"name": "EthernetUAA", "setting": 987},
            "SetHostname": {"name": "SetHostname", "setting": 654},
        }, "settings": {"987": {"val": mac.replace(":", "")},
                        "654": {"val": "ET0021B7EF1DAA"}}}}).encode()


class NetworkRecoveryTests(EWSResponses, SimpleTestCase):
    def setUp(self):
        self.start_http()

    def test_found_different_ip_exact_mac_and_structured_result(self):
        self.printer("10.11.42.241")
        self.printer("10.11.42.15", "00:21:B7:EF:1D:BB")
        result = recover_network_identity(SUBNET, "0021b7ef1daa")
        self.assertEqual(result, dict(expected_mac=MAC, subnet=SUBNET, found_ip="10.11.42.241",
            found_mac=MAC, hostname="ET0021B7EF1DAA", status="FOUND", scanned_hosts=254,
            responsive_hosts=2, match_count=1, error="", source="LEXMARK_EWS"))
        self.assertTrue(all(call.kwargs["timeout"] == 0.4 for call in self.opener.open.call_args_list))

    def test_only_usable_hosts_of_explicit_ipv4_24_are_consulted(self):
        recover_network_identity(SUBNET, MAC)
        ips = [urlsplit(call.args[0].full_url).hostname for call in self.opener.open.call_args_list]
        expected = [str(ip) for ip in ipaddress.ip_network(SUBNET).hosts()]
        self.assertEqual(ips, expected)
        self.assertNotIn("10.11.42.0", ips)
        self.assertNotIn("10.11.42.255", ips)
        self.assertEqual(len(ips), len(set(ips)))

    def test_invalid_subnets_ipv6_host_bits_16_and_25_never_connect(self):
        for subnet in ("invalid", "2001:db8::/24", "10.11.0.0/16", "10.11.42.0/25",
                       "10.11.42.1/24", "10.11.42.1-254", "10.11.42.0", None):
            with self.subTest(subnet=subnet):
                result = recover_network_identity(subnet, MAC)
                self.assertEqual(result["status"], "INVALID")
                self.assertEqual(result["error"], "INVALID_SUBNET")
                self.assertEqual(result["scanned_hosts"], 0)
        self.opener.open.assert_not_called()

    def test_invalid_expected_mac_never_connects(self):
        for mac in (None, "invalid", "000000000000", "FFFFFFFFFFFF"):
            result = recover_network_identity(SUBNET, mac)
            self.assertEqual(result["status"], "INVALID")
            self.assertEqual(result["error"], "INVALID_EXPECTED_MAC")
        self.opener.open.assert_not_called()

    def test_timeout_is_configurable_and_never_exceeds_three_seconds(self):
        for timeout in (0, -1, 3.1, float("nan"), float("inf"), "invalid", None):
            self.assertEqual(recover_network_identity(SUBNET, MAC, timeout=timeout)["error"], "INVALID_TIMEOUT")
        self.opener.open.assert_not_called()
        recover_network_identity(SUBNET, MAC, timeout=3)
        self.assertTrue(all(call.kwargs["timeout"] == 3 for call in self.opener.open.call_args_list))

    def test_generic_http_and_other_mac_are_not_identity_matches(self):
        self.responses["10.11.42.1"] = b"<html>HTTP server is up</html>"
        self.printer("10.11.42.2", "00:21:B7:EF:1D:BB")
        result = recover_network_identity(SUBNET, MAC)
        self.assertEqual(result["status"], "NOT_FOUND")
        self.assertEqual(result["found_ip"], "")
        self.assertEqual(result["responsive_hosts"], 1)

    def test_duplicate_mac_is_ambiguous_and_no_ip_is_proposed(self):
        self.printer("10.11.42.1")
        self.printer("10.11.42.254")
        result = recover_network_identity(SUBNET, MAC)
        self.assertEqual(result["status"], "AMBIGUOUS")
        self.assertEqual(result["scanned_hosts"], 254)
        self.assertEqual(result["found_ip"], "")
        self.assertEqual(result["found_mac"], "")

    def test_network_errors_and_invalid_json_are_safe_without_exception_text(self):
        self.responses.update({"10.11.42.1": URLError("SECRET"),
            "10.11.42.2": HTTPError("url", 403, "SECRET", {}, None),
            "10.11.42.3": b"not json"})
        result = recover_network_identity(SUBNET, MAC)
        self.assertEqual(result["status"], "NOT_FOUND")
        self.assertEqual(result["scanned_hosts"], 254)
        self.assertNotIn("SECRET", str(result))
        self.assertNotIn("Traceback", str(result))

    def test_unexpected_failure_does_not_allow_unverified_unique_proposal(self):
        self.printer("10.11.42.241")
        self.responses["10.11.42.1"] = RuntimeError("SECRET")
        result = recover_network_identity(SUBNET, MAC)
        self.assertEqual(result["status"], "INVALID")
        self.assertEqual(result["error"], "INCOMPLETE_SCAN")
        self.assertEqual(result["found_ip"], "")
        self.assertNotIn("SECRET", str(result))


class RecoverPrinterIPCommandTests(EWSResponses, TestCase):
    def setUp(self):
        self.start_http()
        self.device = PrintingDevice.objects.create(photocopier_id="21", serial_number="7018909304981",
                                                    ip_address="10.11.42.249")
        self.detection = PrintingDeviceNetworkDetection.objects.create(printing_device=self.device,
            detected_ip=self.device.ip_address, detected_mac=MAC, detection_source="MANUAL", notes="Preservar")

    def command(self, **options):
        output = StringIO()
        call_command("recover_printer_ip", stdout=output, **options)
        return output.getvalue()

    def snapshot(self):
        return (list(PrintingDevice.objects.order_by("pk").values()),
                list(PrintingDeviceNetworkDetection.objects.order_by("pk").values()))

    def test_found_new_ip_never_writes_with_or_without_dry_run_and_sql_is_constant(self):
        self.printer("10.11.42.241")
        before = self.snapshot()
        for dry_run in (False, True):
            with CaptureQueriesContext(connection) as queries:
                output = self.command(photocopier_id="21", subnet=SUBNET, dry_run=dry_run)
            self.assertEqual(len(queries), 2)  # Device and current detections; no SQL in the /24 loop.
            self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))
            self.assertIn("ESTADO=FOUND", output)
            self.assertIn("IP_PROPUESTA=10.11.42.241", output)
            self.assertIn("MAC_CONFIRMADA=" + MAC, output)
            self.assertIn("IP_REGISTRADA=10.11.42.249", output)
            self.assertIn(f"DRY_RUN={dry_run}", output)
            self.assertEqual(self.snapshot(), before)

    def test_same_ip_is_explicitly_reported_for_uuid_and_serial_selectors(self):
        self.printer(self.device.ip_address)
        for selector in ({"id": str(self.device.pk)}, {"serial": self.device.serial_number}):
            output = self.command(subnet=SUBNET, **selector)
            self.assertIn("ESTADO=FOUND", output)
            self.assertIn("IP_SIN_CAMBIOS=True", output)

    def test_not_found_and_ambiguous_do_not_propose_or_modify_anything(self):
        before = self.snapshot()
        output = self.command(photocopier_id="21", subnet=SUBNET)
        self.assertIn("ESTADO=NOT_FOUND", output)
        self.printer("10.11.42.1")
        self.printer("10.11.42.254")
        output = self.command(photocopier_id="21", subnet=SUBNET)
        self.assertIn("ESTADO=AMBIGUOUS", output)
        self.assertIn("IP_PROPUESTA=\n", output)
        self.assertEqual(self.snapshot(), before)

    def test_missing_multiple_or_invalid_current_detection_abort_without_http(self):
        self.detection.is_current = False
        self.detection.save()
        with self.assertRaises(CommandError):
            self.command(photocopier_id="21", subnet=SUBNET)
        self.detection.is_current = True
        self.detection.detected_mac = "invalid"
        self.detection.save()
        with self.assertRaises(CommandError):
            self.command(photocopier_id="21", subnet=SUBNET)
        self.detection.detected_mac = MAC
        self.detection.save()
        PrintingDeviceNetworkDetection.objects.create(printing_device=self.device, detected_mac=MAC)
        before = self.snapshot()
        with self.assertRaises(CommandError):
            self.command(photocopier_id="21", subnet=SUBNET)
        self.assertEqual(self.snapshot(), before)
        self.opener.open.assert_not_called()

    def test_invalid_inactive_ambiguous_or_multiple_device_selectors_abort(self):
        for options in ({"id": "invalid"}, {"serial": "absent"},
                        {"serial": self.device.serial_number, "photocopier_id": "21"}):
            with self.assertRaises(CommandError):
                self.command(subnet=SUBNET, **options)
        PrintingDevice.objects.create(serial_number=self.device.serial_number)
        with self.assertRaises(CommandError):
            self.command(serial=self.device.serial_number, subnet=SUBNET)
        self.device.is_active = False
        self.device.save()
        with self.assertRaises(CommandError):
            self.command(photocopier_id="21", subnet=SUBNET)
        self.opener.open.assert_not_called()

    def test_invalid_network_or_timeout_reports_invalid_without_http_or_writes(self):
        before = self.snapshot()
        for options in ({"subnet": "10.11.0.0/16"}, {"subnet": SUBNET, "timeout": 4}):
            output = self.command(photocopier_id="21", **options)
            self.assertIn("ESTADO=INVALID", output)
        self.opener.open.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_network_errors_have_no_traceback_or_secrets_in_command_output(self):
        output = self.command(photocopier_id="21", subnet=SUBNET)
        self.assertIn("ESTADO=NOT_FOUND", output)
        self.assertNotIn("private network diagnostic", output)
        self.assertNotIn("Traceback", output)

    def test_parser_requires_one_selector_and_subnet_and_rejects_ip_and_all(self):
        from .management.commands.recover_printer_ip import Command
        parser = Command().create_parser("manage.py", "recover_printer_ip")
        for args in ([], ["--serial", "x"], ["--subnet", SUBNET],
                     ["--ip", self.device.ip_address, "--subnet", SUBNET],
                     ["--all", "--subnet", SUBNET],
                     ["--id", str(self.device.pk), "--serial", "x", "--subnet", SUBNET]):
            with self.assertRaises(CommandError):
                parser.parse_args(args)
