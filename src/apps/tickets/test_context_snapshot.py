import json
from copy import deepcopy
from unittest.mock import patch

from django.test import TestCase
from django.core.signing import SignatureExpired
from django.urls import reverse
from django.template.loader import render_to_string

from apps.accounts.models import User
from apps.inventory.models import Asset
from apps.core.models import Department
from apps.tickets.models import Ticket
from apps.tickets.forms import TicketForm
from apps.tickets.context_snapshot import build_snapshot, review_token


class ContextSnapshotTests(TestCase):
    def setUp(self):
        Department.objects.create(name="Soporte", code="SUPPORT")
        self.user = User.objects.create_user(username="snapshot-tech", email="snapshot-tech@example.test", role="TECHNICIAN")
        self.owner = User.objects.create_user(username="snapshot-owner", email="snapshot-owner@example.test", first_name="Responsable")
        self.asset = Asset.objects.create(internal_code="SNAP-1", serial_number="ABC", assigned_user=self.owner)
        self.context = {
            "requester": {"full_name": "Solicitante local", "username": self.user.username},
            "person": {"candidates": [{"data": {"full_name": "Solicitante institucional", "employee_number": "002"}, "sources": ["RRHH"], "confidence": "CONFIRMADA"}]},
            "warnings": [], "devices": [{
                "data": {"type": "Computer", "name": "pc-test", "serial": "ABC", "mac": "aa:bb:cc:dd:ee:ff"},
                "ip": "192.0.2.1", "glpi_id": "537", "confidence": "CONFIRMADA", "provenance": {"name": "GLPI"},
                "detected_user": {"candidates": [{"data": {"full_name": "Persona sin cuenta", "email": "external@example.test"}, "sources": ["RRHH"], "confidence": "PROBABLE"}]},
                "novadesk_assets": [{"id": str(self.asset.pk), "code": "SNAP-1", "responsible": {"full_name": "Responsable", "username": self.owner.username}}],
            }],
        }

    def selection(self, **changes):
        selected = {"token": review_token(self.context, self.user, {"ip": "192.0.2.1", "hostname": ""}),
                    "device": 0, "requester": 0, "detected": 0, "asset": 0}
        selected.update(changes)
        return json.dumps(selected)

    def resolve(self, selection=None, context=None):
        with patch("apps.tickets.context_snapshot.resolve_technical_context", return_value=context or self.context), patch("apps.tickets.context_snapshot.resolve_automatic_context", return_value={"devices": []}):
            return build_snapshot(self.user, selection if selection is not None else self.selection())

    def test_distinct_people_no_source_writes(self):
        before = Asset.objects.values().get(pk=self.asset.pk)
        with self.assertNumQueries(0):
            snapshot = self.resolve()
        self.assertEqual(snapshot["requester_identity"]["full_name"], "Solicitante institucional")
        self.assertEqual(snapshot["detected_user"]["full_name"], "Persona sin cuenta")
        self.assertEqual(snapshot["novadesk_asset"]["responsible_identity"]["full_name"], "Responsable")
        self.assertEqual(snapshot["device"]["glpi_id"], "537")
        self.assertEqual(snapshot["requester_identity"]["employee_number"], "002")
        self.assertEqual(Asset.objects.values().get(pk=self.asset.pk), before)
        self.assertEqual(User.objects.count(), 2)

    def test_missing_review_selection_is_not_guessed(self):
        for selection in ("", "{}", self.selection(device=None), self.selection(device=-1), self.selection(device=5)):
            self.assertIsNone(self.resolve(selection))

    def test_multiple_devices_need_explicit_index(self):
        self.context["devices"].append(deepcopy(self.context["devices"][0]))
        self.context["devices"][1]["data"]["name"] = "pc-second"
        self.assertIsNone(self.resolve(self.selection(device=None)))
        self.assertEqual(self.resolve(self.selection(device=1))["device"]["name"], "pc-second")

    def test_unsigned_foreign_and_changed_context_rejected(self):
        self.assertIsNone(self.resolve(self.selection(token="forged")))
        token = review_token(self.context, self.owner, {"ip": "192.0.2.1"})
        self.assertIsNone(self.resolve(self.selection(token=token)))
        changed = deepcopy(self.context)
        changed["devices"][0]["data"]["serial"] = "OTHER"
        self.assertIsNone(self.resolve(context=changed))

    def test_expired_proof_rejected_without_source_queries(self):
        selection = self.selection()
        with patch("apps.tickets.context_snapshot.signing.loads", side_effect=SignatureExpired()), patch("apps.tickets.context_snapshot.resolve_technical_context") as resolver:
            self.assertIsNone(build_snapshot(self.user, selection))
        resolver.assert_not_called()

    def test_secrets_and_extra_payload_not_saved(self):
        self.context["headers"] = {"Authorization": "private-secret"}
        self.context["devices"][0]["data"]["password"] = "private-secret"
        self.context["devices"][0]["data"]["hostname"] = "https://user:password@host"
        self.context["warnings"] = ["token=private-secret"]
        serialized = json.dumps(self.resolve())
        for forbidden in ("private-secret", "Authorization", "https://user"):
            self.assertNotIn(forbidden, serialized)

    def test_client_cannot_save_context(self):
        self.user.role = "CLIENT"
        with patch("apps.tickets.context_snapshot.resolve_technical_context") as resolver:
            self.assertIsNone(build_snapshot(self.user, self.selection()))
        resolver.assert_not_called()

    def create_ticket(self, selection=""):
        self.client.force_login(self.user)
        with patch("apps.tickets.context_snapshot.resolve_technical_context", return_value=self.context), patch("apps.tickets.context_snapshot.resolve_automatic_context", return_value={"devices": []}):
            response = self.client.post(reverse("tickets:ticket_create"), {
                "title": "Problema", "description": "Descripción manual", "priority": "LOW", "category": "HARDWARE",
                "request_flow": "OPERATIONAL", "technical_context_selection": selection,
            })
        self.assertEqual(response.status_code, 302)
        return Ticket.objects.latest("created_at")

    def test_real_creation_stores_snapshot_without_changing_requester_description_asset(self):
        ticket = self.create_ticket(self.selection())
        self.assertEqual(ticket.requester_id, self.user.pk)
        self.assertEqual(ticket.description, "Descripción manual")
        self.assertIsNone(ticket.asset_id)
        self.assertEqual(ticket.technical_context_snapshot["device"]["name"], "pc-test")
        saved = deepcopy(ticket.technical_context_snapshot)
        self.context["devices"][0]["data"]["name"] = "changed"
        ticket.refresh_from_db()
        self.assertEqual(ticket.technical_context_snapshot, saved)
        form = TicketForm({"title": "Editado", "description": "Otro problema", "priority": "LOW", "category": "HARDWARE"}, instance=ticket, user=self.user)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        ticket.refresh_from_db()
        self.assertEqual(ticket.technical_context_snapshot, saved)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("tickets:ticket_detail", args=[ticket.pk])).status_code, 403)

    def test_no_context_client_and_technician_create_normally(self):
        for role in ("CLIENT", "TECHNICIAN"):
            self.user.role = role
            self.user.save(update_fields=["role"])
            ticket = self.create_ticket()
            self.assertIsNone(ticket.technical_context_snapshot)
            self.assertEqual(ticket.requester_id, self.user.pk)

    def test_glpi_failure_does_not_block_creation(self):
        selection = self.selection()
        self.client.force_login(self.user)
        with patch("apps.tickets.context_snapshot.resolve_technical_context", side_effect=RuntimeError("secret")):
            response = self.client.post(reverse("tickets:ticket_create"), {
                "title": "Problema", "description": "Manual", "priority": "LOW", "category": "HARDWARE",
                "request_flow": "OPERATIONAL", "technical_context_selection": selection})
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(Ticket.objects.get().technical_context_snapshot)
        self.assertTrue(any("sin esa instantánea" in str(message) for message in response.wsgi_request._messages))

    def test_old_ticket_null_and_optional_detail(self):
        ticket = self.create_ticket()
        self.assertIsNone(ticket.technical_context_snapshot)
        self.assertNotIn("NOVADESK_TECHNICAL_CONTEXT", ticket.description)
        html = render_to_string("tickets/context_snapshot_detail.html", {"snapshot": self.resolve()})
        self.assertIn("pc-test", html)
        self.assertIn("Persona sin cuenta", html)

    def test_new_snapshot_separates_institutional_unit_operational_team_and_branch(self):
        data = self.context["person"]["candidates"][0]["data"]
        data.update(organizational_unit="Dependencia institucional", department="Equipo de soporte", branch="Sede explícita")
        snapshot = self.resolve()
        self.assertEqual(snapshot["metadata"]["resolver_version"], "2")
        self.assertEqual(snapshot["requester_identity"]["organizational_unit"], "Dependencia institucional")
        self.assertEqual(snapshot["requester_identity"]["department"], "Equipo de soporte")
        html = render_to_string("tickets/context_snapshot_detail.html", {"snapshot": snapshot})
        self.assertIn("Dependencia institucional: Dependencia institucional", html)
        self.assertIn("Equipo de atención: Equipo de soporte", html)

    def test_historical_snapshot_is_presented_without_reinterpreting_or_modifying_department(self):
        snapshot = {"metadata": {"resolver_version": "1"}, "requester_identity": {"department": "Dato histórico"}}
        before = deepcopy(snapshot)
        html = render_to_string("tickets/context_snapshot_detail.html", {"snapshot": snapshot})
        self.assertIn("Referencia histórica de dependencia: Dato histórico", html)
        self.assertNotIn("Equipo de atención: Dato histórico", html)
        self.assertEqual(snapshot, before)
