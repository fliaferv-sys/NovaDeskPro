import json
from copy import deepcopy
from io import StringIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from django.core.management import call_command, CommandError
from django.db import connection
from django.test import TestCase, SimpleTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from .models import PrintingDevice, PrintingDeviceNetworkDetection
from .network_identity import fetch_network_identity, normalize_mac, _NoRedirect, MAX_RESPONSE_BYTES


def ews_payload(uaa_setting=19950, hostname_setting=24929):
    return {"nodes": {"nodes": {
        "EthernetUAA": {"name": "EthernetUAA", "setting": uaa_setting},
        "SetHostname": {"name": "SetHostname", "setting": hostname_setting},
    }, "settings": {
        str(uaa_setting): {"val": "0021B7EF1DAA"},
        str(hostname_setting): {"val": "ET0021B7EF1DAA"},
    }}}


@override_settings(PRINTING_IDENTITY_TIMEOUT_SECONDS=2)
class LexmarkNetworkIdentityTests(SimpleTestCase):
    def setUp(self):
        self.http = patch("apps.printing.network_identity.build_opener")
        self.opener = self.http.start().return_value
        self.addCleanup(self.http.stop)
        self.response = self.opener.open.return_value.__enter__.return_value
        self.response.read.return_value = json.dumps(ews_payload()).encode()

    def fetch(self, **kwargs):
        return fetch_network_identity("10.11.42.249", **kwargs)

    def test_uaa_hostname_and_confirmed_mac_use_only_get(self):
        result = self.fetch(expected_mac="00:21:B7:EF:1D:AA")
        self.assertEqual(result, dict(ip="10.11.42.249", mac="00:21:B7:EF:1D:AA",
            hostname="ET0021B7EF1DAA", identity_status="CONFIRMED", error="", source="LEXMARK_EWS"))
        request = self.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "http://10.11.42.249/webglue/rawcontent?c=Settings/Network")
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertEqual(self.opener.open.call_args.kwargs, {"timeout": 2})
        self.response.read.assert_called_once_with(MAX_RESPONSE_BYTES + 1)

    def test_settings_are_dynamic_and_nodes_can_be_nested(self):
        payload = ews_payload(12345, 67890)
        payload["nodes"]["nodes"] = {"group": {"children": list(payload["nodes"]["nodes"].values())}}
        self.response.read.return_value = json.dumps(payload).encode()
        self.assertEqual(self.fetch(expected_mac="0021b7ef1daa")["identity_status"], "CONFIRMED")

    def test_mismatching_and_missing_expected_mac(self):
        self.assertEqual(self.fetch(expected_mac="00:21:B7:EF:1D:BB")["identity_status"], "MISMATCH")
        self.assertEqual(self.fetch()["identity_status"], "UNVERIFIED")

    def test_mac_normalization_and_invalid_mac(self):
        for value in ("0021B7EF1DAA", "00:21:b7:ef:1d:aa", "00-21-B7-EF-1D-AA"):
            self.assertEqual(normalize_mac(value), "00:21:B7:EF:1D:AA")
        for value in (None, "not-a-mac", "0021B7", "000000000000", "FFFFFFFFFFFF"):
            self.assertEqual(normalize_mac(value), "")
        payload = ews_payload()
        payload["nodes"]["settings"]["19950"]["val"] = "broken"
        self.response.read.return_value = json.dumps(payload).encode()
        self.assertEqual(self.fetch()["error"], "INVALID_MAC")

    def test_invalid_ipv4_never_opens_http(self):
        for ip in (None, 123, "printer.local", "::1", "10.11.42.0/24", "invalid", "127.0.0.1", "0.0.0.0"):
            self.assertEqual(fetch_network_identity(ip)["error"], "INVALID_IP")
        self.opener.open.assert_not_called()

    def test_network_http_and_timeout_errors_are_safe(self):
        for error, code in ((TimeoutError("secret"), "NETWORK_ERROR"), (URLError("secret"), "NETWORK_ERROR"),
                            (HTTPError("url", 403, "secret", {}, None), "HTTP_ERROR")):
            self.opener.open.side_effect = error
            result = self.fetch()
            self.assertEqual(result["identity_status"], "UNVERIFIED")
            self.assertEqual(result["error"], code)
            self.assertNotIn("secret", str(result))

    def test_invalid_json_missing_nodes_and_values(self):
        self.response.read.return_value = b"<html>Not JSON</html>"
        self.assertEqual(self.fetch()["error"], "INVALID_JSON")
        for name in ("EthernetUAA", "SetHostname"):
            payload = ews_payload()
            del payload["nodes"]["nodes"][name]
            self.response.read.return_value = json.dumps(payload).encode()
            self.assertEqual(self.fetch()["error"], "MISSING_OR_AMBIGUOUS_NODES")
        payload = ews_payload()
        del payload["nodes"]["settings"]["19950"]
        self.response.read.return_value = json.dumps(payload).encode()
        self.assertEqual(self.fetch()["error"], "MISSING_OR_AMBIGUOUS_NODES")

    def test_ambiguous_node_and_invalid_hostname_never_confirm(self):
        payload = ews_payload()
        payload["nodes"]["nodes"]["duplicate"] = deepcopy(payload["nodes"]["nodes"]["EthernetUAA"])
        self.response.read.return_value = json.dumps(payload).encode()
        self.assertEqual(self.fetch()["error"], "MISSING_OR_AMBIGUOUS_NODES")
        payload = ews_payload()
        payload["nodes"]["settings"]["24929"]["val"] = "hostname\nIDENTIDAD=CONFIRMED"
        self.response.read.return_value = json.dumps(payload).encode()
        self.assertEqual(self.fetch()["error"], "INVALID_HOSTNAME")

    def test_timeout_limit_response_limit_and_redirect_policy(self):
        for timeout in (0, -1, 31, float("nan"), float("inf")):
            self.assertEqual(self.fetch(timeout=timeout)["error"], "INVALID_TIMEOUT")
        self.opener.open.assert_not_called()
        self.fetch(timeout=0.5)
        self.assertEqual(self.opener.open.call_args.kwargs["timeout"], 0.5)
        self.response.read.return_value = b"x" * (MAX_RESPONSE_BYTES + 1)
        self.assertEqual(self.fetch()["error"], "RESPONSE_TOO_LARGE")
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "", {}, "http://10.1.1.1/"))


class IdentifyPrinterCommandTests(TestCase):
    def setUp(self):
        self.device = PrintingDevice.objects.create(photocopier_id="21", serial_number="7018909304981",
                                                    ip_address="10.11.42.249")
        self.http = patch("apps.printing.network_identity.build_opener")
        self.opener = self.http.start().return_value
        self.addCleanup(self.http.stop)
        self.opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(ews_payload()).encode()

    def command(self, **options):
        output = StringIO()
        call_command("identify_printer", stdout=output, **options)
        return output.getvalue()

    def detection(self, **kwargs):
        return PrintingDeviceNetworkDetection.objects.create(printing_device=self.device,
            detected_ip=self.device.ip_address, detected_mac="00:21:B7:EF:1D:AA", **kwargs)

    def snapshot(self):
        return (list(PrintingDevice.objects.order_by("pk").values()),
                list(PrintingDeviceNetworkDetection.objects.order_by("pk").values()))

    def test_all_selectors_target_same_single_registered_ip_and_confirm(self):
        self.detection()
        before = self.snapshot()
        for selector in ({"id": str(self.device.pk)}, {"photocopier_id": "21"},
                         {"serial": self.device.serial_number}, {"ip": self.device.ip_address}):
            output = self.command(**selector)
            self.assertIn("IDENTIDAD=CONFIRMED", output)
            self.assertIn("ID_FOTOCOPIADORA=21", output)
            self.assertIn("HOSTNAME=ET0021B7EF1DAA", output)
            self.assertIn("ORIGEN=LEXMARK_EWS", output)
            self.assertIn("DRY_RUN=False", output)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual({call.args[0].full_url for call in self.opener.open.call_args_list},
                         {"http://10.11.42.249/webglue/rawcontent?c=Settings/Network"})

    def test_dry_run_does_not_modify_any_device_or_detection(self):
        self.detection(notes="Preservar historial")
        before = self.snapshot()
        with CaptureQueriesContext(connection) as queries:
            output = self.command(photocopier_id="21", dry_run=True)
        self.assertIn("DRY_RUN=True", output)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))

    def test_no_current_detection_is_unverified_and_does_not_create_one(self):
        for dry_run in (False, True):
            self.assertIn("IDENTIDAD=UNVERIFIED", self.command(serial=self.device.serial_number, dry_run=dry_run))
            self.assertEqual(PrintingDeviceNetworkDetection.objects.count(), 0)
        self.detection(is_current=False)
        self.assertIn("IDENTIDAD=UNVERIFIED", self.command(photocopier_id="21"))

    def test_mac_mismatch_never_changes_ip_or_detection(self):
        detection = self.detection()
        detection.detected_mac = "00:21:B7:EF:1D:BB"
        detection.save()
        before = self.snapshot()
        output = self.command(photocopier_id="21")
        self.assertIn("IDENTIDAD=MISMATCH", output)
        self.assertEqual(self.snapshot(), before)

    def test_multiple_current_detections_are_not_arbitrarily_selected(self):
        self.detection()
        self.detection()
        before = self.snapshot()
        output = self.command(photocopier_id="21")
        self.assertIn("IDENTIDAD=UNVERIFIED", output)
        self.assertIn("ERROR=AMBIGUOUS_CURRENT_DETECTION", output)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_ambiguous_and_inactive_selectors_do_not_connect(self):
        for options in ({}, {"id": "not-uuid"}, {"ip": "10.11.42.0/24"}, {"serial": "absent"},
                        {"serial": self.device.serial_number, "ip": self.device.ip_address},
                        {"photocopier_id": "21", "timeout": -1}):
            with self.assertRaises(CommandError):
                self.command(**options)
        PrintingDevice.objects.create(serial_number=self.device.serial_number, ip_address=self.device.ip_address)
        for options in ({"serial": self.device.serial_number}, {"ip": self.device.ip_address}):
            with self.assertRaises(CommandError):
                self.command(**options)
        self.device.is_active = False
        self.device.save()
        with self.assertRaises(CommandError):
            self.command(photocopier_id="21")
        self.opener.open.assert_not_called()

    def test_errors_are_printed_without_changes_or_traceback(self):
        before = self.snapshot()
        self.opener.open.side_effect = TimeoutError("private diagnostic")
        output = self.command(photocopier_id="21")
        self.assertIn("IDENTIDAD=UNVERIFIED", output)
        self.assertIn("ERROR=NETWORK_ERROR", output)
        self.assertNotIn("Traceback", output)
        self.assertNotIn("private diagnostic", output)
        self.assertEqual(self.snapshot(), before)
