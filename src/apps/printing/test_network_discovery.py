import csv
import json
from copy import deepcopy
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock, Event
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.parse import urlsplit

from django.core.management import call_command, CommandError
from django.db import connection, IntegrityError
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext

from .models import PrintingDevice, PrintingDeviceNetworkDetection
from .discovery_adapters import LexmarkEWSAdapter
from .network_map import NETWORKS, authorized_network, select_networks
from .network_discovery import discover_networks, discover_subnet
from .network_reconciliation import load_records, reconcile_findings
from .recovery_application import DiscoveryCandidate, apply_discovery_change
from .test_network_identity import ews_payload

MAC = "00:21:B7:EF:1D:AA"
OTHER_MAC = "00:21:B7:EF:1D:BB"
SUBNET = "10.11.42.0/24"


def finding(**kwargs):
    return dict(ip="10.11.42.241", mac=MAC, hostname="ET0021B7EF1DAA", manufacturer="Lexmark",
                model="MX622", serial="", supported=True, source="LEXMARK_EWS", error="",
                subnet=SUBNET, site="VILLA_ELISA", sector="Informática / Enfermería", scan_complete=True, **kwargs)


def changed_finding(**kwargs):
    result = finding()
    result.update(kwargs)
    return result


def information_payload(**values):
    nodes, settings = {}, {}
    for index, (name, value) in enumerate(values.items(), 100):
        nodes[name] = {"name": name, "setting": index}
        settings[str(index)] = {"val": value}
    return {"nodes": {"nodes": nodes, "settings": settings}}


class AuthorizedMapTests(SimpleTestCase):
    def test_sites_and_pending_networks_are_explicit(self):
        self.assertEqual(len(NETWORKS), 29)
        self.assertEqual(len(select_networks(site="VILLA_ELISA")), 21)
        self.assertEqual(len(select_networks(site="OFICINA_CENTRAL")), 8)
        self.assertEqual(authorized_network("10.16.32.0/24").sector, "Piso 1")
        self.assertEqual(authorized_network("10.20.42.0/24").sector, "Ñu Guazú")
        for octet in range(22, 26):
            self.assertEqual(authorized_network(f"10.{octet}.42.0/24").sector, "PENDIENTE_CONFIRMAR")
        self.assertEqual(len(select_networks(subnets=[SUBNET, SUBNET])), 1)

    def test_unauthorized_core_networks_large_ranges_and_unlisted_floors_rejected_before_http(self):
        with patch("apps.printing.network_discovery.identify_host") as probe:
            for subnet in ("10.0.0.0/24", "10.1.0.0/24", "10.0.0.0/8", "10.11.0.0/16",
                           "10.13.32.0/24", "10.11.42.1/24", "2001:db8::/24"):
                with self.assertRaises(ValueError):
                    discover_networks([SUBNET, subnet])
        probe.assert_not_called()


class LexmarkAdapterTests(SimpleTestCase):
    def setUp(self):
        self.network_patch = patch("apps.printing.network_identity.build_opener")
        self.info_patch = patch("apps.printing.discovery_adapters.build_opener")
        self.network = self.network_patch.start().return_value
        self.info = self.info_patch.start().return_value
        self.addCleanup(self.network_patch.stop)
        self.addCleanup(self.info_patch.stop)
        self.network.open.return_value.__enter__.return_value.read.return_value = json.dumps(ews_payload()).encode()
        self.info.open.return_value.__enter__.return_value.read.return_value = json.dumps(information_payload(
            Manufacturer="Lexmark", ModelName="MX622ADHE", SerialNumber="7018909304981")).encode()

    def test_lexmark_extracts_dynamic_serial_and_metadata_with_only_get(self):
        result = LexmarkEWSAdapter().identify("10.11.42.241", timeout=1)
        self.assertTrue(result["supported"])
        self.assertEqual(result["serial"], "7018909304981")
        self.assertEqual(result["model"], "MX622ADHE")
        self.assertEqual(result["manufacturer"], "Lexmark")
        self.assertEqual(result["mac"], MAC)
        for opener in (self.network, self.info):
            request = opener.open.call_args.args[0]
            self.assertEqual(request.get_method(), "GET")
            self.assertIsNone(request.data)
            self.assertEqual(urlsplit(request.full_url).hostname, "10.11.42.241")
        self.assertIn("c=DeviceInformation", self.info.open.call_args.args[0].full_url)

    def test_missing_information_retains_mac_but_never_invents_serial(self):
        self.info.open.side_effect = HTTPError("url", 404, "SECRET", {}, None)
        result = LexmarkEWSAdapter().identify("10.11.42.241", timeout=1)
        self.assertTrue(result["supported"])
        self.assertEqual(result["serial"], "")
        self.assertEqual(result["model"], "")
        self.assertNotIn("SECRET", str(result))

    def test_unknown_payload_does_not_supply_guessed_serial(self):
        self.info.open.return_value.__enter__.return_value.read.return_value = b'{"serial":"untrusted","model":"unknown"}'
        result = LexmarkEWSAdapter().identify("10.11.42.241", timeout=1)
        self.assertEqual(result["serial"], "")

    def test_generic_http_host_is_unidentified_not_lexmark(self):
        self.network.open.return_value.__enter__.return_value.read.return_value = b"<html>Generic HTTP</html>"
        result = LexmarkEWSAdapter().identify("10.11.42.241", timeout=1)
        self.assertFalse(result["supported"])
        self.assertEqual(result["manufacturer"], "")
        self.info.open.assert_not_called()

    def test_manufacturer_contradiction_is_not_identified(self):
        self.info.open.return_value.__enter__.return_value.read.return_value = json.dumps(information_payload(
            Manufacturer="OtherVendor", SerialNumber="same-looking-serial")).encode()
        result = LexmarkEWSAdapter().identify("10.11.42.241", timeout=1)
        self.assertFalse(result["supported"])
        self.assertEqual(result["error"], "MANUFACTURER_CONFLICT")

    def test_network_failure_is_safe_and_discarded(self):
        self.network.open.side_effect = TimeoutError("SECRET")
        self.assertIsNone(LexmarkEWSAdapter().identify("10.11.42.241", timeout=1))


class DiscoveryScopeTests(SimpleTestCase):
    def test_subnet_is_scanned_once_with_exact_usable_hosts(self):
        with patch("apps.printing.network_discovery.identify_host", return_value=None) as probe:
            scans = discover_networks([SUBNET, SUBNET], workers=1)
        self.assertEqual(len(scans), 1)
        self.assertEqual(probe.call_count, 254)
        self.assertEqual({call.args[0] for call in probe.call_args_list}, {f"10.11.42.{i}" for i in range(1, 255)})

    def test_concurrency_is_bounded_and_worker_options_are_validated(self):
        lock, pause = Lock(), Event()
        active = maximum = 0

        def probe(ip, **kwargs):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            pause.wait(0.001)
            with lock:
                active -= 1
            return None

        with patch("apps.printing.network_discovery.identify_host", side_effect=probe):
            scan = discover_subnet(SUBNET, workers=4)
        self.assertEqual(scan["status"], "COMPLETE")
        self.assertLessEqual(maximum, 4)
        self.assertGreater(maximum, 1)
        for workers in (0, 9, 100):
            with self.assertRaises(ValueError):
                discover_subnet(SUBNET, workers=workers)

    def test_incomplete_scan_marks_every_finding_unusable_without_exposing_errors(self):
        def probe(ip, **kwargs):
            if ip.endswith(".1"):
                return changed_finding(ip=ip)
            raise RuntimeError("SECRET")
        with patch("apps.printing.network_discovery.identify_host", side_effect=probe):
            scan = discover_subnet(SUBNET, workers=1)
        self.assertEqual(scan["status"], "INVALID")
        self.assertFalse(scan["findings"][0]["scan_complete"])
        self.assertNotIn("SECRET", str(scan))


class ReconciliationFixtures:
    def setUp(self):
        self.device = PrintingDevice.objects.create(photocopier_id="21", serial_number="SERIAL-21", ip_address="10.11.42.249")
        self.detection = PrintingDeviceNetworkDetection.objects.create(printing_device=self.device, detected_mac=MAC,
                                                                       detected_ip=self.device.ip_address)

    def rows(self, findings):
        devices, detections = load_records()
        with self.assertNumQueries(0):
            return reconcile_findings(findings, devices, detections)


class ReconciliationTests(ReconciliationFixtures, TestCase):
    def test_exact_serial_and_mac_match_without_ip_as_identity(self):
        for data in (changed_finding(serial="SERIAL-21", mac="", ip=self.device.ip_address),
                     changed_finding(ip=self.device.ip_address)):
            row = self.rows([data])[0]
            self.assertEqual(row["status"], "MATCHED")
            self.assertEqual(row["device_id"], str(self.device.pk))
        self.assertEqual(self.rows([finding()])[0]["status"], "IP_CHANGED")

    def test_new_device_and_generic_host(self):
        self.assertEqual(self.rows([changed_finding(mac=OTHER_MAC)])[0]["status"], "NEW_DEVICE")
        self.assertEqual(self.rows([changed_finding(supported=False, mac="")])[0]["status"], "UNIDENTIFIED")
        self.assertEqual(self.rows([changed_finding(mac="", serial="")])[0]["status"], "UNIDENTIFIED")

    def test_duplicate_local_and_network_identities_are_ambiguous(self):
        other = PrintingDevice.objects.create(serial_number="SERIAL-21")
        self.assertEqual(self.rows([changed_finding(serial="SERIAL-21")])[0]["status"], "AMBIGUOUS")
        other.delete()
        rows = self.rows([finding(), changed_finding(ip="10.11.42.242")])
        self.assertTrue(all(row["status"] == "AMBIGUOUS" for row in rows))

    def test_serial_mac_contradictions_are_conflicts(self):
        other = PrintingDevice.objects.create(serial_number="OTHER-SERIAL")
        data = changed_finding(serial=other.serial_number)
        self.assertEqual(self.rows([data])[0]["status"], "CONFLICT")
        self.assertEqual(self.rows([changed_finding(serial="SERIAL-21", mac=OTHER_MAC)])[0]["status"], "CONFLICT")
        self.assertEqual(self.rows([changed_finding(serial="UNKNOWN-SERIAL")])[0]["status"], "CONFLICT")

    def test_ip_occupied_incomplete_and_inactive_records_do_not_update(self):
        other = PrintingDevice.objects.create(ip_address="10.11.42.241")
        self.assertEqual(self.rows([finding()])[0]["status"], "CONFLICT")
        other.delete()
        self.assertEqual(self.rows([changed_finding(scan_complete=False)])[0]["status"], "CONFLICT")
        self.device.is_active = False
        self.device.save()
        self.assertEqual(self.rows([finding()])[0]["status"], "CONFLICT")

    def test_load_and_reconcile_many_hosts_use_two_queries_total(self):
        findings = [changed_finding(ip=f"10.11.42.{i}", mac=OTHER_MAC) for i in range(1, 255)]
        with self.assertNumQueries(2):
            devices, detections = load_records()
            reconcile_findings(findings, devices, detections)


class DiscoveryCommandTests(ReconciliationFixtures, TestCase):
    def setUp(self):
        super().setUp()
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "discovery.csv"

    def snapshot(self):
        return (list(PrintingDevice.objects.order_by("pk").values()),
                list(PrintingDeviceNetworkDetection.objects.order_by("pk").values()))

    def run_command(self, findings=None, **options):
        findings = [finding()] if findings is None else findings
        scan = dict(subnet=SUBNET, site="VILLA_ELISA", sector="Informática", status="COMPLETE", scanned_hosts=254,
                    findings=findings, error="")
        output = StringIO()
        with patch("apps.printing.management.commands.discover_printers_network.discover_networks", return_value=[scan]) as scanner:
            call_command("discover_printers_network", subnet=[SUBNET], output=str(self.output), stdout=output, **options)
        return output.getvalue(), scanner

    def test_dry_run_has_no_database_writes_and_csv_headers_and_values_are_correct(self):
        before = self.snapshot()
        with CaptureQueriesContext(connection) as queries:
            output, scanner = self.run_command(dry_run=True)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(queries), 2)
        self.assertIn("IP_CHANGED=1", output)
        self.assertIn("ACTUALIZADAS=0", output)
        with self.output.open(encoding="utf-8-sig", newline="") as report:
            rows = list(csv.DictReader(report))
        self.assertEqual(rows[0]["IP"], "10.11.42.241")
        self.assertEqual(rows[0]["PRINTING_DEVICE_ID"], str(self.device.pk))
        self.assertEqual(rows[0]["SEDE"], "VILLA_ELISA")
        self.assertEqual(rows[0]["ESTADO_CONCILIACION"], "IP_CHANGED")

    def test_apply_updates_only_existing_ip_and_preserves_history_and_institutional_fields(self):
        before = PrintingDevice.objects.values().get(pk=self.device.pk)
        output, _ = self.run_command(apply=True)
        self.device.refresh_from_db()
        self.detection.refresh_from_db()
        after = PrintingDevice.objects.values().get(pk=self.device.pk)
        self.assertIn("ACTUALIZADAS=1", output)
        self.assertFalse(self.detection.is_current)
        self.assertEqual(self.device.ip_address, "10.11.42.241")
        self.assertEqual(self.device.connection_status, "UNKNOWN")
        self.assertIsNone(self.device.monitored_ip)
        current = self.device.network_detections.get(is_current=True)
        self.assertEqual(current.detection_source, "LEXMARK_EWS_DISCOVERY")
        allowed = {"ip_address", "connection_status", "monitored_ip", "monitor_error", "monitor_method",
                   "monitor_evidence", "updated_at", "last_status_change_at"}
        self.assertTrue({key for key in before if before[key] != after[key]} <= allowed)
        self.assertEqual(PrintingDevice.objects.count(), 1)

    def test_serial_only_match_with_no_detection_uses_same_history_write_path(self):
        self.detection.delete()
        output, _ = self.run_command([changed_finding(serial="SERIAL-21")], apply=True)
        self.assertIn("ACTUALIZADAS=1", output)
        self.assertEqual(self.device.network_detections.filter(is_current=True).count(), 1)

    def test_new_matched_unidentified_and_ambiguous_findings_never_write(self):
        cases = ([changed_finding(mac=OTHER_MAC)], [changed_finding(ip=self.device.ip_address)],
                 [changed_finding(supported=False, mac="")], [finding(), changed_finding(ip="10.11.42.242")])
        for findings in cases:
            before = self.snapshot()
            output, _ = self.run_command(findings, apply=True, overwrite=True)
            self.assertIn("ACTUALIZADAS=0", output)
            self.assertEqual(self.snapshot(), before)

    def test_existing_output_requires_explicit_overwrite_before_network_or_updates(self):
        self.output.write_text("KEEP", encoding="utf-8")
        before = self.snapshot()
        with patch("apps.printing.management.commands.discover_printers_network.discover_networks") as scanner:
            with self.assertRaises(CommandError):
                self.run_command(apply=True)
            scanner.assert_not_called()
        self.assertEqual(self.output.read_text(), "KEEP")
        self.assertEqual(self.snapshot(), before)

    def test_pending_network_can_be_scanned_and_never_assigns_location(self):
        before = self.snapshot()
        with patch("apps.printing.network_discovery.identify_host", return_value=None):
            scan = discover_subnet("10.22.42.0/24", workers=1)
        self.assertEqual(scan["sector"], "PENDIENTE_CONFIRMAR")
        self.assertEqual(self.snapshot(), before)

    def test_apply_failure_rolls_back_history_and_hides_exception(self):
        before = self.snapshot()
        with patch("apps.printing.recovery_application.PrintingDevice.save", side_effect=IntegrityError("SECRET")):
            output, _ = self.run_command(apply=True)
        self.assertIn("ERRORES=1", output)
        self.assertNotIn("SECRET", output)
        self.assertEqual(self.snapshot(), before)

    def test_changed_detection_and_device_after_scan_abort_transaction(self):
        devices, detections = load_records()
        candidate = DiscoveryCandidate.capture(devices[0], detections[self.device.pk])
        row = reconcile_findings([finding()], devices, detections)[0]
        PrintingDeviceNetworkDetection.objects.filter(pk=self.detection.pk).update(notes="Changed")
        before = self.snapshot()
        self.assertEqual(apply_discovery_change(candidate, row)["error"], "DETECTION_CHANGED")
        self.assertEqual(self.snapshot(), before)
        PrintingDevice.objects.filter(pk=self.device.pk).update(ip_address="10.11.42.230")
        self.assertEqual(apply_discovery_change(candidate, row)["error"], "DEVICE_CHANGED")

    def test_csv_formula_cells_are_escaped_and_invalid_scope_options_abort(self):
        self.run_command([changed_finding(hostname="=SENSITIVE()")])
        with self.output.open(encoding="utf-8-sig", newline="") as report:
            self.assertEqual(list(csv.DictReader(report))[0]["HOSTNAME"], "'=SENSITIVE()")
        for options in ({"workers": 100}, {"timeout": 4}, {"dry_run": True, "apply": True}):
            with self.assertRaises(CommandError):
                self.run_command(**options)

    def test_each_site_and_all_authorized_are_passed_as_exact_explicit_scope(self):
        for scope, count in (({"site": "VILLA_ELISA"}, 21), ({"site": "OFICINA_CENTRAL"}, 8),
                             ({"all_authorized": True}, 29)):
            with patch("apps.printing.management.commands.discover_printers_network.discover_networks", return_value=[]) as scanner:
                call_command("discover_printers_network", output=str(self.output), overwrite=True,
                             stdout=StringIO(), dry_run=True, **scope)
            self.assertEqual(len(scanner.call_args.args[0]), count)

    def test_apply_ip_conflict_is_not_written(self):
        PrintingDevice.objects.create(ip_address="10.11.42.241")
        before = self.snapshot()
        output, _ = self.run_command(apply=True)
        self.assertIn("CONFLICT=1", output)
        self.assertIn("ACTUALIZADAS=0", output)
        self.assertEqual(self.snapshot(), before)

    def test_partial_or_failed_discovery_cannot_write_and_does_not_expose_secrets(self):
        before = self.snapshot()
        output, _ = self.run_command([changed_finding(scan_complete=False)], apply=True)
        self.assertIn("ACTUALIZADAS=0", output)
        self.assertEqual(self.snapshot(), before)
        with patch("apps.printing.management.commands.discover_printers_network.discover_networks", side_effect=RuntimeError("SECRET")):
            with self.assertRaises(CommandError) as error:
                call_command("discover_printers_network", subnet=[SUBNET], output=str(self.output), overwrite=True,
                             stdout=StringIO(), apply=True)
        self.assertNotIn("SECRET", str(error.exception))
        self.assertEqual(self.snapshot(), before)
