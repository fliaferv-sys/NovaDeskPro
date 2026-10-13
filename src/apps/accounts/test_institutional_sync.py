from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase, Client, override_settings
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

    def test_get_never_syncs_post_authorized_does(self):
        self.client.force_login(self.actor)
        url = reverse("sync_user_institutional_data", args=[self.user.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.user.refresh_from_db(); self.assertIsNone(self.user.id_personal)
        response = self.client.post(url, {"id_personal": 999, "employee_number": "forged", "role": "ADMIN"})
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.id_personal, 33)
        self.assertEqual(self.user.employee_number, "2100")
        self.assertEqual(self.user.role, "CLIENT")

    def test_roles_and_csrf(self):
        url = reverse("sync_user_institutional_data", args=[self.user.pk])
        self.assertEqual(self.client.post(url).status_code, 302)
        for role in ("CLIENT", "TECHNICIAN", "AUDITOR"):
            self.actor.role = role; self.actor.save(update_fields=["role"])
            self.client.force_login(self.actor)
            self.assertEqual(self.client.post(url).status_code, 403)
        self.actor.role = "SUPERVISOR"; self.actor.save(update_fields=["role"])
        self.client.force_login(self.actor)
        self.assertEqual(self.client.post(url).status_code, 302)
        secured = Client(enforce_csrf_checks=True); secured.force_login(self.actor)
        self.assertEqual(secured.post(url).status_code, 403)

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
        for role, visible in (("ADMIN", True), ("SUPERVISOR", True), ("AUDITOR", False)):
            self.actor.role = role; self.actor.save(update_fields=["role"])
            self.client.force_login(self.actor)
            with patch("apps.accounts.user_presentation.get_institutional_directory", return_value=[]), patch("apps.accounts.institutional_sync.resolve_sync_identity") as sync:
                response = self.client.get(reverse("user_list"))
            self.assertEqual(response.status_code, 200)
            self.assertEqual("Sincronizar datos" in response.content.decode(), visible)
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

    def test_response_does_not_disclose_matching_values(self):
        self.client.force_login(self.actor)
        self.user.phone = "0999999999"; self.user.save(update_fields=["phone"])
        response = self.client.post(reverse("sync_user_institutional_data", args=[self.user.pk]))
        content = " ".join(str(message) for message in response.wsgi_request._messages)
        self.assertIn("Requiere revisión", content)
        self.assertNotIn("0999999999", content)
