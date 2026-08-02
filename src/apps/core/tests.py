from django.test import TestCase
from django.urls import reverse


class PwaEndpointTests(TestCase):
    def test_manifest_is_available(self):
        response = self.client.get(reverse("web_app_manifest"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.json()["name"], "NovaDesk Pro")
        self.assertEqual(response.json()["scope"], "/")

    def test_service_worker_has_root_scope(self):
        response = self.client.get(reverse("service_worker"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response["Content-Type"].startswith("application/javascript")
        )
        self.assertEqual(response["Service-Worker-Allowed"], "/")
        self.assertContains(response, "notificationclick")
