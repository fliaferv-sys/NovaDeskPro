from unittest.mock import patch

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.tests import TEST_STORAGES
from .models import PrintingDevice, PrintingDeviceNetworkDetection


@override_settings(STORAGES=TEST_STORAGES)
class PrintingInventoryIdentityUITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="inventory-ui", role="ADMIN")
        with patch("apps.accounts.signals.try_sync_user_institutional_data"):
            self.client.force_login(self.user)
        self.device = PrintingDevice.objects.create(brand="Lexmark", model="MX622",
            serial_number="SERIAL-UI", photocopier_id="21", ip_address="10.11.42.249")
        self.url = reverse("printing:devices_by_model")

    def test_current_identity_is_distinct_from_connectivity_and_registered_ip(self):
        PrintingDeviceNetworkDetection.objects.create(printing_device=self.device,
            detected_mac="00:21:B7:EF:1D:AA", detected_ip="10.11.42.241")
        response = self.client.get(self.url)
        for value in ("Lexmark", "MX622", "SERIAL-UI", "00:21:B7:EF:1D:AA",
                      "10.11.42.249", "10.11.42.241", "Identidad vinculada",
                      "Desconocido", "No indica conexión en tiempo real."):
            self.assertContains(response, value)
        self.assertContains(response, 'class="equipment-model"')
        self.assertContains(response, f'/psline/equipo/{self.device.pk}/')

    def test_unlinked_device_has_pending_identity(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Identidad pendiente de verificar")
        self.assertContains(response, "Sin detección vigente")

    def test_historical_detection_is_not_presented_as_current(self):
        PrintingDeviceNetworkDetection.objects.create(printing_device=self.device,
            detected_mac="00:21:B7:EF:1D:BB", detected_ip="10.11.42.240", is_current=False)
        response = self.client.get(self.url)
        self.assertContains(response, "Identidad pendiente de verificar")
        self.assertNotContains(response, "00:21:B7:EF:1D:BB")
        self.assertNotContains(response, "10.11.42.240")

    def test_detection_query_is_batched_and_get_does_not_write(self):
        def queries():
            with CaptureQueriesContext(connection) as captured:
                self.assertEqual(self.client.get(self.url).status_code, 200)
            return [q["sql"] for q in captured]
        first = queries()
        for index in range(4):
            device = PrintingDevice.objects.create(brand="Lexmark", model="MX622", serial_number=f"SERIAL-{index}")
            PrintingDeviceNetworkDetection.objects.create(printing_device=device,
                detected_mac=f"00:21:B7:EF:1D:{index:02X}")
        many = queries()
        self.assertEqual(len(first), len(many))
        detections = [sql for sql in many if "printing_printingdevicenetworkdetection" in sql.lower()]
        self.assertEqual(len(detections), 1)
        self.assertIn("is_current", detections[0])
        self.assertFalse(any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in many))

    def test_existing_filters_and_access_remain(self):
        self.assertContains(self.client.get(self.url, {"brand": "Lexmark", "model": "MX622", "search": "21"}), "SERIAL-UI")
        self.assertNotContains(self.client.get(self.url, {"brand": "Other"}), "SERIAL-UI")
        self.assertNotContains(self.client.get(self.url, {"status": "ONLINE"}), "SERIAL-UI")
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
