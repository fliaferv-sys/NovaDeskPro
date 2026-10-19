from copy import deepcopy
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from pyasn1.codec.ber import decoder, encoder
from pysnmp.proto.api import v2c

from .snmp_identity import (fetch_printer_serial, decode_serial_response, build_serial_request,
                            SNMPValidationError, SERIAL_OID, MAX_RESPONSE_BYTES)
from .discovery_adapters import LexmarkEWSAdapter
from .network_reconciliation import load_records, reconcile_findings
from .models import PrintingDevice, PrintingDeviceNetworkDetection
from .test_network_discovery import changed_finding, SUBNET, MAC, OTHER_MAC

COMMUNITY = "unit-test-sensitive-community"
REQUEST_ID = 12346
SERIAL = "7018909304981"


def response_packet(*, request_id=REQUEST_ID, community=COMMUNITY.encode(), version=1,
                    oid=SERIAL_OID, value=None, pdu_class=None, error_status=0, error_index=0, extra=False):
    pdu = (pdu_class or v2c.ResponsePDU)()
    v2c.apiPDU.set_defaults(pdu)
    v2c.apiPDU.set_request_id(pdu, request_id)
    v2c.apiPDU.set_error_status(pdu, error_status)
    v2c.apiPDU.set_error_index(pdu, error_index)
    bindings = [(oid, v2c.OctetString(SERIAL) if value is None else value)]
    if extra:
        bindings.append((oid, v2c.OctetString("EXTRA")))
    v2c.apiPDU.set_varbinds(pdu, bindings)
    message = v2c.Message()
    v2c.apiMessage.set_defaults(message)
    v2c.apiMessage.set_version(message, version)
    v2c.apiMessage.set_community(message, community)
    v2c.apiMessage.set_pdu(message, pdu)
    return encoder.encode(message)


@override_settings(PRINTING_SNMP_COMMUNITY_SECRET=COMMUNITY, PRINTING_SNMP_TIMEOUT_SECONDS=0.5, PRINTING_SNMP_RETRIES=0)
class SNMPSerialReaderTests(SimpleTestCase):
    def setUp(self):
        self.patch_socket = patch("apps.printing.snmp_identity.socket.socket")
        self.socket_factory = self.patch_socket.start()
        self.addCleanup(self.patch_socket.stop)
        self.transport = self.socket_factory.return_value.__enter__.return_value
        self.transport.recv.return_value = response_packet()
        self.random_patch = patch("apps.printing.snmp_identity.secrets.randbelow", return_value=REQUEST_ID - 1)
        self.random_patch.start()
        self.addCleanup(self.random_patch.stop)

    def fetch(self, **kwargs):
        return fetch_printer_serial("10.11.42.241", **kwargs)

    def test_valid_response_returns_physical_serial_with_only_get_and_exact_oid(self):
        result = self.fetch()
        self.assertEqual(result["status"], "CONFIRMED")
        self.assertEqual(result["serial"], SERIAL)
        self.transport.connect.assert_called_once_with(("10.11.42.241", 161))
        self.transport.settimeout.assert_called_once_with(0.5)
        packet = self.transport.send.call_args.args[0]
        message, remainder = decoder.decode(packet, asn1Spec=v2c.Message())
        self.assertFalse(remainder)
        self.assertEqual(message["data"].getName(), "get-request")
        self.assertEqual(int(v2c.apiMessage.get_version(message)), 1)
        pdu = v2c.apiMessage.get_pdu(message)
        self.assertEqual(int(v2c.apiPDU.get_request_id(pdu)), REQUEST_ID)
        bindings = v2c.apiPDU.get_varbinds(pdu)
        self.assertEqual(str(bindings[0][0]), SERIAL_OID)
        self.assertEqual(bindings[0][1].tagSet, v2c.Null().tagSet)
        self.assertNotIn(COMMUNITY, str(result))

    def test_protocol_correlation_status_oid_and_value_types_are_validated(self):
        cases = (({"request_id": REQUEST_ID + 1}, "WRONG_REQUEST_ID"),
                 ({"community": b"other"}, "WRONG_COMMUNITY"), ({"version": 0}, "WRONG_VERSION"),
                 ({"pdu_class": v2c.GetRequestPDU}, "WRONG_PDU"),
                 ({"error_status": 5}, "AGENT_ERROR"), ({"error_index": 1}, "INVALID_ERROR_INDEX"),
                 ({"oid": "1.3.6.1.2.1.1.5.0"}, "WRONG_OID"),
                 ({"value": v2c.Integer32(123)}, "INVALID_VALUE_TYPE"),
                 ({"value": v2c.NoSuchInstance("")}, "INVALID_VALUE_TYPE"),
                 ({"value": v2c.NoSuchObject("")}, "INVALID_VALUE_TYPE"),
                 ({"value": v2c.EndOfMibView("")}, "INVALID_VALUE_TYPE"),
                 ({"extra": True}, "INVALID_VARBINDS"))
        for options, code in cases:
            with self.subTest(options=options):
                self.transport.recv.return_value = response_packet(**options)
                result = self.fetch()
                self.assertEqual(result["serial"], "")
                self.assertEqual(result["error"], code)
                self.assertNotIn(COMMUNITY, str(result))

    def test_invalid_asn1_truncated_trailing_or_binary_text_never_yields_serial(self):
        good = response_packet()
        packets = (b"", b"garbage-" + SERIAL.encode(), good[:-1], good + SERIAL.encode(),
                   b"\x30\x80" + good[2:] + b"\x00\x00", b"\x30\x84\xff\xff\xff\xff", good[:3])
        for packet in packets:
            self.transport.recv.return_value = packet
            result = self.fetch()
            self.assertEqual(result["error"], "INVALID_ASN1")
            self.assertEqual(result["serial"], "")

    def test_valid_definite_long_ber_length_is_accepted(self):
        packet = response_packet()
        self.assertLess(packet[1], 128)
        packet = packet[:1] + b"\x81" + packet[1:]
        self.assertEqual(decode_serial_response(packet, request_id=REQUEST_ID, community=COMMUNITY.encode()), SERIAL)

    def test_invalid_serial_control_characters_nonascii_empty_or_oversized_rejected(self):
        for raw in (b"", b" ", b"N/A", b"unknown", b"SERIAL\x00", b"bad\nserial", b"\xffABC", b"X" * 151):
            self.transport.recv.return_value = response_packet(value=v2c.OctetString(raw))
            result = self.fetch()
            self.assertEqual(result["error"], "INVALID_SERIAL")
            self.assertEqual(result["serial"], "")

    def test_response_size_is_bounded(self):
        self.transport.recv.return_value = b"x" * (MAX_RESPONSE_BYTES + 1)
        self.assertEqual(self.fetch()["error"], "INVALID_ASN1")
        self.transport.recv.assert_called_once_with(MAX_RESPONSE_BYTES + 1)

    def test_timeout_and_retries_are_bounded(self):
        self.transport.recv.side_effect = TimeoutError(COMMUNITY)
        result = self.fetch(retries=1)
        self.assertEqual(result["error"], "TIMEOUT")
        self.assertEqual(self.transport.send.call_count, 2)
        self.assertNotIn(COMMUNITY, str(result))
        self.transport.send.reset_mock()
        self.transport.recv.side_effect = [TimeoutError(), response_packet()]
        self.assertEqual(self.fetch(retries=1)["serial"], SERIAL)
        self.assertEqual(self.transport.send.call_count, 2)

    def test_invalid_configuration_ipv4_and_disabled_reader_do_not_open_socket(self):
        for ip in (None, "hostname", "10.11.42.0/24", "::1", "127.0.0.1"):
            self.assertEqual(fetch_printer_serial(ip)["error"], "INVALID_IP")
        for options in ({"timeout": 0}, {"timeout": 4}, {"timeout": float("nan")}, {"retries": 2}, {"retries": -1}):
            self.assertEqual(self.fetch(**options)["error"], "INVALID_CONFIGURATION")
        with override_settings(PRINTING_SNMP_COMMUNITY_SECRET=""):
            self.assertEqual(self.fetch()["error"], "NOT_CONFIGURED")
        self.socket_factory.assert_not_called()

    def test_timeout_uses_smaller_of_discovery_budget_and_snmp_setting(self):
        self.fetch(timeout=1)
        self.transport.settimeout.assert_called_with(0.5)
        self.fetch(timeout=0.2)
        self.transport.settimeout.assert_called_with(0.2)

    def test_transport_and_dependency_errors_hide_sensitive_details(self):
        self.transport.connect.side_effect = OSError(COMMUNITY)
        result = self.fetch()
        self.assertEqual(result["error"], "NETWORK_ERROR")
        self.assertNotIn(COMMUNITY, str(result))
        with patch("apps.printing.snmp_identity.build_serial_request", side_effect=ImportError(COMMUNITY)):
            result = self.fetch()
        self.assertEqual(result["error"], "DEPENDENCY_UNAVAILABLE")
        self.assertNotIn(COMMUNITY, str(result))

    def test_django_technical_settings_report_redacts_community(self):
        from django.views.debug import SafeExceptionReporterFilter
        redacted = SafeExceptionReporterFilter().get_safe_settings()
        self.assertNotIn(COMMUNITY, str(redacted))


class SNMPDiscoveryAdapterTests(SimpleTestCase):
    def setUp(self):
        self.ews = patch("apps.printing.discovery_adapters.fetch_network_identity", return_value={
            "mac": MAC, "hostname": "ET0021B7EF1DAA", "error": "NO_VALID_EXPECTED_MAC"})
        self.info = patch("apps.printing.discovery_adapters._device_information", return_value=({}, "DEVICE_INFORMATION_UNAVAILABLE"))
        self.snmp = patch("apps.printing.discovery_adapters.fetch_printer_serial", return_value={
            "serial": SERIAL, "status": "CONFIRMED", "error": ""})
        self.ews_mock = self.ews.start()
        self.info_mock = self.info.start()
        self.snmp_mock = self.snmp.start()
        for patcher in (self.ews, self.info, self.snmp):
            self.addCleanup(patcher.stop)

    def test_snmp_enriches_serial_only_after_ews_and_preserves_ethernet_mac(self):
        result = LexmarkEWSAdapter().identify("10.11.42.241", timeout=1)
        self.assertEqual(result["serial"], SERIAL)
        self.assertEqual(result["serial_source"], "SNMPV2C")
        self.assertEqual(result["mac"], MAC)
        self.assertEqual(result["source"], "LEXMARK_EWS")
        self.snmp_mock.assert_called_once_with("10.11.42.241", timeout=1)

    def test_ews_failure_generic_http_or_manufacturer_conflict_never_invokes_snmp(self):
        for response in ({"mac": "", "hostname": "", "error": "NETWORK_ERROR"},
                         {"mac": "", "hostname": "", "error": "INVALID_JSON"}):
            self.ews_mock.return_value = response
            LexmarkEWSAdapter().identify("10.11.42.241", timeout=1)
        self.ews_mock.return_value = {"mac": MAC, "hostname": "Lexmark", "error": ""}
        self.info_mock.return_value = ({"manufacturer": "Other"}, "")
        LexmarkEWSAdapter().identify("10.11.42.241", timeout=1)
        self.snmp_mock.assert_not_called()

    def test_snmp_errors_preserve_ews_data_without_inventing_serial(self):
        for code in ("TIMEOUT", "INVALID_ASN1", "WRONG_REQUEST_ID", "NOT_CONFIGURED"):
            self.snmp_mock.return_value = {"serial": "", "status": "UNVERIFIED", "error": code}
            result = LexmarkEWSAdapter().identify("10.11.42.241", timeout=1)
            self.assertEqual(result["serial"], "")
            self.assertEqual(result["mac"], MAC)
            self.assertTrue(result["supported"])
        self.info_mock.return_value = ({"serial": "KNOWN-EWS"}, "")
        self.assertEqual(LexmarkEWSAdapter().identify("10.11.42.241", timeout=1)["serial"], "KNOWN-EWS")

    def test_ews_snmp_serial_contradiction_is_explicitly_blocked(self):
        self.info_mock.return_value = ({"serial": "DIFFERENT-EWS"}, "")
        result = LexmarkEWSAdapter().identify("10.11.42.241", timeout=1)
        self.assertEqual(result["error"], "SERIAL_SOURCE_CONFLICT")


class SNMPReconciliationTests(TestCase):
    def setUp(self):
        self.device = PrintingDevice.objects.create(serial_number=SERIAL, photocopier_id="21", ip_address="10.11.42.241")

    def reconcile(self, findings):
        devices, detections = load_records()
        return reconcile_findings(findings, devices, detections)

    def physical_finding(self, **kwargs):
        return changed_finding(serial=SERIAL, serial_source="SNMPV2C", **kwargs)

    def test_physical_serial_resolves_existing_printer_without_matching_by_ip_alone(self):
        row = self.reconcile([self.physical_finding()])[0]
        self.assertEqual(row["status"], "MATCHED")
        self.assertEqual(row["device_id"], str(self.device.pk))
        row = self.reconcile([changed_finding(serial="", mac=OTHER_MAC)])[0]
        self.assertEqual(row["status"], "CONFLICT")
        self.assertEqual(row["reason"], "IP_ALREADY_ASSIGNED")
        self.assertEqual(self.device.network_detections.count(), 0)

    def test_duplicate_serial_in_database_or_on_network_is_ambiguous(self):
        other = PrintingDevice.objects.create(serial_number=SERIAL)
        self.assertEqual(self.reconcile([self.physical_finding()])[0]["status"], "AMBIGUOUS")
        other.delete()
        rows = self.reconcile([self.physical_finding(), self.physical_finding(ip="10.11.42.242", mac=OTHER_MAC)])
        self.assertTrue(all(row["status"] == "AMBIGUOUS" for row in rows))

    def test_known_mac_changes_or_serial_sources_disagree_are_conflicts(self):
        PrintingDeviceNetworkDetection.objects.create(printing_device=self.device, detected_mac=OTHER_MAC)
        self.assertEqual(self.reconcile([self.physical_finding()])[0]["reason"], "STORED_IDENTITY_DISAGREES")
        self.assertEqual(self.reconcile([self.physical_finding(error="SERIAL_SOURCE_CONFLICT")])[0]["reason"], "SERIAL_SOURCE_CONFLICT")

    def test_serial_and_mac_pointing_at_different_records_conflict(self):
        other = PrintingDevice.objects.create(serial_number="OTHER-SERIAL")
        PrintingDeviceNetworkDetection.objects.create(printing_device=other, detected_mac=MAC)
        self.assertEqual(self.reconcile([self.physical_finding()])[0]["reason"], "SERIAL_MAC_DISAGREE")

    def test_new_serial_does_not_allow_automatic_mac_enrollment_on_ip_change(self):
        row = self.reconcile([self.physical_finding(ip="10.11.42.242")])[0]
        self.assertEqual(row["status"], "CONFLICT")
        self.assertEqual(row["reason"], "MAC_NOT_PREVIOUSLY_CONFIRMED")

    def test_duplicate_mac_in_local_detections_and_network_is_ambiguous(self):
        PrintingDeviceNetworkDetection.objects.create(printing_device=self.device, detected_mac=MAC)
        other = PrintingDevice.objects.create(serial_number="OTHER-SERIAL")
        PrintingDeviceNetworkDetection.objects.create(printing_device=other, detected_mac=MAC)
        self.assertEqual(self.reconcile([self.physical_finding()])[0]["status"], "AMBIGUOUS")
        other.delete()
        rows = self.reconcile([self.physical_finding(), changed_finding(
            ip="10.11.42.242", serial="OTHER-SERIAL", serial_source="SNMPV2C")])
        self.assertTrue(all(row["status"] == "AMBIGUOUS" for row in rows))

    def test_apply_changed_ip_without_previously_confirmed_mac_is_blocked(self):
        finding = self.physical_finding(ip="10.11.42.242", subnet=SUBNET, scan_complete=True)
        scan = dict(subnet=SUBNET, status="COMPLETE", scanned_hosts=254, findings=[finding], error="")
        before = PrintingDevice.objects.values().get(pk=self.device.pk)
        with TemporaryDirectory() as directory:
            with patch("apps.printing.management.commands.discover_printers_network.discover_networks", return_value=[scan]):
                call_command("discover_printers_network", subnet=[SUBNET], apply=True,
                             output=str(Path(directory) / "blocked.csv"), stdout=StringIO())
        self.assertEqual(PrintingDevice.objects.values().get(pk=self.device.pk), before)
        self.assertEqual(self.device.network_detections.count(), 0)

    def test_apply_with_same_ip_never_writes_mac_or_creates_devices_and_csv_has_no_secret(self):
        finding = self.physical_finding(subnet=SUBNET, scan_complete=True)
        scan = dict(subnet=SUBNET, status="COMPLETE", scanned_hosts=254, findings=[finding], error="")
        with TemporaryDirectory() as directory:
            output = Path(directory) / "snmp-discovery.csv"
            with patch("apps.printing.management.commands.discover_printers_network.discover_networks", return_value=[scan]):
                call_command("discover_printers_network", subnet=[SUBNET], apply=True, output=str(output), stdout=StringIO())
            self.assertIn(SERIAL, output.read_text(encoding="utf-8-sig"))
            self.assertNotIn(COMMUNITY, output.read_text(encoding="utf-8-sig"))
        self.assertEqual(self.device.network_detections.count(), 0)
        self.assertEqual(PrintingDevice.objects.count(), 1)


@override_settings(PRINTING_SNMP_COMMUNITY_SECRET=COMMUNITY, PRINTING_SNMP_TIMEOUT_SECONDS=0.5,
                   PRINTING_SNMP_RETRIES=0)
class SNMPEndToEndTests(TestCase):
    def test_real_ber_reader_enriches_adapter_and_matches_existing_serial_without_writes(self):
        device = PrintingDevice.objects.create(serial_number=SERIAL, ip_address="10.11.42.241")
        with patch("apps.printing.discovery_adapters.fetch_network_identity", return_value={
                "mac": MAC, "hostname": "ET0021B7EF1DAA", "error": "NO_VALID_EXPECTED_MAC"}), patch(
                "apps.printing.discovery_adapters._device_information", return_value=({}, "DEVICE_INFORMATION_UNAVAILABLE")), patch(
                "apps.printing.snmp_identity.secrets.randbelow", return_value=REQUEST_ID - 1), patch(
                "apps.printing.snmp_identity.socket.socket") as socket_mock:
            socket_mock.return_value.__enter__.return_value.recv.return_value = response_packet()
            result = LexmarkEWSAdapter().identify(device.ip_address, timeout=1)
        self.assertEqual(result["serial"], SERIAL)
        self.assertEqual(result["mac"], MAC)
        result.update(subnet=SUBNET, scan_complete=True)
        devices, detections = load_records()
        rows = reconcile_findings([result], devices, detections)
        self.assertEqual(rows[0]["status"], "MATCHED")
        self.assertEqual(rows[0]["device_id"], str(device.pk))
        self.assertEqual(PrintingDeviceNetworkDetection.objects.count(), 0)
