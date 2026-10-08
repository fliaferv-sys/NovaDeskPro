import json
from unittest.mock import patch

from django.contrib import admin
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.tests import TEST_STORAGES
from apps.directory import identity_services as services
from apps.directory.identity_policies import authorize_identity_context, issue_identity_reference


@override_settings(STORAGES=TEST_STORAGES)
class SharedIdentityAdminTests(TestCase):
    def setUp(self):
        self.actor = User.objects.create_superuser(username="phase1-admin", email="phase1-admin@example.test", password="test-password")
        self.client.force_login(self.actor)
        self.model_admin = admin.site._registry[User]
        self.request = RequestFactory().post("/admin/accounts/user/add/")
        self.request.user = self.actor
        self.row = {"IdPersonal": 701, "Mail": "newperson@petropar.gov.py", "LegajoNro": "701", "NombresApellidos": "Persona Institucional", "Vinculo": "Permanente"}
        self.lookup = patch.object(services, "search_directory_employees", side_effect=lambda *args, **kwargs: [self.row] if self.row else [])
        self.lookup.start()
        self.addCleanup(self.lookup.stop)
        self.ad = patch.object(services, "search_ad_users", return_value=[])
        self.ad.start()
        self.addCleanup(self.ad.stop)
        mapping = patch.object(services, "_load_tercerizados", return_value={})
        mapping.start()
        self.addCleanup(mapping.stop)

    def reference(self, context="accounts.add", object_id=""):
        identity = services.search_common_identities("newperson@petropar.gov.py", "email")["exact_identity"]
        policy = authorize_identity_context(self.request, context, object_id)
        return issue_identity_reference(self.request, policy, identity)

    def creation_data(self, reference=""):
        return {"email": "newperson@petropar.gov.py", "username": "newperson", "password1": "T3st-random-password-916!", "password2": "T3st-random-password-916!", "first_name": "Manual", "last_name": "Apellido", "role": "CLIENT", "employment_type": "PERMANENT", "approval_status": "APPROVED", "is_active": "on", "institutional_identity_ref": reference}

    def test_add_form_uses_generic_config_and_backend_reference_validation(self):
        response = self.client.get(reverse("admin:accounts_user_add"))
        self.assertContains(response, 'data-context="accounts.add"')
        self.assertContains(response, "shared/js/institutional_identity.js")
        self.assertNotContains(response, "accounts/js/institutional_autofill.js")
        form_class = self.model_admin.get_form(self.request)
        form = form_class(data=self.creation_data(self.reference()))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["first_name"], "Manual")
        self.assertEqual(form.cleaned_data["role"], "CLIENT")
        self.assertEqual(form.selected_institutional_identity["rrhh_id"], 701)

    def test_admin_post_creates_user_and_does_not_apply_source_to_manual_fields(self):
        response = self.client.post(reverse("admin:accounts_user_add"), self.creation_data(self.reference()))
        self.assertEqual(response.status_code, 302)
        created = User.objects.get(username="newperson")
        self.assertEqual(created.first_name, "Manual")
        self.assertTrue(created.check_password("T3st-random-password-916!"))
        self.assertFalse(created.is_staff)
        self.assertFalse(created.is_superuser)

    def test_tampered_or_changed_source_reference_blocks_save(self):
        form_class = self.model_admin.get_form(self.request)
        form = form_class(data=self.creation_data("invalid-reference"))
        self.assertFalse(form.is_valid())
        self.assertIn("__all__", form.errors)
        reference = self.reference()
        self.row["LegajoNro"] = "changed"
        form = form_class(data=self.creation_data(reference))
        self.assertFalse(form.is_valid())
        self.assertFalse(User.objects.filter(username="newperson").exists())

    def test_manual_creation_without_selection_remains_available(self):
        form_class = self.model_admin.get_form(self.request)
        with patch.object(services, "resolve_common_identity") as resolve:
            form = form_class(data=self.creation_data())
            self.assertTrue(form.is_valid(), form.errors)
            resolve.assert_not_called()

    def test_edit_open_does_not_query_sources_or_change_data(self):
        existing = User.objects.create_user(username="existing", email="existing@petropar.gov.py", first_name="Original")
        with patch.object(services, "search_directory_employees") as rrhh, patch.object(services, "search_ad_users") as ad:
            response = self.client.get(reverse("admin:accounts_user_change", args=[existing.pk]))
        self.assertContains(response, 'data-mode="change"')
        self.assertContains(response, 'data-context="accounts.change"')
        rrhh.assert_not_called()
        ad.assert_not_called()
        existing.refresh_from_db()
        self.assertEqual(existing.first_name, "Original")

    def test_explicit_selection_in_edit_is_scoped_and_revalidated_on_save(self):
        existing = User.objects.create_user(username="existing", email="existing@petropar.gov.py", first_name="Original")
        creation_reference = self.reference()
        reference = self.reference("accounts.change", str(existing.pk))
        request = RequestFactory().post("/admin/accounts/user/change/")
        request.user = self.actor
        form_class = self.model_admin.get_form(request, existing)
        data = {"email": "newperson@petropar.gov.py", "username": "newperson", "first_name": "Nueva selección", "role": "CLIENT", "employment_type": "PERMANENT", "approval_status": "APPROVED", "is_active": "on", "institutional_identity_ref": reference}
        form = form_class(data=data, instance=existing)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        existing.refresh_from_db()
        self.assertEqual(existing.first_name, "Nueva selección")
        # A reference from creation cannot be reused to edit any account.
        form = form_class(data={**data, "institutional_identity_ref": creation_reference}, instance=existing)
        self.assertFalse(form.is_valid())

    def test_manual_edit_without_selection_does_not_resolve_identity(self):
        existing = User.objects.create_user(username="existing", email="existing@petropar.gov.py", first_name="Original")
        form_class = self.model_admin.get_form(self.request, existing)
        data = {"email": existing.email, "username": existing.username, "first_name": "Manual", "role": "CLIENT", "employment_type": "PERMANENT", "approval_status": "APPROVED", "is_active": "on"}
        with patch("apps.directory.identity_policies.resolve_common_identity") as resolve:
            form = form_class(data=data, instance=existing)
            self.assertTrue(form.is_valid(), form.errors)
            resolve.assert_not_called()
