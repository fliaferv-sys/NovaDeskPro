import json
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.directory import identity_services as services
from apps.directory.identity_policies import CONTRACT_FIELDS


class CommonIdentityAPITests(TestCase):
    def setUp(self):
        self.actor = User.objects.create_superuser(username="api-admin", email="api-admin@example.test", password="test-password")
        self.client.force_login(self.actor)
        self.rrhh_rows = []
        self.ad_rows = []
        self.mapping = {}
        self.patches = [
            patch.object(services, "search_directory_employees", side_effect=self.rrhh_search),
            patch.object(services, "search_ad_users", side_effect=self.ad_search),
            patch.object(services, "_load_tercerizados", side_effect=lambda: self.mapping),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def filter_rows(self, rows, query, field, exact):
        return [row for row in rows if str(row.get(field) or "").strip().casefold() == str(query).strip().casefold() or (not exact and str(query).strip().casefold() in str(row.get(field) or "").strip().casefold())]

    def rrhh_search(self, query, limit=20, search_field="email", exact=False, **kwargs):
        field = {"email": "Mail", "employee_number": "LegajoNro", "name": "NombresApellidos", "rrhh_id": "IdPersonal"}[search_field]
        return self.filter_rows(self.rrhh_rows, query, field, exact)[:limit]

    def ad_search(self, query, limit=20, search_field="email", exact=False, **kwargs):
        return self.filter_rows(self.ad_rows, query, search_field, exact)[:limit]

    def rrhh(self, **overrides):
        row = {"IdPersonal": 1234, "Mail": "person@petropar.gov.py", "LegajoNro": "1002", "NombresApellidos": "Nombre Completo", "Cargo": "Analista", "Vinculo": "Contratado"}
        row.update(overrides)
        self.rrhh_rows.append(row)
        return row

    def ad(self, **overrides):
        row = {"email": "person@petropar.gov.py", "username": "person", "name": "Nombre Apellido", "first_name": "Nombre", "last_name": "Apellido", "is_active": True}
        row.update(overrides)
        self.ad_rows.append(row)
        return row

    def post(self, route, **payload):
        payload.setdefault("context", "accounts.add")
        return self.client.post(reverse("directory:" + route), data=json.dumps(payload), content_type="application/json")

    def search(self, query="person@petropar.gov.py", field="email", **extra):
        return self.post("identity_search_api", q=query, field=field, **extra)

    def test_exact_email_rrhh_identity_without_local_account(self):
        self.rrhh()
        response = self.search(" PERSON@petropar.gov.py ")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "resolved")
        self.assertEqual(data["identity"]["rrhh_id"], 1234)
        self.assertIsNone(data["identity"]["local_user_id"])
        self.assertEqual(data["values"]["username"], "person")
        self.assertNotIn("first_name", data["values"])
        self.assertEqual(data["values"]["employment_type"], "CONTRACTED")

    def test_exact_username_ad_identity(self):
        self.ad(username="account-id")
        data = self.search("account-id", "username").json()
        self.assertEqual(data["status"], "resolved")
        self.assertEqual(data["identity"]["username"], "account-id")
        self.assertEqual(data["values"]["username"], "person")
        self.assertEqual(data["identity"]["source"], "ACTIVE_DIRECTORY")
        self.assertIsNone(data["identity"]["rrhh_id"])

    def test_partial_name_and_multiple_candidates_require_selection(self):
        self.rrhh()
        self.rrhh(IdPersonal=1235, Mail="other@petropar.gov.py", LegajoNro="1003", NombresApellidos="Nombre Otro")
        data = self.search("Nombre", "name").json()
        self.assertEqual(data["status"], "candidates")
        self.assertEqual(len(data["candidates"]), 2)
        self.assertNotIn("values", data)
        resolved = self.post("identity_resolve_api", reference=data["candidates"][1]["reference"]).json()
        self.assertEqual(resolved["identity"]["rrhh_id"], 1235)

    def test_same_email_is_not_enough_to_merge_sources(self):
        self.rrhh()
        self.ad()
        data = self.search().json()
        self.assertEqual(data["status"], "candidates")
        self.assertEqual(len(data["candidates"]), 2)
        self.assertNotIn("identity", data)

    def test_explicit_local_links_can_merge_sources_without_inventing_data(self):
        self.rrhh()
        self.ad()
        local = User.objects.create_user(username="person", email="person@petropar.gov.py", id_personal=1234, employee_number="1002", first_name="Nombre", last_name="Apellido")
        data = self.search().json()
        self.assertEqual(data["status"], "resolved")
        self.assertEqual(data["identity"]["local_user_id"], str(local.pk))
        self.assertEqual(data["identity"]["rrhh_id"], 1234)
        self.assertEqual(data["identity"]["first_name"], "Nombre")

    def test_duplicate_source_records_remain_ambiguous(self):
        self.rrhh()
        self.rrhh(IdPersonal=9999, LegajoNro="2000")
        self.assertEqual(self.search().json()["status"], "candidates")

    def test_local_account_and_document_search(self):
        local = User.objects.create_user(username="local-person", email="local@petropar.gov.py", document_number="TEST-001", first_name="Persona", last_name="Local")
        data = self.search("TEST-001", "document_number").json()
        self.assertEqual(data["status"], "resolved")
        self.assertEqual(data["identity"]["source"], "LOCAL")
        self.assertEqual(data["identity"]["local_user_id"], str(local.pk))
        self.assertIsNone(data["identity"]["rrhh_id"])

    def test_outsourced_document_search_and_ad_enrichment(self):
        self.ad()
        record = {"ci": "TEST-002", "photo_file": ""}
        self.mapping = {"email:person@petropar.gov.py": record, "username:person": record}
        data = self.search("TEST-002", "document_number").json()
        self.assertEqual(data["status"], "resolved")
        self.assertEqual(data["identity"]["document_number"], "TEST-002")
        self.assertEqual(data["identity"]["employment_type"], "OUTSOURCED")
        self.assertIsNone(data["identity"]["local_user_id"])

    def test_mapping_without_ad_or_local_account(self):
        record = {"ci": "TEST-003", "photo_file": ""}
        self.mapping = {"email:mapped@petropar.gov.py": record, "username:mapped": record}
        data = self.search("TEST-003", "document_number").json()
        self.assertEqual(data["status"], "resolved")
        self.assertEqual(data["identity"]["source"], "TERCERIZADOS")
        self.assertEqual(data["identity"]["first_name"], "")

    def test_employee_number_search(self):
        self.rrhh()
        self.assertEqual(self.search("1002", "employee_number").json()["identity"]["rrhh_id"], 1234)

    def test_no_results(self):
        self.assertEqual(self.search().json()["status"], "not_found")

    def test_whitelists_and_rejects_arbitrary_fields(self):
        self.rrhh()
        data = self.search().json()
        self.assertEqual(set(data["identity"]), CONTRACT_FIELDS | {"reference"})
        self.assertEqual(set(data["candidates"][0]), {"full_name", "email", "employee_number", "source", "reference"})
        self.assertNotIn("document_number", data["candidates"][0])
        self.assertEqual(self.search(fields="password,is_superuser").status_code, 400)
        self.assertEqual(self.search(context="deliveries.add").status_code, 403)

    def test_authentication_staff_and_context_permission(self):
        self.client.logout()
        self.assertEqual(self.search().status_code, 302)
        staff = User.objects.create_user(username="staff", email="staff@example.test", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.search().status_code, 403)
        staff.user_permissions.add(Permission.objects.get(codename="add_user", content_type__app_label="accounts"))
        self.assertEqual(self.search().status_code, 200)
        self.assertEqual(self.search(context="accounts.change", object_id=str(self.actor.pk)).status_code, 403)
        staff.is_staff = False
        staff.save(update_fields=["is_staff"])
        self.assertEqual(self.search().status_code, 403)

    def test_change_requires_existing_object(self):
        self.assertEqual(self.search(context="accounts.change", object_id="bad-id").status_code, 403)
        self.assertEqual(self.search(context="accounts.change").status_code, 403)

    def test_reference_is_bound_to_actor_context_and_record_and_revalidated(self):
        row = self.rrhh()
        reference = self.search().json()["identity"]["reference"]
        self.assertEqual(self.post("identity_resolve_api", reference=reference).status_code, 200)
        self.assertEqual(self.post("identity_resolve_api", reference=reference + "x").status_code, 409)
        self.assertEqual(self.post("identity_resolve_api", reference=reference, context="accounts.change", object_id=str(self.actor.pk)).status_code, 409)
        row["LegajoNro"] = "changed"
        self.assertEqual(self.post("identity_resolve_api", reference=reference).status_code, 409)
        other = User.objects.create_superuser(username="other-admin", email="other-admin@example.test", password="test")
        self.client.force_login(other)
        self.assertEqual(self.post("identity_resolve_api", reference=reference).status_code, 409)

    def test_expired_reference_and_missing_source_are_rejected(self):
        self.rrhh()
        reference = self.search().json()["identity"]["reference"]
        with patch("django.core.signing.time.time", return_value=9999999999):
            self.assertEqual(self.post("identity_resolve_api", reference=reference).status_code, 409)
        self.rrhh_rows.clear()
        self.assertEqual(self.post("identity_resolve_api", reference=reference).status_code, 409)

    def test_source_failure_never_claims_unique_match(self):
        self.ad()
        with patch.object(services, "search_directory_employees", side_effect=services.DirectoryDatabaseError("test")):
            data = self.search().json()
        self.assertTrue(data["incomplete"])
        self.assertEqual(data["status"], "candidates")

    def test_results_are_bounded_and_truncation_disables_auto_resolution(self):
        for i in range(25):
            self.rrhh(IdPersonal=i + 1, Mail=f"person{i}@petropar.gov.py", LegajoNro=str(i))
        data = self.search("person", "email").json()
        self.assertEqual(len(data["candidates"]), 20)
        self.assertTrue(data["incomplete"])
        self.assertEqual(data["status"], "candidates")

    def test_csrf_and_method_validation(self):
        self.assertEqual(self.client.get(reverse("directory:identity_search_api")).status_code, 405)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.actor)
        response = client.post(reverse("directory:identity_search_api"), data=json.dumps({"context": "accounts.add", "q": "TEST-CI", "field": "document_number"}), content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_ci_is_not_part_of_urls_or_application_log_messages(self):
        ci = "TEST-PRIVATE-CI"
        with self.assertLogs("django.request", level="WARNING") as logs:
            response = self.search(ci, "document_number", fields="password")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(all(ci not in line for line in logs.output))
        self.assertNotIn(ci, response.wsgi_request.get_full_path())

    def test_partial_document_search_is_bounded_without_ad_fanout(self):
        for i in range(4):
            record = {"ci": f"TEST-{i}", "photo_file": ""}
            self.mapping[f"email:mapped{i}@petropar.gov.py"] = record
            self.mapping[f"username:mapped{i}"] = record
        with patch.object(services, "search_ad_users", return_value=[]) as ad:
            response = self.search("TEST-", "document_number")
        self.assertEqual(response.json()["status"], "candidates")
        self.assertEqual(len(response.json()["candidates"]), 4)
        ad.assert_not_called()
