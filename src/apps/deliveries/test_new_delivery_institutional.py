from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core import signing
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User


@override_settings(
    DIRECTORY_AD_DOMAIN="petropar.gov.py",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class NewDeliveryInstitutionalSearchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="operador-de-prueba", email="operador@petropar.gov.py",
            password="test-only", first_name="Operador", last_name="Prueba",
        )
        permissions = Permission.objects.filter(content_type__app_label="deliveries")
        self.user.user_permissions.add(*permissions)
        self.client.force_login(self.user)
        self.person = {
            "source": "RRHH", "_locator": {"source": "RRHH", "id": 12345},
            "_linked": [], "rrhh_id": 12345,
            "name": "Silvio Prueba", "full_name": "Silvio Prueba",
            "email": "", "employee_number": "9001", "position": "Analista",
            "organizational_unit": "Laboratorio", "branch": "Villa Elisa",
            "is_active": True, "is_person": True, "is_technical": False,
            "is_shared": False,
        }

    @patch("apps.deliveries.views.search_institutional_identities")
    def test_search_selects_person_without_local_user(self, search):
        search.return_value = [self.person]
        response = self.client.get(
            reverse("deliveries:new_delivery_recipient_search"), {"q": "silvio"}
        )
        self.assertEqual(response.status_code, 200)
        entries = response.json()["results"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["employee_number"], "9001")
        self.assertNotIn("id_personal", entries[0])
        self.assertNotIn("_locator", entries[0])

        with patch("apps.deliveries.views.resolve_common_identity", return_value=self.person):
            response = self.client.post(
                reverse("deliveries:new_delivery_recipient"),
                {"recipient_token": entries[0]["token"]},
            )
        self.assertRedirects(
            response, reverse("deliveries:new_delivery_assets"),
            fetch_redirect_response=False,
        )
        selection = self.client.session["new_delivery_wizard"]
        self.assertNotIn("recipient_id", selection)
        self.assertEqual(selection["recipient_identity"]["locator"]["id"], 12345)

    def test_invalid_token_is_rejected(self):
        response = self.client.post(
            reverse("deliveries:new_delivery_recipient"),
            {"recipient_token": "invalid-forged-token"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No fue posible validar")
        self.assertNotIn("new_delivery_wizard", self.client.session)

    def test_search_requires_delivery_permissions(self):
        outsider = User.objects.create_user(username="viewer", password="test-only")
        self.client.force_login(outsider)
        response = self.client.get(
            reverse("deliveries:new_delivery_recipient_search"), {"q": "silvio"}
        )
        self.assertEqual(response.status_code, 403)

    def test_search_ignores_single_character(self):
        response = self.client.get(
            reverse("deliveries:new_delivery_recipient_search"), {"q": "s"}
        )
        self.assertEqual(response.json()["results"], [])
