import csv
import json
from copy import deepcopy
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.db import IntegrityError, connection
from django.test import TestCase
from django.utils import timezone

from .initial_identity import load_inventory, snapshot, evaluate, apply_initial_binding
from .models import PrintingDevice, PrintingDeviceNetworkDetection
from .test_network_discovery import changed_finding, MAC, OTHER_MAC, SUBNET


class InitialIdentityTests(TestCase):
    def setUp(self):
        self.device = PrintingDevice.objects.create(photocopier_id="21", serial_number="SERIAL-21",
            ip_address="10.11.42.249", connection_status="OFFLINE", monitor_evidence={"keep": True})
        self.old = PrintingDeviceNetworkDetection.objects.create(printing_device=self.device,
            detected_ip=self.device.ip_address, detected_mac="", notes="preserve original", is_current=True)
        self.finding = changed_finding(serial="SERIAL-21", serial_source="SNMPV2C", snmp_status="CONFIRMED",
            snmp_error="", identity_verified=True, error="")
        self.before = snapshot(*load_inventory())
        self.baseline = deepcopy(self.before)
        self.live_patch = patch("apps.printing.initial_identity.identify_host", return_value=deepcopy(self.finding))
        self.live = self.live_patch.start()
        self.addCleanup(self.live_patch.stop)

    def evaluate(self):
        return evaluate(self.finding, *load_inventory())

    def apply(self):
        return apply_initial_binding(self.finding, self.baseline)

    def assert_unchanged(self):
        self.assertEqual(snapshot(*load_inventory()), self.before)

    def command(self, **options):
        scan = dict(status="COMPLETE", scanned_hosts=254, findings=[self.finding])
        output = StringIO()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "bindings.csv"
            with patch("apps.printing.management.commands.bind_printer_identity.discover_networks", return_value=[scan]):
                call_command("bind_printer_identity", subnet=[SUBNET], output=str(path), stdout=output, **options)
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
        return rows, output.getvalue()

    def test_explicit_apply_preserves_every_device_field_and_history(self):
        self.assertEqual(self.evaluate()["status"], "PENDING_INITIAL_BINDING")
        rows, output = self.command(apply_bindings=True)
        self.assertIn("VINCULADAS=1", output)
        self.assertEqual(rows[0]["status"], "BOUND")
        self.assertEqual(snapshot(*load_inventory())[0], self.before[0])
        self.old.refresh_from_db()
        self.assertFalse(self.old.is_current)
        self.assertEqual(self.old.notes, "preserve original")
        self.assertEqual(self.old.detected_mac, "")
        new = PrintingDeviceNetworkDetection.objects.get(is_current=True)
        evidence = json.loads(new.notes)
        self.assertEqual(evidence["serial"], "SERIAL-21")
        self.assertEqual(evidence["mac"], MAC)
        self.assertEqual(evidence["ip"], self.finding["ip"])
        self.assertEqual(evidence["printing_device_id"], str(self.device.pk))
        self.assertTrue(evidence["validated_at"])
        self.assertEqual(evidence["result"], "INITIAL_IDENTITY_CONFIRMED")
        self.assertEqual(new.detected_ip, self.finding["ip"])
        self.assertEqual(PrintingDevice.objects.count(), 1)
        self.live.assert_called_once_with(self.finding["ip"], timeout=1)

    def test_dry_run_and_default_never_revalidate_or_write(self):
        for options in ({}, {"dry_run": True}):
            rows, _ = self.command(**options)
            self.assertEqual(rows[0]["status"], "PENDING_INITIAL_BINDING")
            self.assert_unchanged()
        self.live.assert_not_called()

    def test_ip_recovery_apply_is_rejected(self):
        with self.assertRaises(TypeError):
            self.command(apply=True)
        from .management.commands.bind_printer_identity import Command
        parser = Command().create_parser("manage.py", "bind_printer_identity")
        with self.assertRaises(CommandError):
            parser.parse_args(["--subnet", SUBNET, "--apply"])
        self.assert_unchanged()

    def test_modes_cannot_be_combined(self):
        with self.assertRaises(CommandError):
            self.command(apply_bindings=True, dry_run=True)

    def test_duplicate_serial_blocks_even_inactive_record(self):
        PrintingDevice.objects.create(serial_number="SERIAL-21", is_active=False)
        self.assertEqual(self.evaluate()["reason"], "SERIAL_NOT_UNIQUE")

    def test_mac_on_other_historical_device_blocks(self):
        other = PrintingDevice.objects.create(serial_number="OTHER")
        PrintingDeviceNetworkDetection.objects.create(printing_device=other, detected_mac=MAC, is_current=False)
        self.assertEqual(self.evaluate()["reason"], "MAC_ALREADY_ASSOCIATED")

    def test_any_different_historical_mac_blocks(self):
        PrintingDeviceNetworkDetection.objects.create(printing_device=self.device, detected_mac=OTHER_MAC, is_current=False)
        self.assertEqual(self.evaluate()["reason"], "HISTORICAL_IDENTITY_CONFLICT")

    def test_already_confirmed_mac_is_idempotent(self):
        self.old.detected_mac = MAC
        self.old.save()
        self.assertEqual(self.evaluate()["status"], "ALREADY_ASSOCIATED")
        rows, _ = self.command(apply_bindings=True)
        self.assertEqual(rows[0]["status"], "ALREADY_ASSOCIATED")
        self.live.assert_not_called()
        self.assertEqual(PrintingDeviceNetworkDetection.objects.count(), 1)

    def test_existing_device_without_any_detection_can_be_bound(self):
        self.old.delete()
        self.baseline = snapshot(*load_inventory())
        self.assertEqual(self.apply(), "BOUND")
        self.assertEqual(self.device.network_detections.get().detected_mac, MAC)

    def test_inactive_target_and_observed_ip_assigned_elsewhere_block(self):
        PrintingDevice.objects.filter(pk=self.device.pk).update(is_active=False)
        self.assertEqual(self.evaluate()["reason"], "INACTIVE_OR_NON_NETWORK_DEVICE")
        PrintingDevice.objects.filter(pk=self.device.pk).update(is_active=True)
        PrintingDevice.objects.create(serial_number="OTHER", ip_address=self.finding["ip"])
        self.assertEqual(self.evaluate()["reason"], "IP_ALREADY_ASSIGNED")

    def test_incomplete_identity_and_snmp_errors_block(self):
        for changes in ({"serial": ""}, {"mac": ""}, {"identity_verified": False},
                        {"snmp_status": "UNVERIFIED", "snmp_error": "TIMEOUT"},
                        {"snmp_error": "INVALID_BER"}, {"serial_source": "LEXMARK_EWS"},
                        {"error": "NETWORK_IDENTITY_CHANGED"}, {"scan_complete": False}):
            with self.subTest(changes=changes):
                finding = {**self.finding, **changes}
                self.assertEqual(evaluate(finding, *load_inventory())["status"], "BLOCKED")

    def test_live_serial_mac_and_ip_changes_block(self):
        for changes in ({"serial": "OTHER"}, {"mac": OTHER_MAC}, {"ip": "10.11.42.242"},
                        {"identity_verified": False}, {"snmp_status": "UNVERIFIED", "snmp_error": "TIMEOUT"}):
            with self.subTest(changes=changes):
                self.live.return_value = {**self.finding, **changes}
                self.assertEqual(self.apply(), "PHYSICAL_IDENTITY_CHANGED")
                self.assert_unchanged()

    def test_network_exception_is_sanitized(self):
        self.live.side_effect = TimeoutError("secret-community")
        rows, text = self.command(apply_bindings=True)
        self.assertEqual(rows[0]["reason"], "PHYSICAL_REVALIDATION_FAILED")
        self.assertNotIn("secret-community", str(rows) + text)
        self.assert_unchanged()

    def test_concurrent_ip_or_other_field_changes_abort(self):
        for changes in ({"ip_address": "10.11.42.242"}, {"serial_number": "OTHER"}, {"is_active": False}):
            with self.subTest(changes=changes):
                PrintingDevice.objects.filter(pk=self.device.pk).update(**changes)
                self.assertEqual(self.apply(), "INVENTORY_CHANGED")
                self.assertEqual(PrintingDeviceNetworkDetection.objects.count(), 1)
                PrintingDevice.objects.filter(pk=self.device.pk).update(ip_address=self.device.ip_address,
                    serial_number=self.device.serial_number, is_active=True)

    def test_monitoring_timestamp_does_not_block_binding(self):
        PrintingDevice.objects.filter(
            pk=self.device.pk
        ).update(last_checked_at=timezone.now())

        self.assertEqual(self.apply(), "BOUND")
    def test_concurrent_monitored_ip_change_blocks_binding(self):
        PrintingDevice.objects.filter(
            pk=self.device.pk
        ).update(monitored_ip="10.11.42.242")

        self.assertEqual(self.apply(), "INVENTORY_CHANGED")
        self.assertEqual(
            PrintingDeviceNetworkDetection.objects.count(), 1
        )
    def test_concurrent_mac_insertion_aborts(self):
        def concurrent(*args, **kwargs):
            other = PrintingDevice.objects.create(serial_number="OTHER")
            PrintingDeviceNetworkDetection.objects.create(printing_device=other, detected_mac=MAC)
            return deepcopy(self.finding)
        self.live.side_effect = concurrent
        self.assertEqual(self.apply(), "INVENTORY_CHANGED")
        self.assertEqual(self.device.network_detections.count(), 1)

    def test_expired_revalidation_blocks(self):
        with patch("apps.printing.initial_identity.monotonic", side_effect=[1, 12]):
            self.assertEqual(self.apply(), "PHYSICAL_REVALIDATION_EXPIRED")
        self.assert_unchanged()

    def test_detection_creation_failure_rolls_back_history(self):
        with patch("apps.printing.initial_identity.PrintingDeviceNetworkDetection.objects.create", side_effect=IntegrityError):
            with self.assertRaises(IntegrityError):
                self.apply()
        self.assert_unchanged()

    def test_multiple_current_detections_block(self):
        PrintingDeviceNetworkDetection.objects.create(printing_device=self.device)
        self.assertEqual(self.evaluate()["reason"], "MULTIPLE_CURRENT_DETECTIONS")

    def test_duplicate_network_identity_blocks_apply(self):
        scan = dict(status="COMPLETE", scanned_hosts=254, findings=[self.finding, {**self.finding, "ip": "10.11.42.242"}])
        with TemporaryDirectory() as directory, patch(
            "apps.printing.management.commands.bind_printer_identity.discover_networks", return_value=[scan]):
            call_command("bind_printer_identity", subnet=[SUBNET], output=str(Path(directory)/"report.csv"),
                         apply_bindings=True, stdout=StringIO())
        self.live.assert_not_called()
        self.assert_unchanged()

    def test_second_binding_in_batch_uses_only_own_committed_delta(self):
        self.assertEqual(self.apply(), "BOUND")
        other = PrintingDevice.objects.create(serial_number="OTHER")
        # An unrelated concurrent insert must not become trusted by refreshing the baseline.
        self.assertEqual(self.apply(), "INVENTORY_CHANGED")
        self.assertFalse(other.network_detections.exists())

    def test_two_valid_bindings_share_a_batch_without_changing_devices(self):
        other = PrintingDevice.objects.create(serial_number="OTHER", ip_address="10.11.42.248")
        second = {**self.finding, "serial": "OTHER", "mac": OTHER_MAC, "ip": "10.11.42.242"}
        scan = dict(status="COMPLETE", scanned_hosts=254, findings=[self.finding, second])
        self.live.side_effect = [deepcopy(self.finding), deepcopy(second)]
        before_devices = snapshot(*load_inventory())[0]
        with TemporaryDirectory() as directory, patch(
            "apps.printing.management.commands.bind_printer_identity.discover_networks", return_value=[scan]):
            path = Path(directory)/"report.csv"
            call_command("bind_printer_identity", subnet=[SUBNET], output=str(path),
                         apply_bindings=True, stdout=StringIO())
            with path.open(encoding="utf-8-sig", newline="") as stream:
                self.assertEqual([r["status"] for r in csv.DictReader(stream)], ["BOUND", "BOUND"])
        self.assertEqual(snapshot(*load_inventory())[0], before_devices)
        self.assertEqual(other.network_detections.get(is_current=True).detected_mac, OTHER_MAC)

    def test_transaction_rereads_and_locks_all_history(self):
        from . import initial_identity
        with patch("apps.printing.initial_identity.load_inventory", wraps=initial_identity.load_inventory) as load:
            self.assertEqual(self.apply(), "BOUND")
        load.assert_called_once_with(locked=True)

    def test_postgresql_table_lock_precedes_snapshot_and_writes(self):
        statements = []
        def execute(execute, sql, params, many, context):
            statements.append(sql)
            if sql.startswith("LOCK TABLE"):
                self.assertTrue(connection.in_atomic_block)
                return None  # Validate emitted PostgreSQL SQL without executing it on SQLite.
            return execute(sql, params, many, context)
        with connection.execute_wrapper(execute), patch.object(connection, "vendor", "postgresql"):
            self.assertEqual(self.apply(), "BOUND")
        lock_index = next(i for i, sql in enumerate(statements) if sql.startswith("LOCK TABLE"))
        self.assertIn('"printing_printingdevice"', statements[lock_index])
        self.assertIn('"printing_printingdevicenetworkdetection"', statements[lock_index])
        self.assertIn("SHARE ROW EXCLUSIVE MODE", statements[lock_index])
        self.assertFalse(any(sql.startswith(("SELECT", "INSERT", "UPDATE")) for sql in statements[:lock_index]))

    def test_incomplete_scan_prevents_all_bindings(self):
        scan = dict(status="INVALID", scanned_hosts=253, findings=[self.finding])
        with TemporaryDirectory() as directory, patch(
            "apps.printing.management.commands.bind_printer_identity.discover_networks", return_value=[scan]):
            call_command("bind_printer_identity", subnet=[SUBNET], output=str(Path(directory)/"report.csv"),
                         apply_bindings=True, stdout=StringIO())
        self.live.assert_not_called()
        self.assert_unchanged()
