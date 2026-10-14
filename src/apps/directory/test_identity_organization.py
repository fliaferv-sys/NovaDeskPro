from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.accounts.models import User
from apps.core.models import Department
from apps.institution.identity_organization import OrganizationIndex
from apps.institution.models import InstitutionalIdentityAssignment, OrganizationalUnit
from .identity_policies import account_form_values
from .identity_services import get_institutional_directory, resolve_common_identity, search_common_identities


class CentralOrganizationTests(TestCase):
    def setUp(self):
        self.parent = OrganizationalUnit.objects.create(code="ORG-ROOT", name="Dirección", unit_type="DIRECTORATE")
        self.unit = OrganizationalUnit.objects.create(code="ORG-LEAF", name="Departamento", unit_type="DEPARTMENT", parent=self.parent)
        self.assignment = InstitutionalIdentityAssignment.objects.create(id_personal=1, email="persona@petropar.gov.py", username="persona", organizational_unit=self.unit)
        self.row = dict(IdPersonal=1, LegajoNro="100", NombresApellidos="Persona Institucional", Mail="persona@petropar.gov.py",
                        Telefono="123", Cargo="Cargo", Vinculo="Permanente", Estado="Activo", Ubicacion="Dependencia fuente")
        self.ad = dict(name="Persona Institucional", first_name="Persona", last_name="Institucional", email="persona@petropar.gov.py", username="persona", is_active=True)

    def test_directory_organization_queries_are_constant_for_many_people(self):
        rows = [dict(self.row, IdPersonal=n, Mail="", LegajoNro=str(n)) for n in range(1, 51)]
        with patch("apps.directory.identity_services.get_directory_employees", return_value=rows), patch("apps.directory.identity_services.search_ad_users_by_emails", return_value=[]), self.assertNumQueries(3):
            result = get_institutional_directory()
        self.assertEqual(len(result), 50)
        self.assertEqual([item["code"] for item in result[0]["organizational_path"]], ["ORG-ROOT", "ORG-LEAF"])

    def test_assignment_identifiers_must_not_contradict_each_other(self):
        result = OrganizationIndex().enrich(dict(id_personal=1, email="otra@petropar.gov.py", username="persona"))
        self.assertIsNone(result["organizational_unit"])
        self.assertTrue(result["organization_conflicts"])

    def test_inactive_unit_or_cyclic_path_never_produces_mapping(self):
        self.unit.is_active = False; self.unit.save()
        self.assertIsNone(OrganizationIndex().enrich({"id_personal": 1})["organizational_unit"])
        self.unit.is_active = True; self.unit.save()
        OrganizationalUnit.objects.filter(pk=self.parent.pk).update(parent=self.unit)
        self.assertIsNone(OrganizationIndex().enrich({"id_personal": 1})["organizational_unit"])
        with self.assertRaises(ValidationError):
            self.unit.full_clean()

    def test_local_unit_has_coherent_path_without_mapping(self):
        user = User.objects.create_user(username="local", email="local@example.test", organizational_unit=self.unit)
        identity = resolve_common_identity({"source": "LOCAL", "id": str(user.pk)})
        self.assertEqual(identity["organizational_unit"]["code"], self.unit.code)
        self.assertEqual(identity["organizational_path"][-1], identity["organizational_unit"])
        self.assertEqual(identity["location"], "")

    def test_rrhh_location_never_autocompletes_operational_department(self):
        Department.objects.create(name="Dependencia fuente", code="ORG-SUPPORT")
        values = account_form_values({"location": "Dependencia fuente"})
        self.assertNotIn("department", values)
        self.assertNotIn("branch", values)

    def test_common_search_and_signed_resolution_consolidate_rrhh_ad_without_local_account(self):
        def rrhh_search(value, **kwargs):
            return [self.row]
        with patch("apps.directory.identity_services.search_directory_employees", side_effect=rrhh_search), patch("apps.directory.identity_services.search_ad_users", return_value=[self.ad]), patch("apps.directory.identity_services._load_tercerizados", return_value={}):
            result = search_common_identities(self.row["Mail"], exact=True)
            self.assertTrue(result["exact_unique"])
            identity = result["identities"][0]
            self.assertEqual(identity["sources"], ["ACTIVE_DIRECTORY", "RRHH"])
            resolved = resolve_common_identity(identity["_locator"], identity["_linked"])
        self.assertEqual(resolved["rrhh_id"], 1)
        self.assertEqual(resolved["username"], "persona")
        self.assertEqual(resolved["organizational_unit"]["code"], self.unit.code)
        self.assertIsNone(resolved["local_user_id"])

    def test_duplicate_source_and_identifier_conflicts_remain_ambiguous(self):
        with patch("apps.directory.identity_services.search_directory_employees", return_value=[self.row, dict(self.row, IdPersonal=2)]), patch("apps.directory.identity_services.search_ad_users", return_value=[self.ad]), patch("apps.directory.identity_services._load_tercerizados", return_value={}):
            result = search_common_identities(self.row["Mail"], exact=True)
        self.assertFalse(result["exact_unique"])
        self.assertEqual(len(result["identities"]), 3)

    def test_explicit_id_and_conflicting_email_do_not_fall_back_to_another_person(self):
        from .identity_services import InstitutionalIdentityError, resolve_institutional_identity
        with patch("apps.directory.identity_services.get_directory_employee_by_id_personal", return_value=self.row), self.assertRaises(InstitutionalIdentityError):
            resolve_institutional_identity(id_personal=1, email="otra@petropar.gov.py")

    def test_legacy_exact_email_duplicates_do_not_choose_first(self):
        from .identity_services import InstitutionalIdentityError, resolve_institutional_identity
        with patch("apps.directory.identity_services.search_directory_employees", return_value=[self.row, dict(self.row, IdPersonal=2)]), self.assertRaises(InstitutionalIdentityError):
            resolve_institutional_identity(email=self.row["Mail"])
