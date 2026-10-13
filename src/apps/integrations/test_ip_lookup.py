from unittest.mock import Mock, patch

from django.db import connection
from django.test import TestCase, RequestFactory, SimpleTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.models import User
from apps.directory.identity_policies import technical_ip_identity_payload
from apps.integrations.glpi_client import GLPIClient, GLPIError
from apps.integrations.ip_lookup import lookup_ip, IPLookupError, institutional_people, contact_search_terms
from apps.integrations.views import ip_lookup_view
from apps.integrations.test_glpi import config, response


def mock_glpi(count=1, user=False, contact=""):
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.redact.side_effect = lambda value: value.replace("private-token", "[REDACTADO]")
    client.items.side_effect = lambda name, **kwargs: ([{"id": i, "name": "192.0.2.1", "itemtype": "NetworkName", "items_id": i} for i in range(1, count + 1)]
        if name == "IPAddress" else [{"id": 1, "email": "persona@petropar.gov.py"}])
    def item(kind, identifier):
        if kind == "NetworkName":
            return {"id": identifier, "name": "host-test", "itemtype": "NetworkPort", "items_id": identifier}
        if kind == "NetworkPort":
            return {"id": identifier, "itemtype": "Computer", "items_id": identifier, "mac": "00:11:22:33:44:55"}
        if kind == "Computer":
            return {"id": identifier, "name": "Equipo", "serial": "ABC", "users_id": 9 if user else 0, "contact": contact,
                    "date_mod": "2026-01-01 00:00:00", "locations_id": 4, "states_id": 5}
        if kind == "Location":
            return {"id": 4, "completename": "Villa Elisa > DTI"}
        if kind == "State":
            return {"id": 5, "name": "Activo"}
        if kind == "User":
            return {"id": 9, "name": "persona", "api_token": "never-show-user-token"}
        raise AssertionError(kind)
    client.item.side_effect = item
    return client


class IPLookupTests(TestCase):
    def test_valid_ip_found_without_user(self):
        client = mock_glpi()
        result = lookup_ip("192.0.2.1", client_factory=lambda: client)
        self.assertEqual(result["status"], "IDENTIFICADO")
        self.assertEqual(result["candidates"][0]["network_confidence"], "CONFIRMADA")
        self.assertEqual(result["candidates"][0]["people"]["confidence"], "DESCONOCIDA")
        self.assertIn("00:11:22:33:44:55", str(result))
        client.items.assert_called_once_with("IPAddress", filters={"name": "192.0.2.1"})
        client.__exit__.assert_called_once()

    def test_absent_ip(self):
        client = mock_glpi(count=0)
        self.assertEqual(lookup_ip("192.0.2.1", client_factory=lambda: client)["status"], "NO_IDENTIFICADO")
        client.item.assert_not_called()

    def test_invalid_ipv4_does_not_call_glpi(self):
        factory = Mock()
        for value in ("invalid", "999.1.1.1", "2001:db8::1", "192.0.2.1/path"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                lookup_ip(value, client_factory=factory)
        factory.assert_not_called()

    def test_multiple_candidates_not_chosen(self):
        result = lookup_ip("192.0.2.1", client_factory=lambda: mock_glpi(count=2))
        self.assertEqual(len(result["candidates"]), 2)

    @patch("apps.integrations.ip_lookup.search_common_identities")
    def test_contact_name_only_is_probable_and_no_local_user_created(self, search):
        identity = {"full_name": "Persona Institucional", "email": "persona@petropar.gov.py", "source": "RRHH",
            "_locator": {"source": "RRHH", "id": 10}, "position": "Tecnico", "phone": "123", "is_active": True,
            "organizational_unit": {"name": "DTI"}, "local_user_id": None, "document_number": "private-ci"}
        search.return_value = {"incomplete": False, "identities": [identity]}
        before = User.objects.count()
        with CaptureQueriesContext(connection) as queries:
            result = lookup_ip("192.0.2.1", client_factory=lambda: mock_glpi(contact="Persona Institucional"))
        person = result["candidates"][0]["people"]
        self.assertEqual(person["confidence"], "PROBABLE")
        self.assertIn("Persona Institucional", str(person))
        self.assertIn("DTI", str(person))
        self.assertNotIn("private-ci", str(person))
        self.assertNotIn("local_user_id", str(person))
        self.assertEqual(User.objects.count(), before)
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))
        search.assert_called_once_with("Persona Institucional", "name", exact=True)

    @patch("apps.integrations.ip_lookup.search_common_identities")
    def test_identity_confirmed_by_email_and_username_without_local_user(self, search):
        search.return_value = {"incomplete": False, "identities": [{"full_name": "Persona Institucional", "email": "persona@petropar.gov.py",
            "source": "RRHH", "_locator": {"source": "RRHH", "id": 10}, "local_user_id": None}]}
        result = lookup_ip("192.0.2.1", client_factory=lambda: mock_glpi(user=True))
        self.assertEqual(result["candidates"][0]["people"]["confidence"], "CONFIRMADA")
        self.assertEqual(search.call_count, 2)
        self.assertNotIn("never-show-user-token", str(result))

    @patch("apps.integrations.ip_lookup.search_common_identities")
    def test_ambiguous_or_incomplete_identities_unknown(self, search):
        search.return_value = {"incomplete": True, "identities": [{"_locator": {"source": "RRHH", "id": 1}}, {"_locator": {"source": "RRHH", "id": 2}}]}
        result = lookup_ip("192.0.2.1", client_factory=lambda: mock_glpi(user=True))
        self.assertEqual(result["candidates"][0]["people"]["confidence"], "DESCONOCIDA")
        self.assertEqual(len(result["candidates"][0]["people"]["candidates"]), 2)

    def test_unavailable_glpi_never_exposes_exception_payload(self):
        client = mock_glpi()
        client.items.side_effect = GLPIError('private-token Authorization: password http://user:password@host/ full response')
        with self.assertRaises(IPLookupError) as error:
            lookup_ip("192.0.2.1", client_factory=lambda: client)
        self.assertNotIn("private-token", str(error.exception))
        self.assertNotIn("password", str(error.exception))
        self.assertIn("busqueda IPAddress", str(error.exception))
        client.__exit__.assert_called_once()

    def test_success_redacts_known_secret_and_never_returns_raw_payload(self):
        client = mock_glpi(contact="private-token")
        with patch("apps.integrations.ip_lookup.search_common_identities", return_value={"incomplete": False, "identities": []}):
            result = lookup_ip("192.0.2.1", client_factory=lambda: client)
        self.assertNotIn("private-token", str(result))
        self.assertIn("[REDACTADO]", str(result))

    def test_long_spaced_secret_redacted_before_display_truncation(self):
        secret = "private  credential " * 30
        client = mock_glpi(contact=secret)
        client.redact.side_effect = lambda value: value.replace(secret, "[REDACTADO]")
        with patch("apps.integrations.ip_lookup.search_common_identities", return_value={"incomplete": False, "identities": []}):
            result = lookup_ip("192.0.2.1", client_factory=lambda: client)
        self.assertNotIn("private", str(result))
        self.assertIn("[REDACTADO]", str(result))

    @patch("apps.integrations.ip_lookup.search_common_identities")
    def test_inactive_glpi_user_not_resolved(self, search):
        client = mock_glpi(user=True)
        original = client.item.side_effect
        client.item.side_effect = lambda kind, identifier: {"id": 9, "name": "persona", "is_active": 0} if kind == "User" else original(kind, identifier)
        result = lookup_ip("192.0.2.1", client_factory=lambda: client)
        self.assertEqual(result["candidates"][0]["people"]["confidence"], "DESCONOCIDA")
        search.assert_not_called()

    def test_orphans_and_other_ip_do_not_associate(self):
        client = mock_glpi()
        client.items.return_value = []
        client.items.side_effect = lambda *args, **kwargs: [
            {"id": 1, "name": "192.0.2.10", "itemtype": "NetworkName", "items_id": 1},
            {"id": 2, "name": "192.0.2.1", "itemtype": "Computer", "items_id": 1}]
        result = lookup_ip("192.0.2.1", client_factory=lambda: client)
        self.assertEqual(result["candidates"], [])
        self.assertTrue(result["warnings"])


class IPLookupViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tecnico-ip", role="TECHNICIAN")
        self.url = reverse("integrations:ip_lookup")

    def test_anonymous_redirects_and_client_denied(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.user.role = "CLIENT"
        self.user.save(update_fields=["role"])
        self.client.force_login(self.user)
        with patch("apps.integrations.views.lookup_ip") as lookup:
            self.assertEqual(self.client.get(self.url, {"ip": "192.0.2.1"}).status_code, 403)
        lookup.assert_not_called()

    def test_technician_and_admin_can_open_form_without_query(self):
        for role in ("TECHNICIAN", "ADMIN"):
            self.user.role = role
            self.user.save(update_fields=["role"])
            self.client.force_login(self.user)
            with patch("apps.integrations.views.lookup_ip") as lookup:
                response = self.client.get(self.url)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Consulta técnica por IP")
            self.assertIn("no-store", response["Cache-Control"])
            lookup.assert_not_called()

    def test_invalid_ip_and_service_error_are_clear(self):
        self.client.force_login(self.user)
        with patch("apps.integrations.views.lookup_ip") as lookup:
            self.assertEqual(self.client.get(self.url, {"ip": "bad"}).status_code, 200)
            lookup.assert_not_called()
        with patch("apps.integrations.views.lookup_ip", side_effect=IPLookupError("Consulta no disponible.")):
            self.assertContains(self.client.get(self.url, {"ip": "192.0.2.1"}), "Consulta no disponible")

    def test_no_result_and_multiple_candidates_and_xss_escape(self):
        self.client.force_login(self.user)
        with patch("apps.integrations.views.lookup_ip", return_value={"ip": "192.0.2.1", "candidates": [], "warnings": []}):
            self.assertContains(self.client.get(self.url, {"ip": "192.0.2.1"}), "No identificado")
        candidate = {"device_type": "<script>unsafe()</script>", "fields": [], "people": {"candidates": []}}
        with patch("apps.integrations.views.lookup_ip", return_value={"ip": "192.0.2.1", "candidates": [candidate, candidate], "warnings": []}):
            result = self.client.get(self.url, {"ip": "192.0.2.1"})
        self.assertContains(result, "Varios candidatos")
        self.assertNotContains(result, "<script>unsafe()</script>")

    def test_view_and_service_zero_writes(self):
        request = RequestFactory().get(self.url, {"ip": "192.0.2.1"})
        request.user = self.user
        with patch("apps.integrations.ip_lookup.GLPIConfig.from_env", return_value=config()), \
             patch("apps.integrations.ip_lookup.GLPIClient", return_value=mock_glpi()), CaptureQueriesContext(connection) as queries:
            response = ip_lookup_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))


class IPClientTests(SimpleTestCase):
    def test_detail_uses_get_whitelist_and_validates_id(self):
        http = Mock()
        http.get.return_value = response({"id": 7, "name": "Computer"})
        client = GLPIClient(config(), http)
        client.token = "mock-session"
        self.assertEqual(client.item("Computer", 7)["id"], 7)
        self.assertTrue(http.get.call_args.args[0].endswith("Computer/7"))
        with self.assertRaises(GLPIError):
            client.item("Computer", "https://credentials@host")

    def test_filtered_collection_uses_searchtext_and_keeps_pagination(self):
        http = Mock()
        http.get.return_value = response([{"id": 1, "name": "192.0.2.1"}], content_range="0-0/1")
        client = GLPIClient(config(), http)
        client.token = "mock-session"
        self.assertEqual(len(client.items("IPAddress", filters={"name": "192.0.2.1"})), 1)
        self.assertEqual(http.get.call_args.kwargs["params"]["searchText[name]"], "192.0.2.1")

    def test_technical_identity_whitelist(self):
        result = technical_ip_identity_payload({"full_name": "Persona", "email": "person@example.test", "document_number": "private"})
        self.assertNotIn("document_number", result)
        self.assertNotIn("local_user_id", result)


@override_settings(DIRECTORY_AD_NETBIOS_DOMAIN="PETROPAR", DIRECTORY_AD_DOMAIN="petropar.gov.py")
class GLPIContactResolutionTests(TestCase):
    @patch("apps.integrations.ip_lookup.search_common_identities")
    def test_ad_rrhh_consolidated_contact_high_confidence_without_writes(self, search):
        ad = {"source": "ACTIVE_DIRECTORY", "email": "vhpalma@petropar.gov.py", "username": "vhpalma",
            "full_name": "Persona Institucional", "_locator": {"source": "ACTIVE_DIRECTORY", "username": "vhpalma"}}
        rrhh = {"source": "RRHH", "email": "vhpalma@petropar.gov.py", "full_name": "PERSONA INSTITUCIONAL",
            "position": "Jefe de Departamento Interino", "phone": "5550100", "location": "Secretaría General",
            "_locator": {"source": "RRHH", "id": 1}}
        search.side_effect = lambda query, kind, **kwargs: {"incomplete": False,
            "identities": [] if query == "vhpalma@petropar" else [ad] if kind == "username" else [ad, rrhh]}
        before = User.objects.count()
        with CaptureQueriesContext(connection) as queries:
            result = institutional_people(None, [], "vhpalma@PETROPAR")
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["confidence"], "CONFIRMADA")
        self.assertEqual(result["candidates"][0]["sources"], ["ACTIVE_DIRECTORY", "RRHH"])
        self.assertIn("Jefe de Departamento Interino", str(result))
        self.assertEqual(User.objects.count(), before)
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))

    def identity(self, identifier=1):
        return {"_locator": {"source": "RRHH", "id": identifier}, "full_name": "Persona de prueba",
            "username": "yhpalma", "email": "yhpalma@petropar.gov.py", "source": "RRHH", "is_active": True,
            "location": "Villa Elisa", "position": "Cargo de prueba", "phone": "123", "local_user_id": None}

    @patch("apps.integrations.ip_lookup.search_common_identities")
    def test_netbios_contact_checks_variants_and_unique_identity_without_writes(self, search):
        search.side_effect = lambda query, kind, **kwargs: {"incomplete": False,
            "identities": [] if query == "yhpalma@petropar" else [self.identity()]}
        count = User.objects.count()
        with CaptureQueriesContext(connection) as queries:
            result = institutional_people(None, [], " yhpalma@PETROPAR ")
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["confidence"], "PROBABLE")
        self.assertEqual([(call.args[0], call.args[1]) for call in search.call_args_list], [
            ("yhpalma@petropar", "email"), ("yhpalma", "username"), ("yhpalma@petropar.gov.py", "email")])
        self.assertIn("Villa Elisa", str(result))
        self.assertIn("yhpalma", str(result))
        self.assertEqual(User.objects.count(), count)
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))

    @patch("apps.integrations.ip_lookup.search_common_identities")
    def test_username_and_full_email(self, search):
        search.return_value = {"incomplete": False, "identities": [self.identity()]}
        for term, kind in [("yhpalma", "username"), ("yhpalma@petropar.gov.py", "email")]:
            search.reset_mock()
            self.assertEqual(institutional_people(None, [], term)["confidence"], "PROBABLE")
            search.assert_called_once_with(term, kind, exact=True)

    @patch("apps.integrations.ip_lookup.search_common_identities")
    def test_ambiguous_variants_not_merged_by_shared_email(self, search):
        search.side_effect = [{"incomplete": False, "identities": []},
            {"incomplete": False, "identities": [self.identity(1)]},
            {"incomplete": False, "identities": [self.identity(2)]}]
        result = institutional_people(None, [], "yhpalma@PETROPAR")
        self.assertEqual(len(result["candidates"]), 2)
        self.assertEqual(result["confidence"], "DESCONOCIDA")

    @patch("apps.integrations.ip_lookup.search_common_identities")
    def test_not_found_and_incomplete(self, search):
        search.return_value = {"incomplete": False, "identities": []}
        self.assertIn("No identificado", institutional_people(None, [], "yhpalma@PETROPAR")["reason"])
        search.return_value = {"incomplete": True, "identities": [self.identity()]}
        self.assertEqual(institutional_people(None, [], "yhpalma@PETROPAR")["confidence"], "DESCONOCIDA")

    def test_unknown_domain_never_converted(self):
        self.assertEqual(contact_search_terms("yhpalma@EXTERNO"), [("yhpalma@EXTERNO", "email")])

    @patch("apps.integrations.ip_lookup.search_common_identities")
    def test_inferred_email_not_counted_as_confirming_evidence(self, search):
        search.return_value = {"incomplete": False, "identities": [self.identity()]}
        self.assertEqual(institutional_people({"name": "yhpalma@PETROPAR"}, [], "")["confidence"], "PROBABLE")

    @patch("apps.integrations.ip_lookup.search_common_identities")
    def test_contact_still_searched_when_glpi_user_not_resolved(self, search):
        search.side_effect = lambda query, kind, **kwargs: {"incomplete": False,
            "identities": [self.identity()] if query == "yhpalma" else []}
        result = institutional_people({"name": "unresolved-user"}, [], "yhpalma@PETROPAR")
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["confidence"], "PROBABLE")
