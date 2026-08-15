from concurrent.futures import ThreadPoolExecutor

from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from .models import BusinessSequence
from .sequences import next_business_number


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


class BusinessSequenceConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def test_next_business_number_returns_unique_values_under_concurrency(self):
        key = "ticket-concurrency-test"

        def worker(_):
            close_old_connections()
            return next_business_number(key, seed=0)

        with ThreadPoolExecutor(max_workers=5) as executor:
            numbers = list(executor.map(worker, range(5)))

        self.assertEqual(len(numbers), 5)
        self.assertEqual(len(set(numbers)), 5)
        self.assertEqual(sorted(numbers), [1, 2, 3, 4, 5])

        sequence = BusinessSequence.objects.get(key=key)
        self.assertEqual(sequence.value, 5)
