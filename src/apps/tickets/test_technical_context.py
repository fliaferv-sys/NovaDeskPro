from unittest.mock import patch
from types import SimpleNamespace

from django.test import TestCase
from django.template.loader import render_to_string
from django.urls import reverse
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import User
from apps.tickets.forms import TicketForm
from apps.inventory.models import Asset


class TicketTechnicalContextTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="context-tech", role="TECHNICIAN")
        self.url = reverse("tickets:technical_context")

    def test_role_permissions_and_invalid_input(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.force_login(self.user)
        with patch("apps.tickets.technical_context_views.resolve_technical_context") as resolver:
            self.assertEqual(self.client.get(self.url, {"ip": "not-ip"}).status_code, 400)
            self.assertEqual(self.client.get(self.url, {"hostname": "http://user:pass@host"}).status_code, 400)
            resolver.assert_not_called()
        self.user.role = "CLIENT"
        self.user.save(update_fields=["role"])
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_requester_is_authenticated_user_no_writes(self):
        self.client.force_login(self.user)
        with patch("apps.tickets.technical_context_views.resolve_technical_context", return_value={"devices": []}) as resolver, CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.url, {"requester": "other-person", "ip": "192.0.2.1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resolver.call_args.kwargs["requester"].pk, self.user.pk)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))

    def test_empty_query_does_not_resolve_or_disclose_context(self):
        self.client.force_login(self.user)
        with patch("apps.tickets.technical_context_views.resolve_technical_context") as resolver:
            self.assertEqual(self.client.get(self.url).status_code, 400)
        resolver.assert_not_called()

    def test_panel_only_create_staff_and_existing_form_rules_kept(self):
        request = SimpleNamespace(user=self.user)
        self.assertIn("data-technical-context", render_to_string("tickets/technical_context.html", {"request": request}))
        self.assertNotIn("data-technical-context", render_to_string("tickets/technical_context.html", {"request": request, "editing": True}))
        self.user.role = "CLIENT"
        self.assertNotIn("data-technical-context", render_to_string("tickets/technical_context.html", {"request": request}))
        other = User.objects.create_user(username="other-context-owner", email="other-context@example.test")
        Asset.objects.create(internal_code="NO-AUTO", assigned_user=other)
        form = TicketForm(user=self.user)
        self.assertFalse(form.fields["asset"].queryset.exists())
        self.assertEqual(set(form.fields), {"asset", "printing_device", "title", "description", "priority", "category"})
