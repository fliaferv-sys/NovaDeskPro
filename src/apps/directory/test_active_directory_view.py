from copy import deepcopy
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from apps.accounts.models import User


class ActiveDirectoryPresentationTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(username="directory-viewer", email="viewer@example.test")
        self.client.force_login(user)

    def identity(self, active, relationship="Permanente", consolidated=False):
        return {"source": "RRHH", "sources": ["ACTIVE_DIRECTORY", "RRHH"] if consolidated else ["RRHH"],
            "source_label": "AD + RR.HH." if consolidated else "RR.HH.", "id_personal": 1,
            "employee_number": "001", "name": "Persona activa" if active else "Persona inactiva",
            "first_name": "", "last_name": "", "location": "Sede", "phone": "123", "email": "persona@example.test",
            "status": "Activo" if active else "Inactivo", "employment_type": relationship, "position": "Cargo",
            "username": "persona", "is_active": active, "photo_url": "/media/existing.jpg"}

    def test_active_visible_inactive_hidden_and_total_only_active(self):
        rows = [self.identity(True), self.identity(False)]
        original = deepcopy(rows)
        with patch("apps.directory.views.get_institutional_directory", return_value=rows):
            response = self.client.get(reverse("directory:home"))
        self.assertContains(response, "Persona activa")
        self.assertNotContains(response, "Persona inactiva")
        self.assertEqual(response.context["directory_kpis"]["total"], 1)
        self.assertEqual(rows, original)

    def test_consolidated_final_activity_controls_visibility(self):
        rows = [self.identity(True, consolidated=True), self.identity(False, consolidated=True)]
        with patch("apps.directory.views.get_institutional_directory", return_value=rows):
            response = self.client.get(reverse("directory:home"))
        self.assertEqual(response.context["employees"], [rows[0]])
        self.assertContains(response, "AD + RR.HH.")
        self.assertContains(response, "/media/existing.jpg")

    def test_search_page_and_ajax_exclude_inactive(self):
        rows = [self.identity(True), self.identity(False)]
        with patch("apps.directory.views.get_institutional_directory", return_value=rows), \
             patch("apps.directory.views.search_institutional_identities", return_value=rows):
            response = self.client.get(reverse("directory:home"), {"q": "Persona"})
            self.assertEqual(response.context["employees"], [rows[0]])
            response = self.client.get(reverse("directory:employee_search_api"), {"q": "Persona"})
        self.assertEqual(len(response.json()["employees"]), 1)
        self.assertTrue(response.json()["employees"][0]["is_active"])

    def test_all_kpi_classifications_count_active_only(self):
        rows = [self.identity(active, relationship) for active in (True, False)
            for relationship in ("Permanente", "Contratado", "Tercerizado", "Comisionado")]
        with patch("apps.directory.views.get_institutional_directory", return_value=rows):
            response = self.client.get(reverse("directory:home"))
        self.assertEqual(response.context["directory_kpis"], {
            "total": 4, "permanent": 1, "contracted": 1, "outsourced": 1, "other": 1})
        self.assertEqual(len(response.context["employees"]), 4)

    def test_unknown_activity_not_invented(self):
        identity = self.identity(True)
        identity["is_active"] = None
        with patch("apps.directory.views.get_institutional_directory", return_value=[identity]):
            response = self.client.get(reverse("directory:home"))
        self.assertEqual(response.context["employees"], [])
        self.assertEqual(response.context["directory_kpis"]["total"], 0)
