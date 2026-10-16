from copy import deepcopy
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.db import connection, IntegrityError
from django.test import TestCase, SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from .connectivity import effective_status
from .models import PrintingDevice, PrintingDeviceNetworkDetection
from .network_recovery import recovery_result, scan_network_identities
from .recovery_application import RecoveryCandidate, apply_recovery, offline_candidates, claim_automatic_attempt
from .test_network_recovery import EWSResponses

MAC = "00:21:B7:EF:1D:AA"
OTHER_MAC = "00:21:B7:EF:1D:BB"
SUBNET = "10.11.42.0/24"


def scan_result(identities=None, *, subnet=SUBNET):
    return dict(subnet=subnet, status="COMPLETE", scanned_hosts=254, responsive_hosts=len(identities or {}),
                identities=identities or {}, error="", source="LEXMARK_EWS")


def found(ip="10.11.42.241", mac=MAC):
    return recovery_result(scan_result({mac: [{"ip": ip, "hostname": "Lexmark"}]}), mac)


class RecoveryFixtures:
    def setUp(self):
        self.device = PrintingDevice.objects.create(photocopier_id="21", serial_number="RECOVERY-21",
            ip_address="10.11.42.249", connection_status="OFFLINE", supports_network=True,
            monitor_method="TCP", monitored_ip="10.11.42.249", monitor_error="NO_RESPONSE",
            monitor_evidence={"network_port": 9100}, last_checked_at=timezone.now(),
            last_online_at=timezone.now() - timedelta(days=1))
        self.detection = PrintingDeviceNetworkDetection.objects.create(printing_device=self.device,
            detected_ip=self.device.ip_address, detected_mac=MAC, notes="Historial original")

    def snapshot(self):
        return (list(PrintingDevice.objects.order_by("pk").values()),
                list(PrintingDeviceNetworkDetection.objects.order_by("pk").values()))

    def command(self, *, result=None, **options):
        output = StringIO()
        with patch("apps.printing.management.commands.recover_printer_ip.recover_network_identity",
                   return_value=found() if result is None else result):
            call_command("recover_printer_ip", photocopier_id="21", subnet=SUBNET, stdout=output, **options)
        return output.getvalue()

    def candidate(self):
        return RecoveryCandidate.capture(self.device, self.detection)


class RecoveryApplicationTests(RecoveryFixtures, TestCase):
    def test_apply_creates_history_preserves_old_record_and_resets_connectivity(self):
        last_online, checked = self.device.last_online_at, self.device.last_checked_at
        output = self.command(apply=True)
        self.device.refresh_from_db()
        self.detection.refresh_from_db()
        self.assertEqual(self.device.ip_address, "10.11.42.241")
        self.assertFalse(self.detection.is_current)
        self.assertEqual(self.detection.notes, "Historial original")
        current = self.device.network_detections.get(is_current=True)
        self.assertNotEqual(current.pk, self.detection.pk)
        self.assertEqual(current.detected_ip, "10.11.42.241")
        self.assertEqual(current.detected_mac, MAC)
        self.assertEqual(current.detection_source, "LEXMARK_EWS_AUTO_RECOVERY")
        self.assertIn("10.11.42.249", current.notes)
        self.assertIn("10.11.42.241", current.notes)
        self.assertEqual(self.device.connection_status, "UNKNOWN")
        self.assertEqual(effective_status(self.device), "UNKNOWN")
        self.assertIsNone(self.device.monitored_ip)
        self.assertEqual(self.device.monitor_error, "")
        self.assertEqual(self.device.monitor_method, "")
        self.assertEqual(self.device.monitor_evidence, {})
        self.assertEqual(self.device.last_online_at, last_online)
        self.assertEqual(self.device.last_checked_at, checked)
        self.assertIsNone(self.device.last_recovery_attempt_at)  # Manual bypasses cooldown.
        for expected in ("ACTUALIZADO=True", "HISTORIAL_CREADO=True", "IDENTIDAD=CONFIRMED",
                         "IP_ANTERIOR=10.11.42.249", "IP_NUEVA=10.11.42.241"):
            self.assertIn(expected, output)

    def test_without_apply_and_dry_run_are_read_only(self):
        before = self.snapshot()
        for options in ({}, {"dry_run": True}):
            with CaptureQueriesContext(connection) as queries:
                output = self.command(**options)
            self.assertIn("ACTUALIZADO=False", output)
            self.assertEqual(self.snapshot(), before)
            self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))

    def test_apply_and_dry_run_cannot_be_combined(self):
        with self.assertRaises(CommandError):
            self.command(apply=True, dry_run=True)

    def test_same_ip_never_writes_even_with_apply(self):
        before = self.snapshot()
        with CaptureQueriesContext(connection) as queries:
            output = self.command(result=found(self.device.ip_address), apply=True)
        self.assertIn("IP_SIN_CAMBIOS=True", output)
        self.assertIn("ACTUALIZADO=False", output)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))

    def test_nonfound_ambiguous_mismatched_or_invalid_evidence_never_writes(self):
        before = self.snapshot()
        changes = ({"status": "NOT_FOUND"}, {"status": "AMBIGUOUS"}, {"found_mac": OTHER_MAC},
                   {"expected_mac": OTHER_MAC}, {"match_count": 2}, {"found_ip": "hostname"},
                   {"found_ip": "10.11.43.241"}, {"found_ip": "10.11.42.255"},
                   {"scanned_hosts": 253}, {"source": "OTHER"}, {"error": "INCOMPLETE_SCAN"})
        for change in changes:
            output = self.command(result={**found(), **change}, apply=True)
            self.assertIn("ACTUALIZADO=False", output)
            self.assertEqual(self.snapshot(), before)

    def test_new_ip_already_assigned_to_active_printer_is_conflict(self):
        PrintingDevice.objects.create(serial_number="CONFLICT", ip_address="10.11.42.241")
        before = self.snapshot()
        output = self.command(apply=True)
        self.assertIn("IP_ALREADY_ASSIGNED", output)
        self.assertEqual(self.snapshot(), before)

    def test_concurrent_ip_change_aborts_without_writes(self):
        candidate = self.candidate()
        PrintingDevice.objects.filter(pk=self.device.pk).update(ip_address="10.11.42.230")
        before = self.snapshot()
        self.assertEqual(apply_recovery(candidate, found(), subnet=SUBNET)["error"], "DEVICE_CHANGED")
        self.assertEqual(self.snapshot(), before)

    def test_concurrent_detection_edits_replacement_or_extra_current_aborts(self):
        candidate = self.candidate()
        for updates in ({"detected_mac": OTHER_MAC}, {"notes": "Changed"}, {"is_current": False}):
            PrintingDeviceNetworkDetection.objects.filter(pk=self.detection.pk).update(**updates)
            before = self.snapshot()
            self.assertEqual(apply_recovery(candidate, found(), subnet=SUBNET)["error"], "DETECTION_CHANGED")
            self.assertEqual(self.snapshot(), before)
        self.detection.save()
        PrintingDeviceNetworkDetection.objects.create(printing_device=self.device, detected_mac=MAC)
        self.assertEqual(apply_recovery(candidate, found(), subnet=SUBNET)["error"], "DETECTION_CHANGED")

    def test_history_creation_failure_rolls_back_all_changes_and_hides_exception(self):
        before = self.snapshot()
        with patch("apps.printing.recovery_application.PrintingDeviceNetworkDetection.objects.create",
                   side_effect=IntegrityError("SECRET")):
            output = self.command(apply=True)
        self.assertIn("APPLY_FAILED", output)
        self.assertNotIn("SECRET", output)
        self.assertNotIn("Traceback", output)
        self.assertEqual(self.snapshot(), before)

    def test_device_save_failure_rolls_back_new_and_previous_detections(self):
        before = self.snapshot()
        with patch("apps.printing.recovery_application.PrintingDevice.save", side_effect=IntegrityError("SECRET")):
            output = self.command(apply=True)
        self.assertIn("APPLY_FAILED", output)
        self.assertEqual(self.snapshot(), before)

    def test_inactive_device_does_not_apply(self):
        candidate = self.candidate()
        PrintingDevice.objects.filter(pk=self.device.pk).update(is_active=False)
        before = self.snapshot()
        self.assertFalse(apply_recovery(candidate, found(), subnet=SUBNET)["updated"])
        self.assertEqual(self.snapshot(), before)


class AutomaticRecoveryTests(RecoveryFixtures, TestCase):
    def bulk(self, scan=None, **options):
        output = StringIO()
        with patch("apps.printing.management.commands.recover_offline_printers.scan_network_identities",
                   return_value=scan or scan_result({MAC: [{"ip": "10.11.42.241", "hostname": "Lexmark"}]})) as scan_mock:
            call_command("recover_offline_printers", stdout=output, **options)
        return output.getvalue(), scan_mock

    def add_printer(self, ip, *, mac=OTHER_MAC, **kwargs):
        device = PrintingDevice.objects.create(ip_address=ip, connection_status=kwargs.pop("connection_status", "OFFLINE"),
                                               supports_network=True, **kwargs)
        PrintingDeviceNetworkDetection.objects.create(printing_device=device, detected_mac=mac)
        return device

    def test_two_printers_same_subnet_share_one_scan_and_dry_run_has_only_two_queries(self):
        self.add_printer("10.11.42.248")
        before = self.snapshot()
        with CaptureQueriesContext(connection) as queries:
            output, scanner = self.bulk(dry_run=True)
        self.assertEqual(len(queries), 2)
        self.assertEqual(self.snapshot(), before)
        scanner.assert_called_once_with(SUBNET, timeout=1, workers=8)
        self.assertIn("IMPRESORAS_ELEGIBLES=2", output)
        self.assertIn("SUBREDES_ESCANEADAS=1", output)

    def test_default_bulk_is_read_only(self):
        before = self.snapshot()
        output, _ = self.bulk()
        self.assertIn("ACTUALIZADAS=0", output)
        self.assertEqual(self.snapshot(), before)

    def test_only_offline_eligible_printers_are_selected(self):
        self.add_printer("10.11.42.10", connection_status="UNKNOWN", monitor_error="NO_IP")
        self.add_printer("10.11.42.11", connection_status="ONLINE")
        self.add_printer(None)
        self.add_printer("10.11.42.12", monitor_error="DUPLICATE_IP")
        self.add_printer("10.11.42.18", monitor_error="NO_IP")
        self.add_printer("10.11.42.13", is_active=False)
        self.add_printer("10.11.42.14", mac="")
        multiple = self.add_printer("10.11.42.15")
        PrintingDeviceNetworkDetection.objects.create(printing_device=multiple, detected_mac=MAC)
        no_network = self.add_printer("10.11.42.16")
        no_network.supports_network = False
        no_network.save()
        self.add_printer("10.11.42.17")
        self.add_printer("10.11.42.17", is_active=False)
        output, scanner = self.bulk()
        self.assertIn("IMPRESORAS_ELEGIBLES=1", output)
        scanner.assert_called_once()

    def test_apply_bulk_updates_exact_matches_only_and_reserves_all_attempts(self):
        other = self.add_printer("10.11.42.248")
        output, _ = self.bulk(apply=True)
        self.device.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(self.device.ip_address, "10.11.42.241")
        self.assertEqual(other.ip_address, "10.11.42.248")
        self.assertIsNotNone(other.last_recovery_attempt_at)
        self.assertIn("ACTUALIZADAS=1", output)
        self.assertIn("NO_ENCONTRADAS=1", output)
        self.assertEqual(other.network_detections.count(), 1)

    def test_cooldown_records_not_found_attempts_and_blocks_repeated_attempt(self):
        output, _ = self.bulk(scan_result(), apply=True)
        self.assertIn("NO_ENCONTRADAS=1", output)
        self.device.refresh_from_db()
        self.assertIsNotNone(self.device.last_recovery_attempt_at)
        output, scanner = self.bulk(apply=True)
        scanner.assert_not_called()
        self.assertIn("IMPRESORAS_ELEGIBLES=0", output)
        PrintingDevice.objects.filter(pk=self.device.pk).update(last_recovery_attempt_at=timezone.now() - timedelta(minutes=31))
        output, scanner = self.bulk()
        scanner.assert_called_once()

    def test_manual_recovery_bypasses_automatic_cooldown(self):
        self.device.last_recovery_attempt_at = timezone.now()
        self.device.save()
        self.assertIn("ACTUALIZADO=True", self.command(apply=True))

    def test_overlapping_automatic_attempt_can_only_be_claimed_once(self):
        candidate = self.candidate()
        self.assertIsNotNone(claim_automatic_attempt(candidate))
        self.assertIsNone(claim_automatic_attempt(candidate))

    def test_automatic_eligibility_changed_after_discovery_aborts_apply(self):
        candidate = claim_automatic_attempt(self.candidate())
        PrintingDevice.objects.filter(pk=self.device.pk).update(connection_status="ONLINE")
        before = self.snapshot()
        result = apply_recovery(candidate, found(), subnet=SUBNET, automatic=True)
        self.assertEqual(result["error"], "AUTOMATIC_ELIGIBILITY_CHANGED")
        self.assertEqual(self.snapshot(), before)

    def test_changed_attempt_reservation_aborts_apply(self):
        candidate = claim_automatic_attempt(self.candidate())
        PrintingDevice.objects.filter(pk=self.device.pk).update(last_recovery_attempt_at=timezone.now())
        before = self.snapshot()
        result = apply_recovery(candidate, found(), subnet=SUBNET, automatic=True)
        self.assertEqual(result["error"], "AUTOMATIC_ELIGIBILITY_CHANGED")
        self.assertEqual(self.snapshot(), before)

    def test_different_subnets_scanned_once_each_and_limit_is_enforced(self):
        self.add_printer("10.11.43.248")
        output, scanner = self.bulk()
        self.assertEqual(scanner.call_count, 2)
        self.assertEqual({call.args[0] for call in scanner.call_args_list}, {SUBNET, "10.11.43.0/24"})
        output, scanner = self.bulk(limit=1)
        scanner.assert_called_once()
        self.assertIn("IMPRESORAS_ELEGIBLES=1", output)

    def test_incomplete_scan_never_updates_ip_or_history(self):
        scan = scan_result({MAC: [{"ip": "10.11.42.241", "hostname": "Lexmark"}]})
        scan.update(status="INVALID", scanned_hosts=253, error="INCOMPLETE_SCAN")
        output, _ = self.bulk(scan, apply=True)
        self.device.refresh_from_db()
        self.assertEqual(self.device.ip_address, "10.11.42.249")
        self.assertEqual(self.device.network_detections.count(), 1)
        self.assertIn("ERRORES=1", output)

    def test_ambiguous_bulk_never_updates(self):
        scan = scan_result({MAC: [{"ip": "10.11.42.241", "hostname": "a"}, {"ip": "10.11.42.242", "hostname": "b"}]})
        output, _ = self.bulk(scan, apply=True)
        self.assertIn("AMBIGUAS=1", output)
        self.assertIn("ACTUALIZADAS=0", output)

    def test_new_ip_conflict_is_reported_in_bulk(self):
        self.add_printer("10.11.42.241", connection_status="ONLINE")
        output, _ = self.bulk(apply=True)
        self.assertIn("CONFLICTOS=1", output)
        self.assertIn("IP_ALREADY_ASSIGNED", output)

    def test_unexpected_scan_error_does_not_leak_secrets(self):
        output = StringIO()
        with patch("apps.printing.management.commands.recover_offline_printers.scan_network_identities", side_effect=RuntimeError("SECRET")):
            call_command("recover_offline_printers", apply=True, stdout=output)
        self.assertNotIn("SECRET", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())
        self.assertIn("ERRORES=1", output.getvalue())

    def test_invalid_options_abort_before_claim_or_scan(self):
        before = self.snapshot()
        for options in ({"timeout": 4}, {"limit": 0}, {"apply": True, "dry_run": True}):
            with self.assertRaises(CommandError):
                self.bulk(**options)
        self.assertEqual(self.snapshot(), before)


class GroupedDiscoveryTests(EWSResponses, SimpleTestCase):
    def setUp(self):
        self.start_http()

    def test_group_scan_reuses_real_ews_parser_without_expected_mac_and_retains_duplicates(self):
        self.printer("10.11.42.1")
        self.printer("10.11.42.254")
        scan = scan_network_identities(SUBNET, timeout=1, workers=8)
        self.assertEqual(scan["status"], "COMPLETE")
        self.assertEqual(scan["scanned_hosts"], 254)
        self.assertEqual(len(scan["identities"][MAC]), 2)
        self.assertEqual(recovery_result(scan, MAC)["status"], "AMBIGUOUS")
        self.assertEqual(self.opener.open.call_count, 254)

    def test_worker_limit_and_incomplete_scan_are_safe(self):
        self.assertEqual(scan_network_identities(SUBNET, workers=100)["status"], "INVALID")
        self.opener.open.assert_not_called()
        self.responses["10.11.42.1"] = RuntimeError("SECRET")
        scan = scan_network_identities(SUBNET)
        self.assertEqual(scan["status"], "INVALID")
        self.assertEqual(scan["error"], "INCOMPLETE_SCAN")
        self.assertNotIn("SECRET", str(scan))
