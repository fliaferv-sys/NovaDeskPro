import json
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth.models import Permission
from django.test import TestCase, RequestFactory, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.tests import TEST_STORAGES
from apps.directory.identity_policies import authorize_identity_context, issue_identity_reference
from apps.printing.models import PrintingDevice


@override_settings(STORAGES=TEST_STORAGES)
class PrintingResponsibleIdentityTests(TestCase):
    def setUp(self):
        self.actor = User.objects.create_superuser(username="printing-identity-admin", password="test-password")
        self.person = User.objects.create_user(username="local-person", email="person@example.test", first_name="Persona", last_name="Local")
        self.client.force_login(self.actor)
        self.request = RequestFactory().post("/admin/printing/printingdevice/add/")
        self.request.user = self.actor
        self.model_admin = admin.site._registry[PrintingDevice]
        self.identity = {"source": "LOCAL", "local_user_id": str(self.person.pk), "full_name": "Persona Local", "email": self.person.email, "username": self.person.username, "_locator": {"source": "LOCAL", "id": str(self.person.pk)}}

    def reference(self, identity=None, obj=None):
        policy = authorize_identity_context(self.request, "printing.change" if obj else "printing.add", str(obj.pk) if obj else "")
        return issue_identity_reference(self.request, policy, identity or self.identity)

    def data(self, **changes):
        data = {"serial_number": "RESP-1", "brand": "Lexmark", "model": "MX622", "device_type": "PRINTER", "technology": "LASER", "color_mode": "MONOCHROME", "ownership_type": "OWNED", "network_port": "9100", "is_active": "on", "supports_network": "on", "notes": "Responsable original del Excel", "responsible_user": ""}
        data.update(changes)
        return data

    def test_valid_explicit_selection_assigns_existing_local_user(self):
        count = User.objects.count()
        with patch("apps.directory.identity_policies.resolve_common_identity", return_value=self.identity):
            response = self.client.post(reverse("admin:printing_printingdevice_add"), self.data(responsible_user=str(self.person.pk), institutional_identity_ref=self.reference()))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PrintingDevice.objects.get().responsible_user, self.person)
        self.assertEqual(User.objects.count(), count)

    def test_edit_open_preserves_assignment_and_does_not_search(self):
        device = PrintingDevice.objects.create(is_outsourced=False, responsible_user=self.person, notes="Original")
        before = PrintingDevice.objects.values().get(pk=device.pk)
        with patch("apps.directory.views.search_common_identities") as search, patch("apps.directory.identity_policies.resolve_common_identity") as resolve:
            response = self.client.get(reverse("admin:printing_printingdevice_change", args=[device.pk]))
        self.assertContains(response, 'data-context="printing.change"')
        self.assertContains(response, 'data-explicit-only="true"')
        self.assertContains(response, "Persona Local")
        self.assertContains(response, "shared/js/institutional_identity.js")
        search.assert_not_called(); resolve.assert_not_called()
        self.assertEqual(PrintingDevice.objects.values().get(pk=device.pk), before)

    def test_responsible_can_be_kept_or_removed_without_identity_lookup(self):
        device = PrintingDevice.objects.create(is_outsourced=False, responsible_user=self.person)
        for value in (str(self.person.pk), ""):
            form_class = self.model_admin.get_form(self.request, device)
            with patch("apps.directory.identity_policies.resolve_common_identity") as resolve:
                form = form_class(data=self.data(responsible_user=value), instance=device)
                self.assertTrue(form.is_valid(), form.errors)
                form.save()
                resolve.assert_not_called()
            device.refresh_from_db()
            self.assertEqual(device.responsible_user_id, self.person.pk if value else None)

    def test_institutional_identity_without_local_user_cannot_be_assigned(self):
        identity = {**self.identity, "local_user_id": None, "source": "RRHH", "_locator": {"source": "RRHH", "id": "701"}}
        count = User.objects.count()
        with patch("apps.directory.identity_policies.resolve_common_identity", return_value=identity):
            form = self.model_admin.get_form(self.request)(data=self.data(responsible_user=str(self.person.pk), institutional_identity_ref=self.reference(identity)))
            self.assertFalse(form.is_valid())
            self.assertIn("responsible_user", form.errors)
        self.assertEqual(User.objects.count(), count)
        self.assertEqual(PrintingDevice.objects.count(), 0)

    def test_selection_cannot_assign_another_local_account(self):
        with patch("apps.directory.identity_policies.resolve_common_identity", return_value=self.identity):
            form = self.model_admin.get_form(self.request)(data=self.data(responsible_user=str(self.actor.pk), institutional_identity_ref=self.reference()))
            self.assertFalse(form.is_valid())
            self.assertIn("responsible_user", form.errors)

    def test_reference_cannot_be_reused_across_add_and_edit(self):
        device = PrintingDevice.objects.create(is_outsourced=False)
        with patch("apps.directory.identity_policies.resolve_common_identity", return_value=self.identity):
            form = self.model_admin.get_form(self.request, device)(data=self.data(responsible_user=str(self.person.pk), institutional_identity_ref=self.reference()), instance=device)
            self.assertFalse(form.is_valid())

    def test_selection_does_not_change_other_device_fields(self):
        from apps.accounts.models import Branch
        from apps.inventory.models import OrganizationalLocation
        branch = Branch.objects.create(code="RESP-BRANCH", name="Sede responsable")
        location = OrganizationalLocation.objects.create(branch=branch, code="RESP-LOC", name="Ubicacion existente")
        device = PrintingDevice.objects.create(is_outsourced=False, serial_number="RESP-1", brand="Lexmark", model="MX622", branch=branch, organizational_location=location, ip_address="192.0.2.3", notes="Responsable original del Excel", photocopier_id="RESP-ID")
        before = PrintingDevice.objects.values().get(pk=device.pk)
        data = self.data(branch=str(branch.pk), organizational_location=str(location.pk), photocopier_id=device.photocopier_id, responsible_user=str(self.person.pk), institutional_identity_ref=self.reference(obj=device))
        with patch("apps.directory.identity_policies.resolve_common_identity", return_value=self.identity):
            form = self.model_admin.get_form(self.request, device)(data=data, instance=device)
            self.assertTrue(form.is_valid(), form.errors); form.save()
        after = PrintingDevice.objects.values().get(pk=device.pk)
        for field in ("responsible_user_id", "updated_at"):
            before.pop(field); after.pop(field)
        self.assertEqual(after, before)

    def test_search_requires_printing_permission_and_is_never_automatic(self):
        limited = User.objects.create_user(username="printing-only", email="printing-only@example.test", is_staff=True)
        limited.user_permissions.add(Permission.objects.get(codename="add_printingdevice"))
        self.client.force_login(limited)
        result = {"identities": [self.identity], "exact_unique": True, "exact_identity": self.identity, "incomplete": False}
        with patch("apps.directory.views.search_common_identities", return_value=result):
            response = self.client.post(reverse("directory:identity_search_api"), data=json.dumps({"context": "printing.add", "q": "Persona", "field": "name"}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "candidates")
        self.assertEqual(set(response.json()["candidates"][0]), {"full_name", "email", "username", "source", "local_user_id", "reference"})
        self.assertFalse(response.json().get("values"))
        response = self.client.post(reverse("directory:identity_search_api"), data=json.dumps({"context": "accounts.add", "q": "Persona", "field": "name"}), content_type="application/json")
        self.assertEqual(response.status_code, 403)
        limited.user_permissions.clear()
        response = self.client.post(reverse("directory:identity_search_api"), data=json.dumps({"context": "printing.add", "q": "Persona", "field": "name"}), content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_resolve_without_local_user_returns_clear_message(self):
        identity = {**self.identity, "local_user_id": None}
        with patch("apps.directory.identity_policies.resolve_common_identity", return_value=identity):
            response = self.client.post(reverse("directory:identity_resolve_api"), data=json.dumps({"context": "printing.add", "reference": self.reference(identity)}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "unassignable")
        self.assertNotIn("values", response.json())

    def test_nonstaff_admin_and_api_permissions_remain_denied(self):
        self.client.force_login(self.person)
        response = self.client.get(reverse("admin:printing_printingdevice_add"))
        self.assertEqual(response.status_code, 302)
        response = self.client.post(reverse("directory:identity_search_api"), data=json.dumps({"context": "printing.add", "q": "Persona", "field": "name"}), content_type="application/json")
        self.assertEqual(response.status_code, 403)
