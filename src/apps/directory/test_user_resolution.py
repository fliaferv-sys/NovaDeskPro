from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.models import User, Branch
from apps.accounts.tests import TEST_STORAGES
from apps.accounts.user_presentation import enrich_user_list
from apps.accounts.institutional_sync import text_key
from apps.core.models import Department
from apps.institution.models import OrganizationalUnit, InstitutionalIdentityAssignment
from apps.printing.models import PrintingDevice
from .identity_services import (
    resolve_identity_for_user, resolve_identities_for_users, search_institutional_identities,
    get_institutional_directory,
)
from .person_references import enrich_person_records
from .services import DirectoryDatabaseError
from .ad_services import ActiveDirectoryError


@override_settings(STORAGES=TEST_STORAGES, DIRECTORY_AD_DOMAIN="petropar.gov.py")
class UserResolutionParityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ariel.local", email="aferreira@petropar.gov.py",
            first_name="Ariel", last_name="Ferreira", role="ADMIN", id_personal=41, employee_number="1173", phone="0971000000")
        self.row = dict(IdPersonal=41, LegajoNro="1173", NombresApellidos="Ariel Ferreira", Mail=self.user.email,
                        Telefono="0971 000000", Cargo="Jefe Interino", Ubicacion="Dir.Tecno. de la Informac.",
                        Estado="Activo", Vinculo="Permanente")
        self.rows = [self.row]
        self.ad = [dict(name="Ariel Ferreira", first_name="Ariel", last_name="Ferreira", username="aferreira",
                       email=self.user.email, is_active=True)]

    def rrhh_search(self, value, *, search_field=None, limit=100, exact=False, **kwargs):
        columns = {"rrhh_id": "IdPersonal", "employee_number": "LegajoNro", "email": "Mail", "name": "NombresApellidos"}
        if search_field is None:
            return deepcopy(self.rows[:limit])
        match = lambda row: (text_key(value) in text_key(row.get(columns[search_field])) if search_field == "name"
                             else str(row.get(columns[search_field]) or "").strip().casefold() == str(value).strip().casefold())
        return deepcopy([row for row in self.rows if match(row)][:limit])

    def ad_search(self, value, *, search_field="email", limit=100, **kwargs):
        return deepcopy([row for row in self.ad if str(row.get(search_field) or "").strip().casefold() == value.strip().casefold()][:limit])

    @contextmanager
    def sources(self):
        with patch("apps.directory.user_resolution.search_directory_employees_batch", side_effect=lambda terms:
                   {term: self.rrhh_search(term[0], search_field=term[1]) for term in terms}) as batch_rrhh, patch(
                   "apps.directory.user_resolution.search_ad_users_batch", side_effect=lambda terms:
                   {term: self.ad_search(term[0], search_field=term[1]) for term in terms}) as batch_ad, patch(
                   "apps.accounts.institutional_sync.search_directory_employees", side_effect=self.rrhh_search) as individual_rrhh, patch(
                   "apps.accounts.institutional_sync.search_ad_users", side_effect=self.ad_search) as individual_ad:
            yield batch_rrhh, batch_ad, individual_rrhh, individual_ad

    def assert_parity(self):
        with self.sources():
            individual = resolve_identity_for_user(self.user)
            batch = resolve_identities_for_users([self.user])[self.user.pk]
        self.assertEqual(batch, individual)
        return batch

    def test_ariel_directory_list_and_individual_share_exact_rrhh_location(self):
        with self.sources() as (batch_rrhh, batch_ad, individual_rrhh, individual_ad), patch(
            "apps.directory.identity_services.get_directory_employees", return_value=[self.row]), patch(
            "apps.directory.identity_services.search_directory_employees", side_effect=self.rrhh_search), patch(
            "apps.directory.identity_services.search_ad_users", return_value=self.ad), patch(
            "apps.directory.identity_services.search_ad_users_by_emails", return_value=self.ad):
            directory = search_institutional_identities("Ariel Ferreira")
            global_directory = get_institutional_directory()
            enrich_user_list([self.user])
        self.assertEqual(directory[0]["location"], "Dir.Tecno. de la Informac.")
        self.assertEqual(global_directory[0]["username"], "aferreira")
        self.assertNotEqual(global_directory[0]["username"], self.user.username)
        self.assertEqual(self.user.display_location, directory[0]["location"])
        self.assertEqual(self.user.display_employee_number, "1173")
        self.assertEqual(self.user.display_position, "Jefe Interino")
        batch_rrhh.assert_called_once()
        batch_ad.assert_not_called()
        individual_rrhh.assert_not_called()
        individual_ad.assert_not_called()
        self.assertEqual(self.assert_parity()["location"], self.user.display_location)

    def test_location_remains_exact_and_empty_location_has_no_fk_fallback(self):
        self.user.branch = Branch.objects.create(code="PARITY-BRANCH", name="Sede local")
        self.user.department = Department.objects.create(code="PARITY-TEAM", name="Equipo operativo")
        unit = OrganizationalUnit.objects.create(code="PARITY-UNIT", name="Dependencia", unit_type="UNIT")
        InstitutionalIdentityAssignment.objects.create(id_personal=41, organizational_unit=unit)
        for location, expected in (("  Dir.Tecno. de la Informac.  ", "  Dir.Tecno. de la Informac.  "), ("", ""), (None, "")):
            self.row["Ubicacion"] = location
            with self.sources():
                enrich_user_list([self.user])
            self.assertEqual(self.user.display_location, expected)
            self.assertEqual(self.user.display_department, self.user.department)
            self.assertEqual(self.user.display_unit, "Dependencia")
            self.assertEqual(self.assert_parity()["location"], location or "")

    def test_identifier_contradiction_and_ambiguity_do_not_show_another_location(self):
        for rows in ([dict(self.row, IdPersonal=99)], [self.row, dict(self.row, LegajoNro="9999")],
                     [self.row, dict(self.row, IdPersonal=99, Ubicacion="Otra ubicación")]):
            self.rows = rows
            identity = self.assert_parity()
            self.assertEqual(identity["source"], "LOCAL")
            with self.sources():
                enrich_user_list([self.user])
            self.assertEqual(self.user.display_location, "")

    def test_email_and_phone_conflicts_are_identical_in_batch_and_individual(self):
        for changes in (dict(Mail="otra@petropar.gov.py"), dict(Telefono="0999999999"), dict(Estado="Inactivo")):
            self.rows = [dict(self.row, **changes)]
            self.assertEqual(self.assert_parity()["source"], "LOCAL")

    def test_ad_rrhh_bridge_has_identical_semantics_without_name_only_matching(self):
        self.user.id_personal = None; self.user.employee_number = None; self.user.username = "aferreira"
        self.row["Mail"] = ""
        self.assertEqual(self.assert_parity()["location"], self.row["Ubicacion"])
        with self.sources() as (rrhh, ad, individual_rrhh, individual_ad):
            enrich_user_list([self.user])
        self.assertEqual(rrhh.call_count, 2)
        ad.assert_called_once()
        individual_rrhh.assert_not_called(); individual_ad.assert_not_called()
        self.user.phone = ""
        self.assertEqual(self.assert_parity()["source"], "LOCAL")

    def test_many_users_share_one_source_load_without_individual_roundtrips(self):
        users = [self.user]
        for number in range(42, 62):
            users.append(User.objects.create_user(username=f"local-{number}", email=f"local-{number}@example.test",
                                                  id_personal=number, employee_number=str(number), phone="0971000000"))
            self.rows.append(dict(self.row, IdPersonal=number, LegajoNro=str(number), Mail=users[-1].email))
        with self.sources() as (rrhh, ad, individual_rrhh, individual_ad), self.assertNumQueries(2):
            enrich_user_list(users)
        rrhh.assert_called_once(); ad.assert_not_called()
        individual_rrhh.assert_not_called(); individual_ad.assert_not_called()
        self.assertTrue(all(user.display_location == self.row["Ubicacion"] for user in users))

    def test_get_list_and_profile_do_not_write_or_persist_location(self):
        with patch("apps.accounts.signals.try_sync_user_institutional_data"):
            self.client.force_login(self.user)
        before = User.objects.values().get(pk=self.user.pk)
        self.assertNotIn("location", before)
        for location, expected in ((self.row["Ubicacion"], self.row["Ubicacion"]), ("", "Sin registrar")):
            self.row["Ubicacion"] = location
            with self.sources(), CaptureQueriesContext(connection) as queries:
                response = self.client.get(reverse("user_list"))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, expected)
            self.assertFalse(any(query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for query in queries))
            self.assertEqual(User.objects.values().get(pk=self.user.pk), before)
        with self.sources(), CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["profile_user"].display_location, "")
        self.assertFalse(any(query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for query in queries))
        self.assertEqual(User.objects.values().get(pk=self.user.pk), before)

    def test_batch_does_not_depend_on_the_truncated_global_directory(self):
        with self.sources(), patch("apps.directory.identity_services.get_institutional_directory") as global_list:
            enrich_user_list([self.user])
        global_list.assert_not_called()
        self.assertEqual(self.user.display_location, self.row["Ubicacion"])

    def test_ticket_requester_uses_confirmed_ids_instead_of_email_only_context(self):
        from apps.integrations.technical_context import resolve_technical_context
        from apps.integrations.test_ip_lookup import mock_glpi
        with self.sources(), patch("apps.integrations.technical_context.institutional_people") as other_path:
            context = resolve_technical_context(requester=self.user, ip="192.0.2.1",
                                                client_factory=lambda: mock_glpi(count=0))
        data = context["person"]["candidates"][0]["data"]
        self.assertEqual(data["location"], self.row["Ubicacion"])
        self.assertEqual(data["employee_number"], "1173")
        self.assertEqual(context["person"]["confidence"], "CONFIRMADA")
        other_path.assert_not_called()

    def test_linked_printing_and_inventory_presentation_uses_same_user_resolution(self):
        device = PrintingDevice(responsible_user=self.user)
        with self.sources() as (rrhh, ad, single_rrhh, single_ad):
            enrich_person_records([device], "responsible_identity", "responsible_user")
        self.assertEqual(device.person_identity["location"], self.assert_parity()["location"])
        rrhh.assert_called_once(); single_rrhh.assert_not_called(); single_ad.assert_not_called()

    def test_rrhh_failure_keeps_local_data_and_no_institutional_location(self):
        with patch("apps.directory.user_resolution.search_directory_employees_batch", side_effect=DirectoryDatabaseError("offline")):
            resolved = resolve_identities_for_users([self.user])[self.user.pk]
        self.assertEqual(resolved["source"], "LOCAL")
        self.assertEqual(resolved["location"], "")

    def test_ad_failure_or_ambiguity_cannot_bridge_a_person(self):
        self.user.id_personal = None; self.user.employee_number = None; self.user.username = "aferreira"
        self.row["Mail"] = ""
        self.ad.append(deepcopy(self.ad[0]))
        self.assertEqual(self.assert_parity()["source"], "LOCAL")
        with self.sources(), patch("apps.directory.user_resolution.search_ad_users_batch", side_effect=lambda terms:
                                  {term: ActiveDirectoryError("offline") for term in terms}):
            self.assertEqual(resolve_identities_for_users([self.user])[self.user.pk]["source"], "LOCAL")
