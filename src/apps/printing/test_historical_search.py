from unittest.mock import patch

from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import Department
from apps.institution.models import OrganizationalUnit
from .historical_notes import historical_values
from .models import PrintingDevice, PrintingDeviceNetworkDetection, PrintingDeviceUserAssignment


class HistoricalNotesParserTests(SimpleTestCase):
    def test_only_explicit_labels_at_line_start_are_parsed(self):
        notes = "Comentario: Responsable: Ignore\n Responsable : ARIEL FERREIRA\r\nDEPENDENCIA: Gerencia Comercial\rResponsable: SILVIO LOPEZ\nResponsable: ariel ferreira\nResponsable:   \nOtra Dependencia: Ignore"
        self.assertEqual(historical_values(notes), {
            "responsibles": ["ARIEL FERREIRA", "SILVIO LOPEZ"],
            "dependencies": ["Gerencia Comercial"],
        })

    def test_empty_notes_are_safe(self):
        self.assertEqual(historical_values(None), {"responsibles": [], "dependencies": []})


class PrintingHistoricalSearchTests(TestCase):
    def setUp(self):
        sync = patch("apps.accounts.signals.try_sync_user_institutional_data")
        sync.start()
        self.addCleanup(sync.stop)
        enrich = patch("apps.printing.inventory_users.enrich_person_records", side_effect=lambda records, *args: list(records))
        enrich.start()
        self.addCleanup(enrich.stop)
        detail_enrich = patch("apps.printing.views.enrich_person_records", side_effect=lambda records, *args: list(records))
        detail_enrich.start()
        self.addCleanup(detail_enrich.stop)
        self.operator = User.objects.create_user(username="history-operator", email="history-operator@example.test", role="ADMIN")
        self.ariel = PrintingDevice.objects.create(photocopier_id="12", notes="Responsable: ARIEL FERREIRA\r\nDependencia: Gerencia Comercial")
        self.mariel = PrintingDevice.objects.create(photocopier_id="27", notes="Responsable: MARIEL Y SANDRA\nDependencia: Dpto. Comercial")
        self.silvio = PrintingDevice.objects.create(photocopier_id="45", is_active=False, notes="Responsable: SILVIO LOPEZ\nDependencia: Dpto. Comercial")
        self.url = reverse("printing:devices_by_model")
        self.client.force_login(self.operator)

    def search(self, term="", **filters):
        response = self.client.get(self.url, {"search": term, **filters})
        self.assertEqual(response.status_code, 200)
        return response, [d.pk for d in response.context["devices"]]

    def test_ariel_matches_active_label_and_not_mariel(self):
        for term in ("ariel", "ARIEL", "ferreira", "Ariel Ferreira"):
            with self.subTest(term=term):
                response, ids = self.search(term)
                self.assertEqual(ids, [self.ariel.pk])
                self.assertEqual(response.context["total"], 1)

    def test_silvio_respects_active_archived_and_all(self):
        self.assertEqual(self.search("silvio")[1], [])
        for lifecycle in ("archived", "all"):
            self.assertEqual(self.search("silvio", lifecycle=lifecycle)[1], [self.silvio.pk])

    def test_comercial_matches_only_dependency_values_with_lifecycle(self):
        self.assertEqual(set(self.search("comercial")[1]), {self.ariel.pk, self.mariel.pk})
        self.assertEqual(set(self.search("comercial", lifecycle="all")[1]), {self.ariel.pk, self.mariel.pk, self.silvio.pk})
        self.assertEqual(self.search("comercial", lifecycle="archived")[1], [self.silvio.pk])

    def test_notes_without_labels_and_audit_mentions_do_not_match(self):
        PrintingDevice.objects.create(photocopier_id="99", notes='Ariel Ferreira visitó Comercial\nComentario: Responsable: Ariel\n{"event": "Responsable: Ariel", "dependency": "Comercial"}')
        self.assertEqual(self.search("ariel")[1], [self.ariel.pk])
        self.assertEqual(set(self.search("comercial")[1]), {self.ariel.pk, self.mariel.pk})
        self.assertEqual(self.search("responsable")[1], [])

    def test_sql_labels_support_case_whitespace_and_line_endings(self):
        for ending in ("\n", "\r\n", "\r"):
            PrintingDevice.objects.filter(pk=self.ariel.pk).update(notes="Otra línea" + ending + "\tRESPONSABLE \t:  ARIEL FERREIRA" + ending + " dependencia: Gerencia Comercial")
            self.assertEqual(self.search("ariel")[1], [self.ariel.pk])
            self.assertIn(self.ariel.pk, self.search("comercial")[1])

    def test_regex_characters_in_input_are_literal(self):
        self.assertEqual(self.search(".*")[1], [])
        self.assertEqual(self.search("ariel|")[1], [])

    def test_historical_dependency_filter_is_separate_from_user_department(self):
        department = Department.objects.create(name="Comercial", code="HIST-COM")
        unit = OrganizationalUnit.objects.create(name="Gerencia Comercial", code="HIST-GC", unit_type="MANAGEMENT")
        self.assertEqual(self.search(department=str(department.pk))[1], [])
        self.assertEqual(self.search(user_unit=str(unit.pk))[1], [])
        self.assertEqual(self.search(installation="Gerencia Comercial")[1], [])
        self.assertEqual(set(self.search(historical_dependency="Comercial")[1]), {self.ariel.pk, self.mariel.pk})
        self.assertEqual(self.search(historical_dependency="Gerencia Comercial")[1], [self.ariel.pk])
        self.assertEqual(self.search("Ariel", historical_dependency="Comercial")[1], [self.ariel.pk])

    def test_structured_relations_still_match_without_duplicates(self):
        person = User.objects.create_user(username="history-ariel", email="history-ariel@example.test", first_name="Ariel", last_name="Ferreira")
        PrintingDevice.objects.filter(pk=self.ariel.pk).update(responsible_user=person)
        assigned = PrintingDevice.objects.create(photocopier_id="70")
        for device in (self.ariel, assigned):
            PrintingDeviceUserAssignment.objects.create(device=device, user=person, assigned_by=self.operator)
        response, ids = self.search("ariel")
        self.assertEqual(set(ids), {self.ariel.pk, assigned.pk})
        self.assertEqual(len(ids), 2)
        self.assertEqual(response.context["total"], 2)

    def test_finished_assignment_is_not_matched_as_current(self):
        person = User.objects.create_user(username="ended-history", email="ended-history@example.test", first_name="RemovedPerson")
        at = timezone.now()
        PrintingDeviceUserAssignment.objects.create(device=self.mariel, user=person, assigned_by=self.operator,
            assigned_at=at, ended_at=at, ended_by=self.operator)
        self.assertEqual(self.search("RemovedPerson")[1], [])

    def test_history_display_is_explicit_and_escaped_in_list_and_detail(self):
        response, _ = self.search("ariel")
        self.assertContains(response, "Responsable histórico (observaciones)")
        self.assertContains(response, "Sin vínculo institucional verificado")
        self.assertContains(response, "Dependencia histórica de instalación (observaciones)")
        PrintingDevice.objects.filter(pk=self.ariel.pk).update(notes="Responsable: <script>alert(1)</script>\nDependencia: Gerencia Comercial")
        for response in (self.client.get(self.url), self.client.get(reverse("printing:device_detail", args=[self.ariel.pk]))):
            self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")
            self.assertNotContains(response, "<script>alert(1)</script>")

    def test_pagination_counts_and_preserves_historical_filter(self):
        PrintingDevice.objects.bulk_create([PrintingDevice(photocopier_id=f"H{i:03}", notes="Responsable: ARIEL FERREIRA\nDependencia: Gerencia Comercial") for i in range(55)])
        response, first = self.search("ariel", historical_dependency="Comercial")
        self.assertEqual(response.context["total"], 56)
        self.assertEqual(len(first), 50)
        next_response, second = self.search("ariel", historical_dependency="Comercial", page=2)
        self.assertEqual(len(second), 6)
        self.assertFalse(set(first) & set(second))
        self.assertContains(response, "historical_dependency=Comercial")

    def test_search_is_read_only_and_preserves_original_notes(self):
        models = (PrintingDevice, PrintingDeviceNetworkDetection, PrintingDeviceUserAssignment, User)
        before = [list(model.objects.order_by("pk").values()) for model in models]
        with CaptureQueriesContext(connection) as queries:
            self.search("ariel", historical_dependency="Comercial")
        self.assertEqual([list(model.objects.order_by("pk").values()) for model in models], before)
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))
