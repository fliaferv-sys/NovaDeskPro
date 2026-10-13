from unittest.mock import patch, Mock

from django.test import TestCase
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import User
from apps.inventory.models import Asset
from apps.integrations.technical_context import resolve_technical_context
from apps.integrations.test_ip_lookup import mock_glpi


class TechnicalContextTests(TestCase):
    def setUp(self):
        self.requester = User.objects.create_user(username="solicitante", email="solicitante@petropar.gov.py", first_name="Solicitante", role="TECHNICIAN")
        self.owner = User.objects.create_user(username="custodio", first_name="Custodio")

    @patch("apps.integrations.ip_lookup.search_common_identities")
    def test_ip_requester_detected_user_and_responsible_stay_distinct(self, search):
        def answer(query, kind, **kwargs):
            user = "Persona detectada" if "persona" in query else "Solicitante Institucional"
            return {"incomplete": False, "identities": [{"source": "RRHH", "email": query if "@" in query else query+"@petropar.gov.py",
                "full_name": user, "_locator": {"source": "RRHH", "id": user}}]}
        search.side_effect = answer
        asset = Asset.objects.create(internal_code="CTX-1", serial_number="ABC", assigned_user=self.owner, current_ip="192.0.2.99")
        before = Asset.objects.values().get(pk=asset.pk)
        count = User.objects.count()
        with CaptureQueriesContext(connection) as queries:
            result = resolve_technical_context(requester=self.requester, ip="192.0.2.1", client_factory=lambda: mock_glpi(user=True))
        self.assertEqual(result["requester"]["full_name"], "Solicitante")
        self.assertEqual(result["devices"][0]["detected_user"]["candidates"][0]["data"]["full_name"], "Persona detectada")
        matched = result["devices"][0]["novadesk_assets"][0]
        self.assertEqual(matched["responsible"]["full_name"], "Custodio")
        self.assertFalse(matched["can_select"])
        self.assertEqual(Asset.objects.values().get(pk=asset.pk), before)
        self.assertEqual(User.objects.count(), count)
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))

    @patch("apps.integrations.ip_lookup.search_common_identities", return_value={"incomplete": False, "identities": []})
    def test_no_identity_and_no_device_are_empty(self, _):
        result = resolve_technical_context(requester=self.requester, ip="192.0.2.1", client_factory=lambda: mock_glpi(count=0))
        self.assertEqual(result["person"]["candidates"], [])
        self.assertEqual(result["devices"], [])

    @patch("apps.integrations.ip_lookup.search_common_identities", return_value={"incomplete": True, "identities": []})
    def test_multiple_devices_and_directory_incomplete(self, _):
        result = resolve_technical_context(requester=self.requester, ip="192.0.2.1", client_factory=lambda: mock_glpi(count=2))
        self.assertEqual(len(result["devices"]), 2)
        self.assertTrue(result["person"]["incomplete"])

    @patch("apps.integrations.ip_lookup.search_common_identities")
    def test_consolidated_rrhh_ad_person(self, search):
        ad = {"source": "ACTIVE_DIRECTORY", "email": "persona@petropar.gov.py", "username": "persona", "full_name": "Persona Institucional",
            "_locator": {"source": "ACTIVE_DIRECTORY", "username": "persona"}}
        rrhh = {"source": "RRHH", "email": "persona@petropar.gov.py", "full_name": "PERSONA INSTITUCIONAL", "position": "Cargo",
            "_locator": {"source": "RRHH", "id": 1}}
        search.return_value = {"incomplete": False, "identities": [ad, rrhh]}
        result = resolve_technical_context(username="persona", email="persona@petropar.gov.py", ip="192.0.2.1", client_factory=lambda: mock_glpi(count=0))
        self.assertEqual(len(result["person"]["candidates"]), 1)
        self.assertEqual(result["person"]["confidence"], "CONFIRMADA")
        self.assertEqual(result["person"]["candidates"][0]["data"]["position"], "Cargo")

    @patch("apps.integrations.ip_lookup.search_common_identities", return_value={"incomplete": False, "identities": []})
    def test_glpi_error_does_not_block_context_or_expose_secret(self, _):
        client = mock_glpi()
        client.items.side_effect = RuntimeError("private-token Authorization: password")
        result = resolve_technical_context(requester=self.requester, ip="192.0.2.1", client_factory=lambda: client)
        self.assertEqual(result["devices"], [])
        self.assertTrue(result["warnings"])
        self.assertNotIn("private-token", str(result))

    @patch("apps.integrations.ip_lookup.search_common_identities", return_value={"incomplete": False, "identities": []})
    def test_hostname_exact_and_no_invented_mac_or_ip(self, _):
        client = mock_glpi()
        client.items.side_effect = lambda kind, **kwargs: [{"id": 1, "name": "host1", "serial": "ABC", "contact": "persona"}, {"id": 2, "name": "host10"}]
        result = resolve_technical_context(hostname="host1", client_factory=lambda: client)
        self.assertEqual(len(result["devices"]), 1)
        self.assertIsNone(result["devices"][0]["data"]["mac"])
        self.assertIsNone(result["devices"][0]["ip"])

    @patch("apps.integrations.ip_lookup.search_common_identities", return_value={"incomplete": False, "identities": []})
    def test_existing_asset_without_ip_kept_read_only(self, _):
        asset = Asset.objects.create(internal_code="CTX-LOCAL", serial_number="LOCAL", assigned_user=self.requester)
        result = resolve_technical_context(requester=self.requester, asset=asset, client_factory=lambda: mock_glpi(count=0))
        self.assertEqual(result["devices"][0]["novadesk_assets"][0]["id"], str(asset.pk))
        self.assertTrue(result["devices"][0]["novadesk_assets"][0]["can_select"])

    def test_contact_lookup_is_filtered_memoized_and_assets_are_batched(self):
        client = mock_glpi()
        client.items.side_effect = lambda kind, **kwargs: [
            {"id": 1, "name": "pc1", "serial": "SER-1", "contact": self.requester.username},
            {"id": 2, "name": "pc2", "serial": "SER-2", "contact": self.requester.username},
        ]
        people = {"confidence": "PROBABLE", "incomplete": False, "candidates": []}
        with patch("apps.integrations.technical_context.institutional_people", return_value=people) as identity, CaptureQueriesContext(connection) as queries:
            context = resolve_technical_context(requester=self.requester, client_factory=lambda: client)
        self.assertEqual(len(context["devices"]), 4)
        self.assertEqual(client.items.call_count, 2)
        for call in client.items.call_args_list:
            self.assertEqual(call.kwargs["filters"], {"contact": self.requester.username})
        self.assertEqual(identity.call_count, 2)  # requester + one repeated contact
        self.assertEqual(len(queries), 1)  # all serial matches in one read
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))

    @patch("apps.integrations.ip_lookup.search_common_identities")
    def test_requester_legajo_and_relationship_use_context_whitelist(self, search):
        search.return_value = {"incomplete": False, "identities": [{"source": "RRHH", "full_name": "Solicitante",
            "email": self.requester.email, "username": self.requester.username, "employee_number": "0002", "employment_relationship": "Permanente",
            "_locator": {"source": "RRHH", "id": 1}}]}
        result = resolve_technical_context(requester=self.requester, client_factory=lambda: mock_glpi(count=0))
        self.assertEqual(result["person"]["candidates"][0]["data"]["employee_number"], "0002")
        self.assertEqual(result["person"]["candidates"][0]["data"]["employment_type"], "Permanente")
