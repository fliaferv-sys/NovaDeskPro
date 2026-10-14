from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import NoReverseMatch
from django.contrib.admin.sites import AdminSite
from django.db import transaction
from types import SimpleNamespace
from apps.accounts.admin import CustomUserAdmin
from apps.accounts.institutional_sync import try_sync_user_institutional_data
from django.contrib.auth.models import Group, Permission
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.institutional_sync import build_user_institutional_sync_plan, apply_user_institutional_sync
from apps.activity.models import ActivityLog
from apps.directory.identity_services import get_user_photo_url


@override_settings(DIRECTORY_AD_DOMAIN="petropar.gov.py")
class InstitutionalSyncTests(TestCase):
    def setUp(self):
        self.actor = User.objects.create_user(username="sync-admin", email="sync-admin@example.test", role="ADMIN")
        self.user = User.objects.create_user(username="robgonzalez", email="robgonzalez@petropar.gov.py",
            first_name="Roberto Nicolas", last_name="Gonzalez Paiva")
        self.row = {"IdPersonal": 33, "LegajoNro": "2100", "NombresApellidos": "ROBERTO NICOLAS GONZALEZ PAIVA",
            "Mail": self.user.email, "Telefono": "0975 254935", "Cargo": "Cargo RRHH", "Estado": "Activo"}
        self.rows = [self.row]
        self.ad = [{"name": self.row["NombresApellidos"], "username": self.user.username, "email": self.user.email, "is_active": True}]
        self.rrhh_patch = patch("apps.accounts.institutional_sync.search_directory_employees", side_effect=self.search)
        self.ad_patch = patch("apps.accounts.institutional_sync.search_ad_users", side_effect=lambda *args, **kwargs: deepcopy(self.ad))
        self.rrhh_patch.start(); self.ad_patch.start()
        self.addCleanup(self.rrhh_patch.stop); self.addCleanup(self.ad_patch.stop)

    def search(self, value, **kwargs):
        column = {"rrhh_id": "IdPersonal", "employee_number": "LegajoNro", "email": "Mail", "name": "NombresApellidos"}[kwargs["search_field"]]
        return [deepcopy(row) for row in self.rows if str(row.get(column) or "").strip().casefold() == str(value).strip().casefold()]

    def plan(self):
        return build_user_institutional_sync_plan(self.user)

    def apply(self, plan=None):
        return apply_user_institutional_sync(self.user, plan, actor=self.actor)

    def test_exact_id_personal_completes_empty_fields(self):
        self.user.id_personal = 33; self.user.save(update_fields=["id_personal"])
        plan = self.apply()
        self.user.refresh_from_db()
        self.assertTrue(plan["can_apply"])
        self.assertEqual(self.user.employee_number, "2100")
        self.assertEqual(self.user.phone, "0975 254935")
        self.assertEqual(self.user.position, "Cargo RRHH")

    def test_exact_employee_number_fills_id_personal(self):
        self.user.employee_number = "2100"; self.user.save(update_fields=["employee_number"])
        self.apply(); self.user.refresh_from_db()
        self.assertEqual(self.user.id_personal, 33)

    def test_roberto_ad_plus_name_phone_without_rrhh_email(self):
        self.row["Mail"] = ""
        self.user.phone = "0975254935"; self.user.save(update_fields=["phone"])
        result = self.apply(); self.user.refresh_from_db()
        self.assertTrue(result["can_apply"])
        self.assertIn("rrhh_nombre_telefono", result["evidence"])
        self.assertEqual(self.user.id_personal, 33)
        self.assertEqual(self.user.employee_number, "2100")
        self.assertEqual(self.user.phone, "0975254935")

    def test_name_only_and_phone_only_never_sync(self):
        self.user.email = "unknown@example.test"
        for phone in (None, "0975 254935"):
            self.user.phone = phone
            self.assertFalse(self.plan()["can_apply"])

    def test_exact_email_ambiguous_rrhh_blocks(self):
        self.rows.append(dict(self.row, IdPersonal=34, LegajoNro="2101"))
        self.assertFalse(self.plan()["can_apply"])

    def test_email_phone_conflict_blocks(self):
        self.user.phone = "0999999999"
        self.assertFalse(self.plan()["can_apply"])

    def test_identifiers_pointing_to_different_people_block(self):
        self.rows.append(dict(self.row, IdPersonal=34, LegajoNro="2101", Mail="other@petropar.gov.py"))
        self.user.id_personal, self.user.employee_number = 33, "2101"
        self.assertFalse(self.plan()["can_apply"])

    def test_existing_position_is_preserved_other_empty_fields_filled(self):
        self.user.position = "Cargo local"; self.user.save(update_fields=["position"])
        plan = self.apply(); self.user.refresh_from_db()
        self.assertEqual(self.user.position, "Cargo local")
        self.assertEqual(self.user.employee_number, "2100")
        self.assertIn("position:valor_local_conservado", plan["conflicts"])

    def test_only_allowed_fields_change_no_photo_role_password_flags_or_permissions(self):
        group = Group.objects.create(name="Existing access")
        permission = Permission.objects.get(codename="view_user", content_type__app_label="accounts")
        self.user.groups.add(group); self.user.user_permissions.add(permission)
        self.user.profile_image = "users/profiles/local.jpg"; self.user.save(update_fields=["profile_image"])
        before = User.objects.values().get(pk=self.user.pk)
        self.apply()
        after = User.objects.values().get(pk=self.user.pk)
        changed = {key for key in before if before[key] != after[key]}
        self.assertEqual(changed, {"id_personal", "employee_number", "phone", "position"})
        self.assertEqual(list(self.user.groups.values_list("pk", flat=True)), [group.pk])
        self.assertEqual(list(self.user.user_permissions.values_list("pk", flat=True)), [permission.pk])
        self.assertEqual(User.objects.count(), 2)

    def test_unrelated_user_not_changed(self):
        self.user.email = "nobody@petropar.gov.py"; self.user.username = "nobody"
        self.user.save(update_fields=["email", "username"])
        self.ad = []
        before = User.objects.values().get(pk=self.user.pk)
        self.apply()
        self.assertEqual(User.objects.values().get(pk=self.user.pk), before)

    def test_manual_url_removed(self):
        with self.assertRaises(NoReverseMatch):
            reverse("sync_user_institutional_data", args=[self.user.pk])
        self.assertEqual(self.client.post(f"/usuarios/{self.user.pk}/sincronizar/").status_code, 404)

    def test_audit_records_actor_target_and_fields_without_values(self):
        self.apply()
        log = ActivityLog.objects.get()
        self.assertEqual(log.user_id, self.actor.pk)
        self.assertEqual(log.object_id, str(self.user.pk))
        self.assertIn("employee_number", log.description)
        self.assertNotIn("2100", log.description)
        self.assertNotIn("0975", log.description)
        self.assertIsNotNone(log.created_at)

    def test_rollback_if_audit_fails(self):
        before = User.objects.values().get(pk=self.user.pk)
        with patch("apps.accounts.institutional_sync.ActivityLog.objects.create", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaises(RuntimeError):
                self.apply()
        self.assertEqual(User.objects.values().get(pk=self.user.pk), before)
        self.assertFalse(ActivityLog.objects.exists())

    def test_photo_by_persisted_employee_number_without_copy(self):
        self.apply(); self.user.refresh_from_db()
        with TemporaryDirectory() as folder, override_settings(MEDIA_ROOT=folder, MEDIA_URL="/media/"):
            photos = Path(folder) / "funcionarios"; photos.mkdir(); (photos / "2100F.jpg").touch()
            self.assertEqual(get_user_photo_url(self.user), "/media/funcionarios/2100F.jpg")
        self.assertFalse(self.user.profile_image)

    def test_plan_is_read_only_and_apply_revalidates_ignores_stale_or_forged_changes(self):
        before = User.objects.values().get(pk=self.user.pk)
        stale = self.plan()
        self.assertEqual(User.objects.values().get(pk=self.user.pk), before)
        stale["proposed_changes"]["role"] = "ADMIN"
        self.rows = []
        self.apply(stale)
        self.assertEqual(User.objects.values().get(pk=self.user.pk), before)

    def test_unique_identifier_already_used_blocks(self):
        self.actor.employee_number = "2100"; self.actor.save(update_fields=["employee_number"])
        self.assertFalse(self.plan()["can_apply"])

    def test_sources_unavailable_no_write(self):
        with patch("apps.accounts.institutional_sync.search_directory_employees", side_effect=RuntimeError("private-secret")):
            plan = self.plan()
        self.assertFalse(plan["can_apply"])
        self.assertNotIn("private-secret", str(plan))

    def test_repeated_sync_no_changes_or_duplicate_audit(self):
        self.apply()
        result = self.apply()
        self.assertTrue(result["can_apply"])
        self.assertFalse(result["proposed_changes"])
        self.assertEqual(ActivityLog.objects.count(), 1)

    def test_ad_ambiguous_or_inactive_cannot_bridge(self):
        self.row["Mail"] = ""; self.user.phone = "0975254935"
        self.ad.append(dict(self.ad[0]))
        self.assertFalse(self.plan()["can_apply"])
        self.ad = [dict(self.ad[0], is_active=False)]
        self.assertFalse(self.plan()["can_apply"])

    def test_bridge_requires_name_and_phone_uniqueness(self):
        self.row["Mail"] = ""; self.user.phone = "0975254935"
        self.rows.append(dict(self.row, IdPersonal=34, LegajoNro="2101"))
        self.assertFalse(self.plan()["can_apply"])

    def test_overlong_fields_not_truncated_or_saved(self):
        self.row["Cargo"] = "X" * 101
        self.assertFalse(self.plan()["can_apply"])

    @override_settings(STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                                 "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
    def test_list_action_visibility_and_get_does_not_sync(self):
        before = User.objects.values().get(pk=self.user.pk)
        for role in ("ADMIN", "SUPERVISOR", "AUDITOR"):
            self.actor.role = role; self.actor.save(update_fields=["role"])
            self.client.force_login(self.actor)
            with patch("apps.accounts.user_presentation.get_institutional_directory", return_value=[]), patch("apps.accounts.institutional_sync.resolve_sync_identity") as sync:
                response = self.client.get(reverse("user_list"))
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("Sincronizar datos", response.content.decode())
            sync.assert_not_called()
        self.assertEqual(User.objects.values().get(pk=self.user.pk), before)

    def test_roberto_name_accents_and_phone_format_normalize_without_approximation(self):
        self.row["Mail"] = ""
        self.row["NombresApellidos"] = "ROBERTO NICOLAS GONZALEZ PAIVA"
        self.user.phone = "0975-254935"
        self.ad[0]["name"] = "Roberto Nicolás González Paiva"
        # Simulate the bounded RRHH name search returning the accent variant.
        with patch("apps.accounts.institutional_sync.search_directory_employees", side_effect=lambda *args, **kwargs:
                   [self.row] if kwargs["search_field"] == "name" else []):
            plan = self.plan()
        self.assertTrue(plan["can_apply"])

    @override_settings(AUTHENTICATION_BACKENDS=["apps.accounts.backends.ApprovedUserModelBackend"])
    def login(self):
        self.user.set_password("login-test-password")
        self.user.save(update_fields=["password"])
        response = self.client.post(reverse("login"), {"username": self.user.email, "password": "login-test-password"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session["_auth_user_id"], str(self.user.pk))

    def test_successful_login_syncs_roberto_and_audit_actor_is_self(self):
        self.row["Mail"] = ""
        self.user.phone = "0975254935"; self.user.save(update_fields=["phone"])
        self.login()
        self.user.refresh_from_db()
        self.assertEqual(self.user.employee_number, "2100")
        self.assertEqual(self.user.id_personal, 33)
        self.assertEqual(ActivityLog.objects.get(action=ActivityLog.ACTION_UPDATE).user_id, self.user.pk)
        with patch("apps.accounts.institutional_sync.apply_user_institutional_sync") as apply:
            self.login()
        apply.assert_not_called()
        self.assertEqual(ActivityLog.objects.filter(action=ActivityLog.ACTION_UPDATE).count(), 1)

    def test_login_source_failure_does_not_block_or_leak(self):
        with patch("apps.accounts.institutional_sync.search_directory_employees", side_effect=RuntimeError("private-secret")), self.assertLogs("apps.accounts.institutional_sync", level="WARNING") as logs:
            self.login()
        self.assertNotIn("private-secret", str(logs.output))
        self.user.refresh_from_db(); self.assertIsNone(self.user.id_personal)

    def test_login_ambiguity_and_conflicts_do_not_block(self):
        self.rows.append(dict(self.row, IdPersonal=34))
        self.login()
        self.user.refresh_from_db(); self.assertIsNone(self.user.id_personal)
        self.rows = [self.row]
        self.user.phone = "0999999999"; self.user.save(update_fields=["phone"])
        self.login()
        self.user.refresh_from_db(); self.assertEqual(self.user.phone, "0999999999")
        self.assertFalse(ActivityLog.objects.filter(action=ActivityLog.ACTION_UPDATE).exists())

    def save_admin(self, change=True):
        model_admin = CustomUserAdmin(User, AdminSite())
        request = SimpleNamespace(user=self.actor)
        form = SimpleNamespace(instance=self.user, save_m2m=lambda: None)
        model_admin.save_model(request, self.user, form, change)
        model_admin.save_related(request, form, [], change)

    def test_admin_save_then_sync_preserves_manual_values_and_actor(self):
        self.user.position = "Cargo ingresado por administrador"
        self.save_admin()
        self.user.refresh_from_db()
        self.assertEqual(self.user.position, "Cargo ingresado por administrador")
        self.assertEqual(self.user.employee_number, "2100")
        self.assertEqual(ActivityLog.objects.get().user_id, self.actor.pk)

    def test_admin_creation_syncs_after_normal_save(self):
        self.user.delete()
        self.user = User(username="robgonzalez", email="robgonzalez@petropar.gov.py", first_name="Roberto Nicolas", last_name="Gonzalez Paiva")
        self.save_admin(change=False)
        self.user.refresh_from_db()
        self.assertEqual(self.user.id_personal, 33)

    def test_admin_source_outage_preserves_normal_save(self):
        self.user.position = "Guardado normal"
        with patch("apps.accounts.institutional_sync.search_directory_employees", side_effect=RuntimeError("private-secret")), self.assertLogs("apps.accounts.institutional_sync", level="WARNING"):
            self.save_admin()
        self.user.refresh_from_db()
        self.assertEqual(self.user.position, "Guardado normal")
        self.assertIsNone(self.user.id_personal)

    def test_admin_audit_error_rolls_back_sync_only_inside_outer_transaction(self):
        self.user.position = "Cambio administrativo"
        with transaction.atomic(), patch("apps.accounts.institutional_sync.ActivityLog.objects.create", side_effect=RuntimeError("private-secret")), self.assertLogs("apps.accounts.institutional_sync", level="WARNING") as logs:
            self.save_admin()
            self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
        self.user.refresh_from_db()
        self.assertEqual(self.user.position, "Cambio administrativo")
        self.assertIsNone(self.user.id_personal)
        self.assertIsNone(self.user.employee_number)
        self.assertFalse(ActivityLog.objects.exists())
        self.assertNotIn("private-secret", str(logs.output))

    def test_login_audit_error_does_not_block_and_reverts_sync(self):
        with patch("apps.accounts.institutional_sync.record_sync_activity", side_effect=RuntimeError("private-secret")), self.assertLogs("apps.accounts.institutional_sync", level="WARNING"):
            self.login()
        self.user.refresh_from_db()
        self.assertIsNone(self.user.employee_number)
        self.assertFalse(ActivityLog.objects.filter(action=ActivityLog.ACTION_UPDATE).exists())

    def test_protected_fields_unchanged_by_automatic_sync(self):
        self.user.profile_image = "users/profiles/local.jpg"
        self.user.save(update_fields=["profile_image"])
        before = User.objects.values().get(pk=self.user.pk)
        try_sync_user_institutional_data(self.user, actor=self.user)
        after = User.objects.values().get(pk=self.user.pk)
        self.assertEqual({key for key in before if before[key] != after[key]}, {"id_personal", "employee_number", "phone", "position"})

    def test_non_admin_cannot_sync_someone_else(self):
        self.actor.role = "CLIENT"
        with self.assertRaises(Exception):
            apply_user_institutional_sync(self.user, actor=self.actor)

    def make_assignment(self, **identifiers):
        from apps.institution.models import InstitutionalIdentityAssignment, OrganizationalUnit
        unit = OrganizationalUnit.objects.create(code="SYNC-UNIT", name="Dependencia", unit_type="UNIT")
        InstitutionalIdentityAssignment.objects.create(organizational_unit=unit, **(identifiers or {"id_personal": 33}))
        return unit

    def test_confirmed_person_syncs_exact_explicit_unit_but_never_branch_or_department(self):
        from apps.accounts.models import Branch
        from apps.core.models import Department
        Branch.objects.create(code="LOCATION", name="Ubicación RRHH")
        Department.objects.create(code="LOCATION", name="Ubicación RRHH")
        self.row["Ubicacion"] = "Ubicación RRHH"
        unit = self.make_assignment()
        self.apply()
        self.user.refresh_from_db()
        self.assertEqual(self.user.organizational_unit, unit)
        self.assertIsNone(self.user.branch_id)
        self.assertIsNone(self.user.department_id)
        self.assertIn("organizational_unit_id", ActivityLog.objects.get().description)
        self.assertFalse(self.apply()["proposed_changes"])
        self.assertEqual(ActivityLog.objects.count(), 1)

    def test_complete_personal_fields_can_sync_new_unit_during_login_hook(self):
        self.apply()
        unit = self.make_assignment()
        try_sync_user_institutional_data(self.user, actor=self.user)
        self.assertEqual(self.user.organizational_unit_id, unit.pk)
        self.assertEqual(ActivityLog.objects.count(), 2)

    def test_existing_local_unit_is_preserved(self):
        from apps.institution.models import OrganizationalUnit
        self.make_assignment()
        other = OrganizationalUnit.objects.create(code="LOCAL-UNIT", name="Local", unit_type="UNIT")
        self.user.organizational_unit = other; self.user.save(update_fields=["organizational_unit"])
        result = self.apply()
        self.user.refresh_from_db()
        self.assertEqual(self.user.organizational_unit, other)
        self.assertIn("organizational_unit:valor_local_conservado", result["conflicts"])

    def test_contradictory_and_inactive_mapping_do_not_assign_unit(self):
        from apps.institution.models import InstitutionalIdentityAssignment, OrganizationalUnit
        self.make_assignment()
        other = OrganizationalUnit.objects.create(code="OTHER-UNIT", name="Otra", unit_type="UNIT")
        InstitutionalIdentityAssignment.objects.create(email=self.user.email, organizational_unit=other)
        self.apply(); self.user.refresh_from_db()
        self.assertIsNone(self.user.organizational_unit_id)
        self.assertEqual(self.user.employee_number, "2100")
        InstitutionalIdentityAssignment.objects.all().update(is_active=False)
        try_sync_user_institutional_data(self.user, actor=self.user)
        self.user.refresh_from_db(); self.assertIsNone(self.user.organizational_unit_id)

    def test_ad_failure_in_bridge_does_not_block_login_or_write(self):
        from apps.directory.ad_services import ActiveDirectoryError
        self.row["Mail"] = ""
        self.user.phone = self.row["Telefono"]; self.user.save(update_fields=["phone"])
        with patch("apps.accounts.institutional_sync.search_ad_users", side_effect=ActiveDirectoryError("unavailable")):
            self.login()
        self.user.refresh_from_db(); self.assertIsNone(self.user.id_personal)
        self.assertFalse(ActivityLog.objects.filter(action=ActivityLog.ACTION_UPDATE).exists())
