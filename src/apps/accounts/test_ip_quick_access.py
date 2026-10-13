from types import SimpleNamespace

from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.urls import reverse


class IPQuickAccessTests(SimpleTestCase):
    def render_card(self, user):
        return render_to_string("accounts/ip_quick_access.html", {"request": SimpleNamespace(user=user)})

    def test_card_uses_shared_structure_for_allowed_roles(self):
        for role, superuser in (("ADMIN", False), ("TECHNICIAN", False), ("CLIENT", True)):
            with self.subTest(role=role, superuser=superuser):
                html = self.render_card(SimpleNamespace(is_authenticated=True, is_superuser=superuser, role=role))
                self.assertIn('class="staff-quick-access-card"', html)
                self.assertIn('class="staff-quick-access-icon"', html)
                self.assertIn('class="staff-quick-access-link"', html)
                self.assertIn("Consulta Técnica por IP", html)
                self.assertIn(f'href="{reverse("integrations:ip_lookup")}"', html)

    def test_card_hidden_for_other_roles_and_anonymous(self):
        for role in ("CLIENT", "SUPERVISOR", "AUDITOR"):
            self.assertNotIn("Consulta Técnica por IP", self.render_card(SimpleNamespace(is_authenticated=True, is_superuser=False, role=role)))
        self.assertNotIn("Consulta Técnica por IP", self.render_card(AnonymousUser()))
