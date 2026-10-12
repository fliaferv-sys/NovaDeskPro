from io import StringIO
import os
from unittest.mock import Mock, patch

import requests
from django.core.management import call_command, CommandError
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import Branch
from apps.inventory.models import Asset, OrganizationalLocation
from apps.printing.models import PrintingDevice
from apps.integrations.glpi_client import GLPIClient, GLPIConfig, GLPIError
from apps.integrations.glpi_diagnostics import (
    printer_diagnostics, serial_comparison, user_diagnostics, printer_network_ips,
    computer_diagnostics, location_diagnostics,
)


def response(data, status=200, content_range=None):
    result = Mock(status_code=status, headers={})
    result.json.return_value = data
    if content_range is not None:
        result.headers["Content-Range"] = content_range
    return result


def config():
    return GLPIConfig("http://glpi.test/apirest.php", "app-secret-test", "api-secret-user", "pass-secret-test", page_size=2)


class GLPIClientTests(SimpleTestCase):
    def make_client(self, responses):
        session = Mock()
        session.get.side_effect = responses
        return GLPIClient(config(), session), session

    def test_init_headers_and_kill_session(self):
        client, http = self.make_client([response({"session_token": "session-secret-test"}), response(True)])
        with client:
            self.assertEqual(client.token, "session-secret-test")
        headers = http.get.call_args_list[0].kwargs["headers"]
        self.assertTrue(headers["Authorization"].startswith("Basic "))
        self.assertEqual(headers["App-Token"], "app-secret-test")
        self.assertEqual(http.get.call_args_list[1].kwargs["headers"]["Session-Token"], "session-secret-test")
        self.assertNotIn("Authorization", http.get.call_args_list[1].kwargs["headers"])
        self.assertFalse(http.get.call_args_list[0].kwargs["allow_redirects"])
        self.assertIsNone(client.token)
        http.close.assert_called_once()

    def test_auth_and_http_errors_never_expose_response(self):
        for status in [401, 403, 404, 500, 302]:
            client, http = self.make_client([response({"password": "pass-secret-test"}, status)])
            with self.subTest(status=status), self.assertRaises(GLPIError) as error:
                with client:
                    pass
            self.assertNotIn("pass-secret-test", str(error.exception))
            self.assertIn(str(status), str(error.exception))
            http.close.assert_called_once()

    def test_pages_follow_server_range_even_when_smaller_than_requested(self):
        client, http = self.make_client([response({"session_token": "token"}),
            response([{"id": 1}], 206, "0-0/3"),
            response([{"id": 2}], 206, "1-1/3"),
            response([{"id": 3}], 200, "2-2/3"), response(True)])
        with client:
            self.assertEqual([r["id"] for r in client.items("Printer")], [1, 2, 3])
        self.assertEqual([c.kwargs["params"]["range"] for c in http.get.call_args_list[1:4]], ["0-1", "1-2", "2-3"])

    def test_short_pages_without_range_continue_until_empty(self):
        client, _ = self.make_client([response({"session_token": "token"}),
            response({"0": {"id": 1}}), response([{"id": 2}]), response([]), response(True)])
        with client:
            self.assertEqual(len(client.items("User")), 2)

    def test_empty_collection(self):
        client, _ = self.make_client([response({"session_token": "token"}), response([], 200, "0-0/0"), response(True)])
        with client:
            self.assertEqual(client.items("Printer"), [])

    def test_invalid_repeated_and_incomplete_pages_fail_and_close_session(self):
        pages = [response([{"id": 1}], 206), response([{"id": 1}], 206, "1-1/3"),
                 response([{"id": 1}], 200, "0-0/3")]
        for page in pages:
            client, http = self.make_client([response({"session_token": "token"}),
                response([{"id": 1}], 206, "0-0/3"), page, response(True)])
            with self.assertRaises(GLPIError):
                with client:
                    client.items("Printer")
            self.assertTrue(http.get.call_args.args[0].endswith("killSession"))

    def test_total_changes_during_pagination(self):
        client, _ = self.make_client([response({"session_token": "token"}),
            response([{"id": 1}], 206, "0-0/2"), response([{"id": 2}], 200, "1-1/3"), response(True)])
        with self.assertRaises(GLPIError):
            with client:
                client.items("Printer")

    def test_timeout_attempts_kill_session(self):
        client, http = self.make_client([response({"session_token": "token"}), requests.Timeout("pass-secret-test"), response(True)])
        with self.assertRaises(GLPIError) as error:
            with client:
                client.items("Printer")
        self.assertNotIn("pass-secret-test", str(error.exception))
        self.assertTrue(http.get.call_args.args[0].endswith("killSession"))

    def test_failed_kill_clears_token_and_reports_error(self):
        client, http = self.make_client([response({"session_token": "token"}), response({}, 500)])
        with self.assertRaises(GLPIError):
            with client:
                pass
        self.assertIsNone(client.token)
        http.close.assert_called_once()

    def test_env_validation_and_repr_do_not_expose_secrets(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(GLPIError, "GLPI_API_URL"):
            GLPIConfig.from_env()
        self.assertNotIn("pass-secret-test", repr(config()))
        self.assertNotIn("app-secret-test", repr(config()))

    def test_range_exhaustion_requires_confirmed_total(self):
        client, _ = self.make_client([response({"session_token": "token"}), response({}, 416, "*/0"), response(True)])
        with client:
            self.assertEqual(client.items("Printer"), [])
        client, _ = self.make_client([response({"session_token": "token"}), response({}, 416), response(True)])
        with self.assertRaises(GLPIError):
            with client:
                client.items("Printer")


class GLPIDiagnosticsTests(TestCase):
    def test_printer_match_differences_no_writes(self):
        branch = Branch.objects.create(name="Planta Villa Elisa", code="PLANTA-VILLA-ELISA")
        location = OrganizationalLocation.objects.create(branch=branch, name="DTI", code="DTI")
        device = PrintingDevice.objects.create(serial_number=" ABC-1 ", photocopier_id="55/BK",
            ip_address="192.0.2.1", branch=branch, organizational_location=location,
            responsible_identity={"name": "Persona Institucional"})
        before = PrintingDevice.objects.values().get(pk=device.pk)
        with CaptureQueriesContext(connection) as queries:
            result = printer_diagnostics([{"id": 7, "serial": "abc-1", "name": "Lexmark", "locations_id": 1, "contact": "Persona"}],
                [{"id": 1, "name": "Villa Elisa"}], {"7": ["192.0.2.2"]})
        self.assertEqual(result[0]["estado"], "COINCIDE")
        self.assertTrue(any("IP_DIFERENTE" in value for value in result[0]["diferencias"]))
        self.assertTrue(any("UBICACION_DIFERENTE" in value for value in result[0]["diferencias"]))
        self.assertEqual(result[0]["novadesk"][0]["responsable"], "Persona Institucional")
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))
        self.assertEqual(PrintingDevice.objects.values().get(pk=device.pk), before)

    def test_only_on_one_side_and_duplicate_serials(self):
        results = serial_comparison([{"id": 1, "serial": "A"}, {"id": 2, "serial": "D"}, {"id": 3, "serial": " d "}],
            [{"id": 1, "serial": "B"}, {"id": 2, "serial": "X"}, {"id": 3, "serial": "X"}])
        self.assertEqual({r["estado"] for r in results}, {"SOLO_GLPI", "SOLO_NOVADESK", "DUPLICADO_GLPI", "DUPLICADO_NOVADESK"})

    def test_significant_internal_spaces_not_removed(self):
        results = serial_comparison([{"id": 1, "serial": "A B"}], [{"id": 2, "serial": "AB"}])
        self.assertEqual(len(results), 2)

    def test_empty_serials_require_review(self):
        self.assertEqual(serial_comparison([{"id": 1, "serial": ""}], [])[0]["estado"], "REVISAR")

    def test_computers_use_existing_asset_and_serial_only(self):
        asset = Asset.objects.create(internal_code="PC-1", serial_number="ABC", hostname="PC-UNO")
        Asset.objects.create(internal_code="PRINT-1", asset_type=Asset.AssetType.PRINTER, serial_number="PRINT")
        results = computer_diagnostics([{"id": 1, "serial": "abc", "otherserial": "PC-1", "name": "PC-UNO"}])
        self.assertEqual(results[0]["estado"], "COINCIDE")
        self.assertEqual(results[0]["novadesk"][0]["id"], str(asset.pk))
        self.assertEqual(computer_diagnostics([{"id": 2, "name": "PC-UNO", "otherserial": "PC-1"}])[0]["estado"], "REVISAR")

    def test_locations_are_proposals_without_writes(self):
        branch = Branch.objects.create(code="VILLA", name="Planta Villa Elisa")
        OrganizationalLocation.objects.create(branch=branch, code="RRHH", name="Recursos Humanos")
        with CaptureQueriesContext(connection) as queries:
            report = location_diagnostics([{"id": 1, "name": "Villa Elisa"}])
        self.assertEqual(report[0]["estado"], "PROPUESTA_REVISAR")
        self.assertEqual(report[0]["candidatos_textuales"], [])
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))

    @patch("apps.integrations.glpi_diagnostics.search_common_identities")
    def test_institutional_user_without_local_account(self, search):
        search.return_value = {"incomplete": False, "identities": [{"source": "RRHH", "email": "persona@petropar.gov.py",
            "full_name": "Persona Institucional", "_locator": {"source": "RRHH", "id": 1}, "is_active": True, "local_user_id": None}]}
        results = user_diagnostics([{"id": 1, "name": "persona", "emails": ["persona@petropar.gov.py"]}])
        self.assertEqual(results[0]["estado"], "COINCIDE")
        self.assertIsNone(results[0]["identidad"]["local_user_id"])
        search.assert_called_once_with("persona@petropar.gov.py", "email", exact=True)

    @patch("apps.integrations.glpi_diagnostics.search_common_identities")
    def test_incomplete_user_search_does_not_claim_match(self, search):
        search.return_value = {"incomplete": True, "identities": []}
        self.assertEqual(user_diagnostics([{"id": 1, "name": "persona"}])[0]["estado"], "REVISAR")

    @patch("apps.integrations.glpi_diagnostics.search_common_identities")
    def test_ambiguous_users_not_linked(self, search):
        search.return_value = {"incomplete": False, "identities": [
            {"_locator": {"source": "RRHH", "id": 1}}, {"_locator": {"source": "RRHH", "id": 2}}]}
        self.assertEqual(user_diagnostics([{"id": 1, "name": "persona"}])[0]["estado"], "REVISAR")

    def test_network_ip_mapping_follows_explicit_relations_only(self):
        result = printer_network_ips([{"id": 10, "itemtype": "Printer", "items_id": 7}],
            [{"id": 20, "itemtype": "NetworkPort", "items_id": 10}],
            [{"id": 30, "itemtype": "NetworkName", "items_id": 20, "name": "192.0.2.2"},
             {"id": 31, "itemtype": "NetworkName", "items_id": 999, "name": "192.0.2.3"}])
        self.assertEqual(result, {"7": ["192.0.2.2"]})


class GLPICommandTests(TestCase):
    def test_without_dry_run_aborts_before_any_http_or_db_writes(self):
        with patch("apps.integrations.glpi_client.requests.Session") as session, CaptureQueriesContext(connection) as queries:
            with self.assertRaisesRegex(CommandError, "Modo escritura no habilitado"):
                call_command("sync_glpi")
        session.assert_not_called()
        self.assertEqual(len(queries), 0)

    def test_missing_credentials_clear_error(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(CommandError, "GLPI_API_URL"):
            call_command("sync_glpi", dry_run=True, stderr=StringIO())

    @patch("apps.core.management.commands.sync_glpi.GLPIConfig.from_env", return_value=config())
    @patch("apps.integrations.glpi_client.requests.Session")
    def test_mocked_command_no_writes_and_redacts_secrets(self, session_factory, _):
        http = Mock()
        session_factory.return_value = http
        http.get.side_effect = [response({"session_token": "session-secret-test"}),
            response([], content_range="0-0/0"),
            response([{"id": 1, "serial": "ABC", "name": "app-secret-test pass-secret-test session-secret-test", "contact": "api-secret-user"}], content_range="0-0/1"), response(True)]
        output = StringIO()
        with CaptureQueriesContext(connection) as queries:
            call_command("sync_glpi", dry_run=True, section="printers", stdout=output)
        text = output.getvalue()
        for secret in ["app-secret-test", "pass-secret-test", "session-secret-test", "api-secret-user"]:
            self.assertNotIn(secret, text)
        self.assertIn("SOLO_GLPI=1", text)
        self.assertIn("ERROR=0", text)
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))
        self.assertTrue(http.get.call_args.args[0].endswith("killSession"))

    @patch("apps.integrations.glpi_diagnostics.search_common_identities")
    @patch("apps.core.management.commands.sync_glpi.GLPIConfig.from_env", return_value=config())
    @patch("apps.integrations.glpi_client.requests.Session")
    def test_all_sections_and_user_emails(self, session_factory, _, search):
        http = Mock()
        session_factory.return_value = http
        search.return_value = {"incomplete": False, "identities": []}
        http.get.side_effect = [response({"session_token": "session-secret-test"}),
            response([], content_range="0-0/0"), response([], content_range="0-0/0"),
            response([], content_range="0-0/0"),
            response([{"id": 1, "name": "persona"}], content_range="0-0/1"),
            response([{"id": 10, "email": "persona@petropar.gov.py"}], content_range="0-0/1"), response(True)]
        output = StringIO()
        with CaptureQueriesContext(connection) as queries:
            call_command("sync_glpi", dry_run=True, stdout=output)
        self.assertIn("User: 1", output.getvalue())
        self.assertIn("NO_ENCONTRADO", output.getvalue())
        search.assert_called_once_with("persona@petropar.gov.py", "email", exact=True)
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))
