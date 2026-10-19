import csv
from copy import deepcopy
from datetime import timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.db import IntegrityError, connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from .discovery_adapters import LexmarkEWSAdapter
from .models import PrintingDevice, PrintingDeviceNetworkDetection
from .network_reconciliation import load_records, reconcile_findings
from .recovery_application import DiscoveryCandidate, apply_discovery_change
from .test_network_discovery import changed_finding, SUBNET, MAC, OTHER_MAC

SERIAL = "SERIAL-21"


class PhysicalReadContinuityTests(SimpleTestCase):
    def identify(self, ews_results, *, serial=SERIAL, status="CONFIRMED", error=""):
        with patch("apps.printing.discovery_adapters.fetch_network_identity", side_effect=ews_results) as ews, patch(
            "apps.printing.discovery_adapters._device_information", return_value=({}, "DEVICE_INFORMATION_UNAVAILABLE")), patch(
            "apps.printing.discovery_adapters.fetch_printer_serial", return_value={
                "serial": serial, "status": status, "error": error}):
            result = LexmarkEWSAdapter().identify("10.11.42.241", timeout=1)
        return result, ews

    def ews(self, mac=MAC):
        return dict(mac=mac, hostname="Lexmark", error="NO_VALID_EXPECTED_MAC")

    def test_ews_mac_is_rechecked_after_snmp_before_pair_is_accepted(self):
        result, ews = self.identify([self.ews(), self.ews()])
        self.assertTrue(result["identity_verified"])
        self.assertEqual(result["serial"], SERIAL)
        self.assertEqual(result["mac"], MAC)
        self.assertEqual(result["snmp_status"], "CONFIRMED")
        self.assertEqual(ews.call_count, 2)

    def test_ip_changes_from_printer_a_to_b_between_ews_and_snmp_is_conflict(self):
        result, _ = self.identify([self.ews(), self.ews(OTHER_MAC)], serial="SERIAL-B")
        self.assertEqual(result["error"], "NETWORK_IDENTITY_CHANGED")
        self.assertEqual(result["serial"], "")
        self.assertFalse(result["identity_verified"])
        row = reconcile_findings([{**result, "ip": "10.11.42.241", "subnet": SUBNET,
                                   "scan_complete": True}], [], {})[0]
        self.assertEqual(row["status"], "CONFLICT")

    def test_unreachable_ews_after_serial_does_not_confirm_pair(self):
        result, _ = self.identify([self.ews(), dict(mac="", hostname="", error="NETWORK_ERROR")])
        self.assertEqual(result["error"], "NETWORK_IDENTITY_UNVERIFIED")
        self.assertEqual(result["serial"], "")
        self.assertFalse(result["identity_verified"])

    def test_unconfigured_snmp_without_ews_serial_preserves_single_read_behavior(self):
        result, ews = self.identify([self.ews()], serial="", status="UNVERIFIED", error="NOT_CONFIGURED")
        self.assertEqual(result["mac"], MAC)
        self.assertEqual(result["serial"], "")
        self.assertEqual(result["snmp_error"], "NOT_CONFIGURED")
        self.assertTrue(result["supported"])
        self.assertFalse(result["identity_verified"])
        self.assertEqual(ews.call_count, 1)


class InventoryPhysicalRevalidationTests(TestCase):
    def setUp(self):
        self.last_online = timezone.now() - timedelta(days=1)
        self.device = PrintingDevice.objects.create(photocopier_id="21", serial_number=SERIAL,
            ip_address="10.11.42.249", connection_status="OFFLINE", monitored_ip="10.11.42.249",
            monitor_method="TCP", monitor_evidence={"network_port": 9100}, last_online_at=self.last_online)
        self.detection = PrintingDeviceNetworkDetection.objects.create(printing_device=self.device,
            detected_ip=self.device.ip_address, detected_mac=MAC, notes="Conservar historial")
        self.other = PrintingDevice.objects.create(photocopier_id="22", serial_number="SERIAL-22", ip_address="10.11.42.248")
        self.finding = changed_finding(serial=SERIAL, serial_source="SNMPV2C", snmp_status="CONFIRMED",
                                       snmp_error="", identity_verified=True)
        devices, detections = load_records()
        self.candidate = DiscoveryCandidate.capture(self.device, detections[self.device.pk])
        self.row = reconcile_findings([self.finding], devices, detections)[0]
        self.live_patch = patch("apps.printing.recovery_application.identify_host", return_value=deepcopy(self.finding))
        self.live = self.live_patch.start()
        self.addCleanup(self.live_patch.stop)

    def snapshot(self):
        return (list(PrintingDevice.objects.order_by("pk").values()),
                list(PrintingDeviceNetworkDetection.objects.order_by("pk").values()))

    def command(self, *, findings=None, **options):
        output = StringIO()
        with TemporaryDirectory() as directory:
            csv_path = Path(directory) / "discovery.csv"
            scan = dict(subnet=SUBNET, status="COMPLETE", scanned_hosts=254,
                        findings=[self.finding] if findings is None else findings, error="")
            with patch("apps.printing.management.commands.discover_printers_network.discover_networks", return_value=[scan]):
                call_command("discover_printers_network", subnet=[SUBNET], output=str(csv_path), stdout=output, **options)
            text = csv_path.read_text(encoding="utf-8-sig")
            with csv_path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
        return output.getvalue(), rows, text

    def test_apply_revalidates_physical_pair_and_updates_only_authorized_local_fields(self):
        before = self.snapshot()
        original = PrintingDevice.objects.values().get(pk=self.device.pk)
        output, rows, _ = self.command(apply=True, timeout=0.8)
        self.live.assert_called_once_with("10.11.42.241", timeout=0.8)
        self.assertIn("ACTUALIZADAS=1", output)
        after = PrintingDevice.objects.values().get(pk=self.device.pk)
        allowed = {"ip_address", "connection_status", "monitored_ip", "monitor_method", "monitor_error",
                   "monitor_evidence", "updated_at", "last_status_change_at"}
        self.assertTrue({key for key in original if original[key] != after[key]} <= allowed)
        self.assertEqual(after["serial_number"], SERIAL)
        self.assertEqual(after["last_online_at"], self.last_online)
        self.assertEqual(after["connection_status"], "UNKNOWN")
        self.detection.refresh_from_db()
        self.assertFalse(self.detection.is_current)
        self.assertEqual(self.detection.detected_ip, "10.11.42.249")
        self.assertEqual(self.detection.detected_mac, MAC)
        self.assertEqual(self.detection.notes, "Conservar historial")
        current = self.device.network_detections.get(is_current=True)
        self.assertEqual(current.detected_ip, "10.11.42.241")
        self.assertEqual(current.detected_mac, MAC)
        self.assertIn("serial y MAC confirmados", current.notes)
        self.assertEqual(PrintingDevice.objects.count(), 2)
        self.assertEqual(PrintingDevice.objects.values().get(pk=self.other.pk), next(row for row in before[0] if row["id"] == self.other.pk))
        self.assertEqual(rows[0]["ESTADO_SNMP"], "CONFIRMED")
        self.assertEqual(rows[0]["ORIGEN_SERIAL"], "SNMPV2C")

    def test_no_apply_and_dry_run_never_revalidate_or_write(self):
        before = self.snapshot()
        for options in ({}, {"dry_run": True}):
            with CaptureQueriesContext(connection) as queries:
                output, rows, _ = self.command(**options)
            self.assertEqual(len(queries), 2)
            self.assertIn("ACTUALIZADAS=0", output)
            self.assertEqual(self.snapshot(), before)
        self.live.assert_not_called()

    def test_changed_live_serial_mac_or_unverified_pair_aborts_all_writes(self):
        before = self.snapshot()
        for changes in ({"serial": "SERIAL-B"}, {"mac": OTHER_MAC}, {"identity_verified": False},
                        {"error": "SERIAL_SOURCE_CONFLICT"}, {"supported": False}):
            self.live.return_value = {**self.finding, **changes}
            result = apply_discovery_change(self.candidate, self.row)
            self.assertEqual(result["error"], "PHYSICAL_IDENTITY_CHANGED")
            self.assertEqual(self.snapshot(), before)

    def test_original_a_mac_unknown_local_serial_plus_b_serial_cannot_apply(self):
        PrintingDevice.objects.filter(pk=self.device.pk).update(serial_number="")
        self.device.refresh_from_db()
        candidate = DiscoveryCandidate.capture(self.device, [self.detection])
        finding = {**self.row, "serial": "SERIAL-B"}
        before = self.snapshot()
        self.assertEqual(apply_discovery_change(candidate, finding)["error"], "PHYSICAL_SERIAL_REQUIRED")
        self.assertEqual(self.snapshot(), before)
        self.live.assert_not_called()

    def test_missing_confirmed_mac_never_enrolls_one_automatically(self):
        self.detection.delete()
        candidate = DiscoveryCandidate.capture(self.device, [])
        before = self.snapshot()
        self.assertEqual(apply_discovery_change(candidate, self.row)["error"], "CONFIRMED_MAC_REQUIRED")
        self.assertEqual(self.snapshot(), before)
        self.live.assert_not_called()

    def test_timeout_before_apply_does_not_write_or_leak_exception(self):
        self.live.side_effect = TimeoutError("SECRET_COMMUNITY")
        before = self.snapshot()
        output, rows, text = self.command(apply=True)
        self.assertIn("ACTUALIZADAS=0", output)
        self.assertEqual(rows[0]["MOTIVO"], "PHYSICAL_REVALIDATION_FAILED")
        self.assertNotIn("SECRET_COMMUNITY", text + output)
        self.assertEqual(self.snapshot(), before)

    def test_revalidation_expires_if_transaction_waits_too_long(self):
        before = self.snapshot()
        with patch("apps.printing.recovery_application.monotonic", side_effect=[100, 111]):
            result = apply_discovery_change(self.candidate, self.row)
        self.assertEqual(result["error"], "PHYSICAL_REVALIDATION_EXPIRED")
        self.assertEqual(self.snapshot(), before)

    def test_db_identity_change_during_physical_read_is_rechecked_under_lock(self):
        def live(ip, **kwargs):
            PrintingDevice.objects.filter(pk=self.device.pk).update(serial_number="CHANGED")
            return self.finding
        self.live.side_effect = live
        result = apply_discovery_change(self.candidate, self.row)
        self.assertEqual(result["error"], "DEVICE_CHANGED")
        self.assertEqual(self.device.network_detections.count(), 1)
        self.device.refresh_from_db()
        self.assertEqual(self.device.ip_address, "10.11.42.249")

    def test_history_failure_reverts_old_detection_and_inventory_ip(self):
        before = self.snapshot()
        with patch("apps.printing.recovery_application.PrintingDeviceNetworkDetection.objects.create", side_effect=IntegrityError("SECRET")):
            with self.assertRaises(IntegrityError):
                apply_discovery_change(self.candidate, self.row)
        self.assertEqual(self.snapshot(), before)

    def test_confirmed_mac_changed_during_revalidation_is_never_overwritten(self):
        def live(ip, **kwargs):
            PrintingDeviceNetworkDetection.objects.filter(pk=self.detection.pk).update(detected_mac=OTHER_MAC)
            return self.finding
        self.live.side_effect = live
        result = apply_discovery_change(self.candidate, self.row)
        self.assertEqual(result["error"], "DETECTION_CHANGED")
        self.detection.refresh_from_db()
        self.assertEqual(self.detection.detected_mac, OTHER_MAC)
        self.assertTrue(self.detection.is_current)
        self.device.refresh_from_db()
        self.assertEqual(self.device.ip_address, "10.11.42.249")
        self.assertEqual(self.device.network_detections.count(), 1)

    def test_ip_assigned_to_another_record_during_revalidation_aborts(self):
        def live(ip, **kwargs):
            PrintingDevice.objects.filter(pk=self.other.pk).update(ip_address=ip)
            return self.finding
        self.live.side_effect = live
        result = apply_discovery_change(self.candidate, self.row)
        self.assertEqual(result["error"], "IP_ALREADY_ASSIGNED")
        self.device.refresh_from_db()
        self.assertEqual(self.device.ip_address, "10.11.42.249")
        self.assertEqual(self.device.network_detections.count(), 1)

    def test_matched_new_and_conflicting_findings_never_enter_apply(self):
        for data in ({**self.finding, "ip": self.device.ip_address},
                     {**self.finding, "serial": "NEW-SERIAL", "mac": OTHER_MAC},
                     {**self.finding, "mac": OTHER_MAC}):
            before = self.snapshot()
            output, _, _ = self.command(findings=[data], apply=True)
            self.assertIn("ACTUALIZADAS=0", output)
            self.assertEqual(self.snapshot(), before)
        self.live.assert_not_called()

    def test_csv_exports_safe_snmp_failure_and_serial_source(self):
        data = {**self.finding, "snmp_status": "UNVERIFIED", "snmp_error": "TIMEOUT", "serial_source": "LEXMARK_EWS"}
        _, rows, text = self.command(findings=[data], dry_run=True)
        self.assertEqual(rows[0]["ESTADO_SNMP"], "UNVERIFIED")
        self.assertEqual(rows[0]["ERROR_SNMP"], "TIMEOUT")
        self.assertEqual(rows[0]["ORIGEN_SERIAL"], "LEXMARK_EWS")
        self.assertNotIn("PRINTING_SNMP_COMMUNITY", text)
