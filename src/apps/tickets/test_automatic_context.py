import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.template.loader import render_to_string
from django.urls import reverse

from apps.accounts.models import User
from apps.core.models import Department
from apps.inventory.models import Asset
from apps.tickets.models import Ticket
from apps.tickets.context_snapshot import build_snapshot, review_token
from apps.integrations.automatic_context import resolve_automatic_context, automatic_selection


class AutomaticContextTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="auto-person", email="auto@example.test", role="CLIENT")
        self.other = User.objects.create_user(username="other-person", email="other-auto@example.test")
        Department.objects.create(name="Soporte", code="SUPPORT")
        self.context = {"requester": {"full_name": "Solicitante", "email": self.user.email},
            "person": {"candidates": [{"data": {"full_name": "Persona institucional", "employee_number": "001", "employment_type": "Permanente"},
                                      "sources": ["RRHH", "ACTIVE_DIRECTORY"], "confidence": "CONFIRMADA"}], "incomplete": False},
            "devices": [{"data": {"type": "Computer", "name": "PC601", "serial": "SER-1"},
                         "ip": None, "confidence": "PROBABLE", "association_confidence": "CONFIRMADA", "auto_eligible": True,
                         "glpi_id": "1", "provenance": {"name": "GLPI"},
                         "detected_user": {"candidates": [{"data": {"full_name": "Usuario distinto"}, "sources": ["RRHH"], "confidence": "PROBABLE"}]},
                         "novadesk_assets": [{"id": "asset-1", "code": "EQ-1", "can_select": True,
                                              "responsible": {"full_name": "Responsable distinto"}}]}], "warnings": [], "automatic": True}

    def proof(self):
        return json.dumps({**automatic_selection(self.context), "token": review_token(self.context, self.user, {"automatic": True})})

    def test_client_unique_safe_context_snapshot_and_requester_preserved(self):
        self.client.force_login(self.user)
        with patch("apps.tickets.context_snapshot.resolve_automatic_context", return_value=self.context):
            response = self.client.post(reverse("tickets:ticket_create"), {"title": "Problema", "description": "Solo problema",
                "priority": "LOW", "category": "HARDWARE", "request_flow": "OPERATIONAL"})
        self.assertEqual(response.status_code, 302)
        ticket = Ticket.objects.get()
        self.assertEqual(ticket.requester_id, self.user.pk)
        self.assertEqual(ticket.description, "Solo problema")
        self.assertIsNone(ticket.asset_id)
        snapshot = ticket.technical_context_snapshot
        self.assertEqual(snapshot["device"]["confidence"], "PROBABLE")
        self.assertEqual(snapshot["device"]["association_confidence"], "CONFIRMADA")
        self.assertEqual(snapshot["detected_user"]["full_name"], "Usuario distinto")
        self.assertEqual(snapshot["novadesk_asset"]["responsible_identity"]["full_name"], "Responsable distinto")

    def test_client_no_equipment_multiple_or_probable_not_associated(self):
        for devices in ([], [self.context["devices"][0]] * 2, [dict(self.context["devices"][0], auto_eligible=False)]):
            with patch("apps.tickets.context_snapshot.resolve_automatic_context", return_value=dict(self.context, devices=devices)):
                self.assertIsNone(build_snapshot(self.user, ""))

    def test_signed_auto_selection_revalidated_and_changed_results_rejected(self):
        proof = self.proof()
        with patch("apps.tickets.context_snapshot.resolve_automatic_context", return_value=self.context) as resolve:
            self.assertIsNotNone(build_snapshot(self.user, proof))
            resolve.assert_called_once_with(self.user)
        changed = deepcopy(self.context)
        changed["devices"].append(deepcopy(changed["devices"][0]))
        with patch("apps.tickets.context_snapshot.resolve_automatic_context", return_value=changed):
            self.assertIsNone(build_snapshot(self.user, proof))

    def test_client_cannot_forge_person_or_equipment_and_opt_out_is_respected(self):
        selected = json.loads(self.proof())
        selected.update(email="forged@example.test", serial="FORGED", responsible="forged")
        with patch("apps.tickets.context_snapshot.resolve_automatic_context", return_value=self.context):
            snapshot = build_snapshot(self.user, json.dumps(selected))
        self.assertEqual(snapshot["device"]["serial"], "SER-1")
        self.assertNotIn("forged", json.dumps(snapshot))
        selected.update(device=5, email="forged@example.test", mac="forged")
        with patch("apps.tickets.context_snapshot.resolve_automatic_context", return_value=self.context):
            self.assertIsNone(build_snapshot(self.user, json.dumps(selected)))
        with patch("apps.tickets.context_snapshot.resolve_automatic_context") as resolve:
            self.assertIsNone(build_snapshot(self.user, "skip"))
        resolve.assert_not_called()

    def test_endpoint_client_minimal_staff_rich_cache_and_no_writes(self):
        self.client.force_login(self.user)
        with patch("apps.tickets.technical_context_views.resolve_automatic_context", return_value=self.context) as resolve, CaptureQueriesContext(connection) as queries:
            first = self.client.get(reverse("tickets:automatic_context"))
            second = self.client.get(reverse("tickets:automatic_context"))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(resolve.call_count, 1)
        for forbidden in ("glpi_id", "confidence", "Usuario distinto", "Responsable distinto", "serial"):
            self.assertNotIn(forbidden, first.content.decode())
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))
        for role in ("ADMIN", "TECHNICIAN"):
            self.user.role = role
            self.user.save(update_fields=["role"])
            response = self.client.get(reverse("tickets:automatic_context"))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["devices"][0]["data"]["name"], "PC601")

    def test_template_client_simple_staff_collapsible_manual_tool(self):
        request = SimpleNamespace(user=self.user)
        html = render_to_string("tickets/technical_context.html", {"request": request})
        self.assertIn("Datos detectados automáticamente", html)
        for forbidden in ("data-context-query", "hostname", "Consulta técnica avanzada", "Confianza", "GLPI"):
            self.assertNotIn(forbidden, html)
        detail = render_to_string("tickets/context_snapshot_detail.html", {"request": request, "snapshot": {
            "device": {"name": "PC601", "ip": "192.0.2.1", "confidence": "PROBABLE"}}})
        self.assertIn("PC601", detail)
        self.assertNotIn("192.0.2.1", detail)
        self.assertNotIn("Confianza", detail)
        self.user.role = "ADMIN"
        html = render_to_string("tickets/technical_context.html", {"request": request})
        self.assertIn("<details><summary>Consulta técnica avanzada", html)
        self.assertIn("data-auto-url", html)
        self.assertIn("max-width:768px", html)

    def test_failures_allow_creating_without_snapshot(self):
        for failure in (RuntimeError("GLPI secret"), RuntimeError("Directory secret")):
            with patch("apps.tickets.context_snapshot.resolve_automatic_context", side_effect=failure):
                self.assertIsNone(build_snapshot(self.user, ""))

    def test_cache_failure_safe_and_manual_client_permission_unchanged(self):
        self.client.force_login(self.user)
        with patch("apps.tickets.technical_context_views.cache.get", side_effect=RuntimeError("private-secret")):
            response = self.client.get(reverse("tickets:automatic_context"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("private-secret", response.content.decode())
        self.assertEqual(self.client.get(reverse("tickets:technical_context"), {"ip": "192.0.2.1"}).status_code, 403)

    def test_automatic_resolver_local_custody_no_updates_or_users_created(self):
        asset = Asset.objects.create(internal_code="AUTO-1", serial_number="SER-1", assigned_user=self.user)
        before = Asset.objects.values().get(pk=asset.pk)
        with patch("apps.integrations.automatic_context.resolve_technical_context", return_value={"devices": [], "warnings": []}), CaptureQueriesContext(connection) as queries:
            result = resolve_automatic_context(self.user)
        self.assertEqual(automatic_selection(result)["device"], 0)
        self.assertEqual(result["devices"][0]["confidence"], "PROBABLE")
        self.assertEqual(Asset.objects.values().get(pk=asset.pk), before)
        self.assertEqual(User.objects.count(), 2)
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))

    def test_glpi_and_local_same_serial_not_duplicated(self):
        Asset.objects.create(internal_code="AUTO-2", serial_number="SER-1", assigned_user=self.user)
        with patch("apps.integrations.automatic_context.resolve_technical_context", return_value=deepcopy(self.context)):
            result = resolve_automatic_context(self.user)
        self.assertEqual(len(result["devices"]), 1)
        self.assertIsNotNone(automatic_selection(result))

    def test_ambiguous_serial_candidates_not_automatic(self):
        Asset.objects.create(internal_code="AUTO-3", serial_number="SER-1", assigned_user=self.user)
        context = deepcopy(self.context)
        context["devices"].append(deepcopy(context["devices"][0]))
        with patch("apps.integrations.automatic_context.resolve_technical_context", return_value=context):
            result = resolve_automatic_context(self.user)
        self.assertIsNone(automatic_selection(result))
