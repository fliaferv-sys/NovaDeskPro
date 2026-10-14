from datetime import timedelta
from io import StringIO
from unittest.mock import patch, MagicMock

from django.core.management import call_command, CommandError
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.tests import TEST_STORAGES
from apps.inventory.models import Asset
from .models import PrintingDevice
from .connectivity import probe_device, persist_result, effective_status
from .connectivity import with_connectivity


@override_settings(STORAGES=TEST_STORAGES, PRINTING_MONITOR_TIMEOUT_SECONDS=0.2,
                   PRINTING_MONITOR_MAX_AGE_SECONDS=900)
class PrinterConnectivityTests(TestCase):
    def setUp(self):
        self.device = PrintingDevice.objects.create(serial_number="701824340HW75", brand="Lexmark",
                                                    model="MX622ADHE", ip_address="10.5.42.41")
        self.admin = User.objects.create_user(username="connectivity-admin", role="ADMIN")
        with patch("apps.accounts.signals.try_sync_user_institutional_data"):
            self.client.force_login(self.admin)

    def command(self, **options):
        output = StringIO()
        call_command("monitor_printers", stdout=output, **options)
        return output.getvalue()

    def measurement(self, status="ONLINE", checked_at=None):
        self.device.connection_status = status
        self.device.monitored_ip = self.device.ip_address
        self.device.last_checked_at = checked_at or timezone.now()
        self.device.monitor_method = "TCP"
        self.device.monitor_evidence = {"network_port": self.device.network_port}
        self.device.save()

    def test_device_without_asset_can_be_online_and_offline(self):
        self.assertIsNone(self.device.asset_id)
        with patch("apps.printing.connectivity.socket.create_connection") as connect:
            self.command(serial=self.device.serial_number)
        connect.assert_called_once_with(("10.5.42.41", 9100), timeout=0.2)
        self.device.refresh_from_db()
        self.assertEqual(effective_status(self.device), "ONLINE")
        first_online = self.device.last_online_at
        with patch("apps.printing.connectivity.socket.create_connection", side_effect=OSError("secret text")):
            self.command(id=str(self.device.pk))
        self.device.refresh_from_db()
        self.assertEqual(effective_status(self.device), "OFFLINE")
        self.assertEqual(self.device.last_online_at, first_online)
        self.assertEqual(self.device.monitor_error, "NO_RESPONSE")
        self.assertIsNotNone(self.device.last_status_change_at)

    def test_no_ip_never_checked_stale_or_changed_target_is_unknown(self):
        self.assertEqual(effective_status(self.device), "UNKNOWN")
        self.measurement(checked_at=timezone.now() - timedelta(minutes=16))
        self.assertEqual(effective_status(self.device), "UNKNOWN")
        self.measurement()
        self.device.ip_address = "10.5.42.42"
        self.assertEqual(effective_status(self.device), "UNKNOWN")
        self.device.ip_address = None
        with patch("apps.printing.connectivity.socket.create_connection") as connect:
            self.assertEqual(probe_device(self.device)["monitor_error"], "NO_IP")
        connect.assert_not_called()
        self.assertEqual(effective_status(self.device), "UNKNOWN")

    def test_invalid_ips_and_ports_do_not_connect(self):
        with patch("apps.printing.connectivity.socket.create_connection") as connect:
            for address in ("printer.local", "10.5.42.0/24", "::1", "127.0.0.1", "0.0.0.0", "224.0.0.1"):
                self.device.ip_address = address
                self.assertEqual(probe_device(self.device)["connection_status"], "UNKNOWN")
            self.device.ip_address = "10.5.42.41"
            self.device.network_port = 65536
            self.assertEqual(probe_device(self.device)["monitor_error"], "INVALID_NETWORK_CONFIGURATION")
        connect.assert_not_called()

    def test_web_reachability_is_distinct_from_print_service(self):
        with patch("apps.printing.connectivity.socket.create_connection", side_effect=[TimeoutError(), MagicMock()]) as connect:
            result = probe_device(self.device)
        self.assertEqual(result["connection_status"], "ONLINE")
        self.assertTrue(result["monitor_evidence"]["host_reachable"])
        self.assertFalse(result["monitor_evidence"]["print_port_reachable"])
        self.assertEqual(connect.call_args.args[0], ("10.5.42.41", 443))

    def test_duplicate_ip_including_inactive_device_never_asserts_online(self):
        other = PrintingDevice.objects.create(serial_number="OTHER", ip_address=self.device.ip_address, is_active=False)
        self.measurement()
        self.assertEqual(effective_status(self.device), "UNKNOWN")
        before = PrintingDevice.objects.values().get(pk=other.pk)
        with patch("apps.printing.connectivity.socket.create_connection") as connect:
            self.command(serial=self.device.serial_number)
        connect.assert_not_called()
        self.device.refresh_from_db()
        self.assertEqual(self.device.monitor_error, "DUPLICATE_IP")
        self.assertEqual(self.device.connection_status, "UNKNOWN")
        self.assertEqual(PrintingDevice.objects.values().get(pk=other.pk), before)

    def test_get_dashboard_counts_model_summary_filters_and_detail_without_network_or_writes(self):
        self.measurement()
        offline = PrintingDevice.objects.create(serial_number="OFF", brand="Lexmark", model="MX622ADHE",
            ip_address="10.5.42.42", monitored_ip="10.5.42.42", connection_status="OFFLINE",
            monitor_method="TCP", monitor_evidence={"network_port": 9100}, last_checked_at=timezone.now())
        unknown = PrintingDevice.objects.create(serial_number="UNKNOWN", brand="Lexmark", model="MX622ADHE")
        with patch("apps.printing.connectivity.socket.create_connection") as connect, patch(
            "apps.printing.views.enrich_person_records", side_effect=lambda records, *args: records), CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("printing:dashboard"))
            self.assertEqual(response.status_code, 200)
            for key, value in (("total_devices", 3), ("online_devices", 1), ("offline_devices", 1), ("unknown_devices", 1)):
                self.assertEqual(response.context[key], value)
                self.assertEqual(response.context["model_summary"][0][key], value)
            for status, pk in (("ONLINE", self.device.pk), ("OFFLINE", offline.pk), ("UNKNOWN", unknown.pk)):
                filtered = self.client.get(reverse("printing:devices_by_model"), {"status": status})
                self.assertEqual([d.pk for d in filtered.context["devices"]], [pk])
            detail = self.client.get(reverse("printing:device_detail", kwargs={"pk": self.device.pk}))
            self.assertContains(detail, "IP monitoreada")
            self.assertContains(detail, "10.5.42.41")
        connect.assert_not_called()
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))

    def test_asset_status_has_no_authority_over_printer_status(self):
        self.device.asset = Asset.objects.create(internal_code="MONITOR-ASSET", connection_status="OFFLINE")
        self.measurement()
        self.assertEqual(effective_status(self.device), "ONLINE")
        self.device.asset.connection_status = "ONLINE"
        self.measurement("OFFLINE")
        self.assertEqual(effective_status(self.device), "OFFLINE")

    def test_dry_run_probes_but_does_not_write_or_log(self):
        from apps.activity.models import ActivityLog
        before = PrintingDevice.objects.values().get(pk=self.device.pk)
        logs = ActivityLog.objects.count()
        with patch("apps.printing.connectivity.socket.create_connection") as connect, CaptureQueriesContext(connection) as queries:
            output = self.command(serial=self.device.serial_number, dry_run=True)
        connect.assert_called_once()
        self.assertIn("DRY_RUN", output)
        self.assertEqual(PrintingDevice.objects.values().get(pk=self.device.pk), before)
        self.assertEqual(ActivityLog.objects.count(), logs)
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))

    def test_pilot_only_updates_selected_device_and_never_scans(self):
        other = PrintingDevice.objects.create(serial_number="UNSELECTED", ip_address="10.5.42.42")
        before = PrintingDevice.objects.values().get(pk=other.pk)
        with patch("apps.printing.connectivity.socket.create_connection", side_effect=OSError()) as connect:
            self.command(ip="10.5.42.41")
        self.assertEqual({call.args[0][0] for call in connect.call_args_list}, {"10.5.42.41"})
        self.assertEqual(PrintingDevice.objects.values().get(pk=other.pk), before)

    def test_pilot_expected_ip_and_invalid_selectors_abort_before_probe(self):
        with patch("apps.printing.connectivity.socket.create_connection") as connect:
            for options in ({}, {"ip": "10.5.42.0/24"}, {"id": "bad"}, {"serial": "absent"},
                            {"serial": self.device.serial_number, "expected_ip": "10.5.42.99"},
                            {"all": True, "expected_ip": "10.5.42.41"}, {"all": True, "timeout": 11}):
                with self.assertRaises(CommandError):
                    self.command(**options)
        connect.assert_not_called()

    def test_unexpected_probe_error_is_unknown_safe_and_does_not_stop_batch(self):
        other = PrintingDevice.objects.create(serial_number="NEXT", ip_address="10.5.42.42")
        with patch("apps.printing.connectivity.socket.create_connection", side_effect=[RuntimeError("SNMP secret"), MagicMock()]):
            output = self.command(all=True)
        self.assertNotIn("SNMP secret", output)
        statuses = set(PrintingDevice.objects.values_list("connection_status", flat=True))
        self.assertEqual(statuses, {"UNKNOWN", "ONLINE"})

    def test_concurrent_ip_change_or_newer_measurement_does_not_get_overwritten(self):
        result = dict(connection_status="ONLINE", monitored_ip=self.device.ip_address, monitor_method="TCP",
                      monitor_error="", monitor_evidence={"network_port": 9100})
        checked = timezone.now()
        PrintingDevice.objects.filter(pk=self.device.pk).update(ip_address="10.5.42.99")
        self.assertFalse(persist_result(self.device, result, checked))
        PrintingDevice.objects.filter(pk=self.device.pk).update(ip_address=self.device.ip_address,
                                                                last_checked_at=checked + timedelta(seconds=1))
        self.assertFalse(persist_result(self.device, result, checked))

    def test_repeated_status_retains_transition_timestamp(self):
        with patch("apps.printing.connectivity.socket.create_connection"):
            self.command(id=str(self.device.pk))
            self.device.refresh_from_db()
            changed = self.device.last_status_change_at
            self.command(id=str(self.device.pk))
        self.device.refresh_from_db()
        self.assertEqual(self.device.last_status_change_at, changed)

    def test_invalid_measurement_is_unknown(self):
        self.measurement()
        for changes in ({"monitor_evidence": []}, {"monitor_method": "INVALID"},
                        {"connection_status": "INVALID"}, {"network_port": 515}):
            current = PrintingDevice.objects.get(pk=self.device.pk)
            for key, value in changes.items():
                setattr(current, key, value)
            self.assertEqual(effective_status(current), "UNKNOWN")

    def test_duplicate_detection_has_no_queries_per_row(self):
        for number in range(1, 15):
            PrintingDevice.objects.create(serial_number=f"BATCH-{number}", ip_address=f"10.5.42.{number}",
                monitored_ip=f"10.5.42.{number}", connection_status="ONLINE", monitor_method="TCP",
                last_checked_at=timezone.now(), monitor_evidence={"network_port": 9100})
        with self.assertNumQueries(1):
            devices = list(with_connectivity(PrintingDevice.objects.all()))
            self.assertEqual(sum(effective_status(d) == "ONLINE" for d in devices), 14)
