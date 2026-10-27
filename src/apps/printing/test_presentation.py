from datetime import datetime, timedelta, timezone as datetime_timezone
from unittest.mock import patch

from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from .models import PrintingDevice, PrintingDeviceUserAssignment
from .presentation import with_monitoring_display


@override_settings(PRINTING_MONITOR_MAX_AGE_SECONDS=900)
class MonitoringPresentationTests(SimpleTestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 27, 15, tzinfo=datetime_timezone.utc)
        self.device = PrintingDevice(ip_address="10.8.1.25", monitored_ip="10.8.1.25",
            monitor_method="TCP", monitor_evidence={"network_port": 9100}, connection_status="ONLINE",
            last_checked_at=self.now-timedelta(minutes=2), last_online_at=self.now-timedelta(minutes=2),
            updated_at=self.now-timedelta(days=3))
        self.device.monitor_ip_conflict = False

    def display(self):
        return with_monitoring_display(self.device, now=self.now).monitoring_display

    def test_recent_online_and_record_updated_are_independent(self):
        values = self.display()
        self.assertEqual(values["status"], "ONLINE")
        self.assertEqual(values["elapsed"], "Hace 2 minutos")
        self.assertNotEqual(values["updated_at"], values["checked_at"])

    def test_recent_offline_with_old_positive_response(self):
        self.device.connection_status = "OFFLINE"
        self.device.last_online_at = self.now-timedelta(days=2, hours=3)
        values = self.display()
        self.assertEqual(values["status"], "OFFLINE")
        self.assertEqual(values["elapsed"], "Hace 2 días, 3 horas")

    def test_never_checked(self):
        self.device.last_checked_at = self.device.last_online_at = None
        values = self.display()
        self.assertEqual(values["status"], "UNKNOWN")
        self.assertIsNone(values["checked_at"])
        self.assertEqual(values["elapsed"], "Sin datos")

    def test_stale_does_not_display_stored_offline_as_current(self):
        self.device.connection_status = "OFFLINE"
        self.device.last_checked_at = self.now-timedelta(hours=1)
        self.device.last_online_at = self.now-timedelta(days=1)
        values = self.display()
        self.assertEqual(values["status"], "UNKNOWN")
        self.assertIn("desactualizado", values["note"])
        self.assertEqual(values["elapsed"], "Hace 1 día")

    def test_archived_is_history_even_if_measurement_recent(self):
        self.device.is_active = False
        self.assertEqual(self.display()["status"], "UNKNOWN")
        self.assertIn("archivado", self.display()["note"])
        self.assertIsNotNone(self.display()["online_at"])

    def test_without_ip_or_network_support(self):
        for changes in ({"ip_address": None}, {"supports_network": False}):
            with self.subTest(changes=changes):
                original = {key: getattr(self.device, key) for key in changes}
                for key, value in changes.items():
                    setattr(self.device, key, value)
                self.assertEqual(self.display()["status"], "UNKNOWN")
                for key, value in original.items():
                    setattr(self.device, key, value)

    def test_changed_ip_and_duplicate_ip_are_not_current_evidence(self):
        self.device.monitored_ip = "10.8.1.26"
        values = self.display()
        self.assertEqual(values["status"], "UNKNOWN")
        self.assertTrue(values["target_changed"])
        self.device.monitored_ip = self.device.ip_address
        self.device.monitor_ip_conflict = True
        self.assertEqual(self.display()["status"], "UNKNOWN")

    def test_future_naive_and_missing_dates_are_not_displayed(self):
        for value in (None, self.now+timedelta(hours=1), self.now.replace(tzinfo=None)):
            with self.subTest(value=value):
                self.device.last_checked_at = self.device.last_online_at = self.device.updated_at = value
                values = self.display()
                self.assertEqual(values["status"], "UNKNOWN")
                self.assertIsNone(values["online_at"])
                self.assertIsNone(values["updated_at"])
                self.assertEqual(values["elapsed"], "Sin datos")

    def test_online_date_after_check_is_not_reliable(self):
        self.device.last_online_at = self.now-timedelta(minutes=1)
        self.assertIsNone(self.display()["online_at"])

    def test_recent_positive_response_uses_minutes_without_negative_age(self):
        self.device.last_online_at = self.device.last_checked_at = self.now
        self.assertEqual(self.display()["elapsed"], "Hace menos de un minuto")

    def test_helper_does_not_change_persistent_fields(self):
        before = {f.attname: getattr(self.device, f.attname) for f in self.device._meta.concrete_fields}
        self.display()
        self.assertEqual(before, {f.attname: getattr(self.device, f.attname) for f in self.device._meta.concrete_fields})


class InventoryPresentationViewsTests(TestCase):
    def setUp(self):
        signals = patch("apps.accounts.signals.try_sync_user_institutional_data")
        signals.start()
        self.addCleanup(signals.stop)
        identities = patch("apps.directory.identity_services.resolve_identities_for_users", return_value={})
        identities.start()
        self.addCleanup(identities.stop)
        self.admin = User.objects.create_user(username="presentation-admin", email="presentation-admin@example.test", role="ADMIN")
        self.person = User.objects.create_user(username="presentation-person", email="presentation-person@example.test", first_name="Usuario", last_name="Uno")
        self.other = User.objects.create_user(username="presentation-other", email="presentation-other@example.test", first_name="Usuario", last_name="Dos")
        self.device = PrintingDevice.objects.create(photocopier_id="DISPLAY-01",
            ip_address="10.8.2.1", notes="Responsable: ARIEL FERREIRA\nResponsable: SILVIO LOPEZ\nDependencia: Gerencia Comercial")
        self.client.force_login(self.admin)
        self.list_url = reverse("printing:devices_by_model")
        self.detail_url = reverse("printing:device_detail", args=[self.device.pk])

    def both_pages(self):
        for url in (self.list_url, self.detail_url):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            yield response

    def test_history_without_redundant_empty_messages(self):
        for response in self.both_pages():
            self.assertContains(response, "Usuarios del equipo")
            self.assertContains(response, "ARIEL FERREIRA")
            self.assertContains(response, "SILVIO LOPEZ")
            self.assertContains(response, "Sin vínculo institucional verificado")
            self.assertNotContains(response, "Sin usuarios registrados")
            self.assertNotContains(response, "Sin usuarios asociados")
            self.assertNotContains(response, "Responsable / Usuarios")
        self.assertEqual(PrintingDeviceUserAssignment.objects.count(), 0)

    def test_multiple_current_users_and_history_coexist(self):
        for user in (self.person, self.other):
            PrintingDeviceUserAssignment.objects.create(device=self.device, user=user, assigned_by=self.admin)
        for response in self.both_pages():
            self.assertContains(response, "Usuario Uno")
            self.assertContains(response, "Usuario Dos")
            self.assertContains(response, "ARIEL FERREIRA")
        response = self.client.get(self.detail_url)
        self.assertContains(response, "Quitar usuario", count=2)
        self.assertContains(response, "Historial de asociaciones finalizadas")

    def test_structured_responsible_is_preserved_without_assignments(self):
        self.device.responsible_user = self.person
        self.device.save()
        for response in self.both_pages():
            self.assertContains(response, "Responsable registrado:")
            self.assertContains(response, "Usuario Uno")

    def test_no_relationships_displays_single_empty_message(self):
        self.device.notes = ""
        self.device.save()
        for response in self.both_pages():
            self.assertContains(response, "Sin usuarios registrados.", count=1)

    def test_ended_assignments_only_in_detail_history(self):
        ended_at = timezone.now()
        PrintingDeviceUserAssignment.objects.create(device=self.device, user=self.person, assigned_by=self.admin,
            assigned_at=ended_at-timedelta(days=1), ended_at=ended_at, ended_by=self.admin)
        self.assertNotContains(self.client.get(self.list_url), "Usuario Uno")
        detail = self.client.get(self.detail_url)
        self.assertContains(detail, "Usuario Uno")
        self.assertNotContains(detail, "Quitar usuario")

    def test_missing_monitoring_shows_no_data_on_both_pages(self):
        for response in self.both_pages():
            for label in ("Última comprobación:", "Última vez en línea:", "Desde la última respuesta positiva:", "Última actualización del registro:"):
                self.assertContains(response, label)
            self.assertContains(response, "Sin datos")
            self.assertContains(response, "Sin estado vigente")

    @override_settings(TIME_ZONE="America/Sao_Paulo", USE_TZ=True)
    def test_local_dates_include_offset_and_record_timestamp_separately(self):
        at = datetime(2026, 10, 25, 15, 30, tzinfo=datetime_timezone.utc)
        PrintingDevice.objects.filter(pk=self.device.pk).update(last_checked_at=at, last_online_at=at,
            last_status_change_at=at, updated_at=at-timedelta(days=1))
        with timezone.override("America/Sao_Paulo"):
            for response in self.both_pages():
                self.assertContains(response, "25/10/2026 12:30:00 -0300")
                self.assertContains(response, "24/10/2026 12:30:00 -0300")
                self.assertContains(response, "La actualización del registro no es una comprobación")

    def test_reads_do_not_write_data_or_probe(self):
        before = list(PrintingDevice.objects.values())
        with patch("apps.printing.connectivity.probe_device") as probe, CaptureQueriesContext(connection) as queries:
            list(self.both_pages())
        probe.assert_not_called()
        self.assertEqual(list(PrintingDevice.objects.values()), before)
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))

    def test_role_and_authentication_controls_are_unchanged(self):
        PrintingDeviceUserAssignment.objects.create(device=self.device, user=self.person, assigned_by=self.admin)
        auditor = User.objects.create_user(username="presentation-auditor", email="presentation-auditor@example.test", role="AUDITOR")
        self.client.force_login(auditor)
        self.assertNotContains(self.client.get(self.detail_url), "Quitar usuario")
        self.client.logout()
        self.assertEqual(self.client.get(self.list_url).status_code, 302)
        self.assertEqual(self.client.get(self.detail_url).status_code, 302)

    def test_archived_lifecycle_filter_is_preserved(self):
        self.device.is_active = False
        self.device.save()
        response = self.client.get(self.list_url)
        self.assertEqual(response.context["total"], 0)
        for lifecycle in ("all", "archived"):
            response = self.client.get(self.list_url, {"lifecycle": lifecycle})
            self.assertEqual(response.context["total"], 1)
            self.assertContains(response, "Equipo archivado: datos de monitoreo históricos.")
