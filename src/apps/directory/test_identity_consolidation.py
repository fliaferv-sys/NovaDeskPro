from copy import deepcopy
from django.test import SimpleTestCase, override_settings
from .identity_services import consolidate_institutional_identities


@override_settings(DIRECTORY_AD_DOMAIN="petropar.gov.py")
class InstitutionalConsolidationTests(SimpleTestCase):
    def identities(self):
        return [
            {"source": "ACTIVE_DIRECTORY", "username": "vhpalma", "email": " VHPALMA@petropar.gov.py ",
             "full_name": "Persona Institucional", "_locator": {"source": "ACTIVE_DIRECTORY", "username": "vhpalma"}},
            {"source": "RRHH", "email": "vhpalma@petropar.gov.py", "full_name": "PERSONA INSTITUCIONAL",
             "position": "Jefe de Departamento Interino", "phone": "5550100", "location": "Secretaría General",
             "organizational_unit": {"name": "Secretaría General"}, "_locator": {"source": "RRHH", "id": 1}},
        ]

    def test_same_institutional_email_and_ad_username_consolidate_complementary_fields(self):
        identities = self.identities()
        original = deepcopy(identities)
        result = consolidate_institutional_identities(identities)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["username"], "vhpalma")
        self.assertEqual(result[0]["email"], "vhpalma@petropar.gov.py")
        self.assertEqual(result[0]["position"], "Jefe de Departamento Interino")
        self.assertEqual(result[0]["phone"], "5550100")
        self.assertEqual(result[0]["location"], "Secretaría General")
        self.assertEqual(result[0]["sources"], ["ACTIVE_DIRECTORY", "RRHH"])
        self.assertEqual(identities, original)

    def test_same_name_different_email_not_merged(self):
        identities = self.identities()
        identities[1]["email"] = "otra@petropar.gov.py"
        self.assertEqual(len(consolidate_institutional_identities(identities)), 2)

    def test_conflicts_preserve_candidates(self):
        for field, left, right in [("username", "vhpalma", "other"), ("document_number", "1", "2"),
            ("employee_number", "1", "2"), ("full_name", "Persona Uno", "Persona Dos"),
            ("phone", "111", "222"), ("is_active", True, False)]:
            identities = self.identities()
            identities[0][field], identities[1][field] = left, right
            with self.subTest(field=field):
                self.assertEqual(len(consolidate_institutional_identities(identities)), 2)

    def test_duplicate_source_never_collapsed(self):
        identities = self.identities()
        identities.append(dict(identities[1], _locator={"source": "RRHH", "id": 2}))
        self.assertEqual(len(consolidate_institutional_identities(identities)), 3)

    def test_shared_email_alone_without_username_or_personal_id_insufficient(self):
        identities = self.identities()
        identities[0].pop("username")
        self.assertEqual(len(consolidate_institutional_identities(identities)), 2)
        for identity in identities:
            identity["employee_number"] = "001"
        self.assertEqual(len(consolidate_institutional_identities(identities)), 1)

    def test_non_institutional_email_not_merged(self):
        identities = self.identities()
        for identity in identities:
            identity["email"] = "vhpalma@example.test"
        self.assertEqual(len(consolidate_institutional_identities(identities)), 2)
