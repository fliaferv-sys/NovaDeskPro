from dataclasses import replace
from unittest.mock import patch
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.accounts.models import User
from apps.directory.identity_selection import institutional_selection, institutional_snapshot
from apps.directory.identity_policies import IdentityPolicy, selection_capabilities, validate_selection
from apps.directory import identity_services as services


class InstitutionalSelectionTests(TestCase):
    def identity(self, **changes):
        result = {"source": "RRHH", "full_name": "Persona Institucional", "email": "persona@petropar.gov.py", "username": "persona", "is_active": True, "rrhh_id": 701, "local_user_id": None, "_locator": {"source": "RRHH", "id": 701}}
        result.update(changes)
        return result

    def test_institutional_selection_does_not_require_user(self):
        policy = IdentityPolicy("future.module", selection_requirement="institutional")
        flags = selection_capabilities(policy, self.identity())
        self.assertTrue(flags["selectable"])
        self.assertFalse(flags["has_local_user"])
        for requirement in ("local_user", "both"):
            with self.assertRaises(ValidationError):
                validate_selection(replace(policy, selection_requirement=requirement), self.identity())

    def test_both_requirements_work_with_existing_user(self):
        user = User.objects.create_user(username="persona", email="persona@petropar.gov.py")
        flags = selection_capabilities(IdentityPolicy("future.module", selection_requirement="both"), self.identity(local_user_id=str(user.pk)))
        self.assertTrue(flags["selectable"])
        self.assertTrue(flags["has_local_user"])

    def test_invalid_email_inactive_or_nonperson_are_not_eligible(self):
        for changes in ({"email": ""}, {"email": "bad@other.test"}, {"is_active": False}, {"is_person": False}, {"is_shared": True}, {"username": "svc_print"}):
            with self.subTest(changes=changes):
                self.assertFalse(institutional_selection(self.identity(**changes))[0])

    def test_minimal_snapshot_prefers_institutional_source_over_local(self):
        identity = self.identity(_locator={"source": "LOCAL", "id": "local"}, _linked=[{"source": "ACTIVE_DIRECTORY", "username": "persona", "email": "persona@petropar.gov.py"}, {"source": "RRHH", "id": 701}])
        snapshot = institutional_snapshot(identity)
        self.assertEqual(snapshot["locator"], {"source": "RRHH", "id": 701})
        self.assertEqual(set(snapshot), {"locator", "source", "name", "email", "username"})

    def test_common_rrhh_source_retains_activity_and_no_local_user(self):
        normalized = services._normalize_rrhh_employee({"IdPersonal": 701, "Mail": "persona@petropar.gov.py", "NombresApellidos": "Persona Institucional", "Estado": "Activo"})
        identity = services._common_identity(normalized, {"source": "RRHH", "id": 701})
        self.assertTrue(institutional_selection(identity)[0])
        self.assertIsNone(identity["local_user_id"])

    def test_disabled_rrhh_is_not_reactivated_by_merge(self):
        user = User.objects.create_user(username="persona", email="persona@petropar.gov.py", id_personal=701)
        local = services._common_identity(services._normalize_local_user(user), {"source": "LOCAL", "id": str(user.pk)}, user)
        rrhh = self.identity(is_active=False)
        rrhh.update(name="Persona Institucional", document_number="", employee_number="")
        merged = services._merge_linked_identities([local, rrhh])[0]
        self.assertFalse(merged["is_active"])

    def test_later_local_link_can_be_resolved_without_changing_snapshot(self):
        from apps.directory.identity_selection import resolve_persisted_identity
        identity = self.identity()
        snapshot = institutional_snapshot(identity)
        linked = {**identity, "local_user_id": "later-local", "_locator": {"source": "LOCAL", "id": "later-local"}, "_linked": [identity["_locator"]]}
        with patch.object(services, "resolve_common_identity", return_value=identity), patch.object(services, "search_common_identities", return_value={"incomplete": False, "identities": [linked]}):
            resolved = resolve_persisted_identity(snapshot)
        self.assertEqual(resolved["local_user_id"], "later-local")
        self.assertEqual(snapshot["locator"], {"source": "RRHH", "id": 701})

    def test_unlinked_matching_email_never_creates_local_association(self):
        from apps.directory.identity_selection import resolve_persisted_identity
        identity = self.identity()
        unsafe = {**identity, "local_user_id": "other", "_locator": {"source": "LOCAL", "id": "other"}, "_linked": []}
        with patch.object(services, "resolve_common_identity", return_value=identity), patch.object(services, "search_common_identities", return_value={"incomplete": False, "identities": [unsafe]}):
            resolved = resolve_persisted_identity(institutional_snapshot(identity))
        self.assertIsNone(resolved["local_user_id"])
