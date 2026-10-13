from unittest.mock import patch
from django.test import TestCase, SimpleTestCase, override_settings
from django.db import connection
from django.test.utils import CaptureQueriesContext
from apps.accounts.models import User
from apps.directory import identity_services as service
from apps.directory.ad_services import search_ad_users_by_emails


@override_settings(DIRECTORY_AD_DOMAIN="petropar.gov.py")
class DirectoryConsolidationTests(TestCase):
    def rrhh(self, **kwargs):
        return dict({"IdPersonal": 1, "NombresApellidos": "PERSONA INSTITUCIONAL", "Mail": "persona@petropar.gov.py",
            "LegajoNro": "001", "Cargo": "Cargo RRHH", "Telefono": "123", "Ubicacion": "Secretaria",
            "Vinculo": "Permanente", "Estado": "Activo"}, **kwargs)

    def ad(self, **kwargs):
        return dict({"name": "Persona Institucional", "username": "persona", "email": "persona@petropar.gov.py", "is_active": True}, **kwargs)

    def full(self, rrhh, ad):
        with patch.object(service, "get_directory_employees", return_value=rrhh), \
             patch.object(service, "search_ad_users_by_emails", return_value=ad), \
             patch.object(service, "_build_employee_photo_url", return_value="/media/existing.jpg"):
            return service.get_institutional_directory()

    def test_complementary_fields_photo_sources_and_no_writes(self):
        before = User.objects.count()
        with CaptureQueriesContext(connection) as queries:
            result = self.full([self.rrhh()], [self.ad()])
        self.assertEqual(len(result), 1)
        person = result[0]
        self.assertEqual(person["source_label"], "AD + RR.HH.")
        for key, expected in {"username": "persona", "email": "persona@petropar.gov.py", "employee_number": "001",
            "position": "Cargo RRHH", "phone": "123", "employment_type": "Permanente", "photo_url": "/media/existing.jpg"}.items():
            self.assertEqual(person[key], expected)
        self.assertTrue(person["is_active"])
        self.assertEqual(User.objects.count(), before)
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))

    def test_missing_mail_uses_existing_explicit_personal_anchor(self):
        User.objects.create_user(username="persona", email="persona@petropar.gov.py", id_personal=1)
        result = self.full([self.rrhh(Mail="")], [self.ad()])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["email"], "persona@petropar.gov.py")
        self.assertEqual(result[0]["username"], "persona")

    def test_missing_mail_without_identifier_never_matches_name(self):
        result = self.full([self.rrhh(Mail="")], [self.ad()])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["email"], "")

    def test_conflicting_mail_names_and_activity_keep_separate(self):
        for ad in [self.ad(email="otra@petropar.gov.py"), self.ad(name="Persona Diferente"), self.ad(is_active=False)]:
            with self.subTest(ad=ad):
                result = self.full([self.rrhh()], [ad])
                self.assertEqual(len(result), 2)
                self.assertEqual(result[0]["status"], "Activo")
                self.assertTrue(result[0]["is_active"])
        inactive = self.full([self.rrhh(Estado="Inactivo")], [])
        self.assertFalse(inactive[0]["is_active"])

    def test_rrhh_only_still_visible(self):
        result = self.full([self.rrhh()], [])
        self.assertEqual(result[0]["sources"], ["RRHH"])
        self.assertEqual(result[0]["username"], "")

    def test_source_badge_username_and_safe_search_json(self):
        user = User.objects.create_user(username="viewer", email="viewer@example.test")
        self.client.force_login(user)
        from django.urls import reverse
        directory = self.full([self.rrhh()], [self.ad()])
        with patch("apps.directory.views.get_institutional_directory", return_value=directory):
            response = self.client.get(reverse("directory:home"))
        self.assertContains(response, "AD + RR.HH.")
        self.assertContains(response, "<dt>Usuario</dt><dd>persona</dd>", html=True)
        with patch("apps.directory.views.search_institutional_identities", return_value=directory):
            response = self.client.get(reverse("directory:employee_search_api"), {"q": "persona"})
        person = response.json()["employees"][0]
        self.assertEqual(person["sources"], ["ACTIVE_DIRECTORY", "RRHH"])
        self.assertNotIn("_locator", person)
        self.assertNotIn("document_number", person)

    def test_search_consolidates_and_ad_only_stays_outsourced(self):
        with patch.object(service, "search_directory_employees", return_value=[self.rrhh()]), \
             patch.object(service, "search_ad_users", return_value=[self.ad()]), \
             patch.object(service, "search_ad_users_by_emails", return_value=[]):
            result = service.search_institutional_identities("persona")
        self.assertEqual(len(result), 1)
        with patch.object(service, "search_directory_employees", return_value=[]), \
             patch.object(service, "search_ad_users", return_value=[self.ad()]), \
             patch.object(service, "search_ad_users_by_emails", return_value=[]), \
             patch.object(service, "_get_tercerizado", return_value={"ci": "synthetic"}), \
             patch.object(service, "_build_tercerizado_photo_url", return_value="/media/outsourced.jpg"):
            result = service.search_institutional_identities("persona")
        self.assertEqual(result[0]["employment_type"], "Tercerizado")
        self.assertEqual(result[0]["photo_url"], "/media/outsourced.jpg")


class ADBatchTests(SimpleTestCase):
    @patch("apps.directory.ad_services._search_ad_filter")
    def test_exact_mail_filter_batches_and_saturation_are_safe(self, query):
        query.return_value = [{"username": "p", "email": "p@example.test"}]
        self.assertEqual(len(search_ad_users_by_emails(["P@EXAMPLE.TEST"])), 1)
        self.assertIn("(mail=p@example.test)", query.call_args.args[0])
        query.return_value = [{"username": "p", "email": "p@example.test"}] * 100
        self.assertEqual(search_ad_users_by_emails(["p@example.test"]), [])
