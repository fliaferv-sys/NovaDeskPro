from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.user_presentation import enrich_user_list
from apps.directory.identity_services import get_user_photo_url
from apps.directory.services import DirectoryDatabaseError


class UserPresentationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sample", email="sample@petropar.gov.py", role="ADMIN")
        self.identity = dict(id_personal=12, email=self.user.email, employee_number="1002",
                             phone="123456", position="Cargo institucional", location="Secretaría",
                             source="RRHH", source_label="AD + RR.HH.", is_active=True)

    def enrich(self, identities=None):
        with patch("apps.accounts.user_presentation.get_institutional_directory",
                   return_value=[self.identity] if identities is None else identities) as lookup:
            enrich_user_list([self.user])
            lookup.assert_called_once_with()

    def test_fallback_fields_and_no_writes(self):
        before = User.objects.values().get(pk=self.user.pk)
        with self.assertNumQueries(0):
            self.enrich()
        self.assertEqual(self.user.display_employee_number, "1002")
        self.assertEqual(self.user.display_phone, "123456")
        self.assertEqual(self.user.display_position, "Cargo institucional")
        self.assertEqual(self.user.display_location, "")
        self.assertEqual(self.user.institutional_source, "AD + RR.HH.")
        self.assertEqual(User.objects.values().get(pk=self.user.pk), before)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(self.user.role, "ADMIN")

    def test_local_values_take_priority(self):
        self.user.phone, self.user.position, self.user.employee_number = "local", "Local", "009"
        self.enrich()
        self.assertEqual(self.user.display_phone, "local")
        self.assertEqual(self.user.display_position, "Local")
        self.assertEqual(self.user.display_employee_number, "009")

    def test_missing_ambiguous_and_conflicting_identity(self):
        for identities in ([], [self.identity, self.identity.copy()],
                           [dict(self.identity, email="other@petropar.gov.py")]):
            self.enrich(identities)
            self.assertEqual(self.user.display_phone, "")

    def test_id_personal_conflict_rejected(self):
        self.user.id_personal = 99
        self.enrich()
        self.assertEqual(self.user.display_phone, "")

    def test_source_unavailable_retains_local_data(self):
        with patch("apps.accounts.user_presentation.get_institutional_directory", side_effect=DirectoryDatabaseError("Unavailable")):
            enrich_user_list([self.user])
        self.assertEqual(self.user.display_phone, "")

    def test_photos_local_and_institutional_and_uploaded(self):
        with TemporaryDirectory() as folder, override_settings(MEDIA_ROOT=folder, MEDIA_URL="/media/"):
            directory = Path(folder) / "funcionarios"
            directory.mkdir()
            (directory / "1002F.jpg").touch()
            (directory / "009F.jpg").touch()
            self.enrich()
            self.assertEqual(self.user.institutional_photo_url, "/media/funcionarios/1002F.jpg")
            self.user.employee_number = "009"
            self.assertEqual(get_user_photo_url(self.user), "/media/funcionarios/009F.jpg")
            self.assertEqual(get_user_photo_url(self.user, identity=self.identity), "/media/funcionarios/009F.jpg")
            self.user.profile_image = "profiles/upload.jpg"
            self.assertEqual(get_user_photo_url(self.user, identity=self.identity), "/media/profiles/upload.jpg")

    def test_outsourced_photo_unchanged(self):
        with patch("apps.directory.identity_services._get_tercerizado", return_value={"photo_file": "5115744F.jpg"}), patch("apps.directory.identity_services._build_tercerizado_photo_url", return_value="/media/funcionarios/5115744F.jpg"):
            self.assertEqual(get_user_photo_url(self.user), "/media/funcionarios/5115744F.jpg")

    def test_list_loads_with_enrichment_and_local_login(self):
        self.client.force_login(self.user)
        with patch("apps.accounts.user_presentation.get_institutional_directory", return_value=[self.identity]):
            response = self.client.get(reverse("user_list"))
        self.assertEqual(response.status_code, 200)
        for value in ("123456", "1002", "Cargo institucional", self.user.email, self.user.username):
            self.assertContains(response, value)

    def test_batch_load_once_for_multiple_accounts(self):
        other = User.objects.create_user(username="other", email="other@example.test")
        with patch("apps.accounts.user_presentation.get_institutional_directory", return_value=[self.identity]) as lookup:
            enrich_user_list([self.user, other])
        lookup.assert_called_once_with()
        self.assertEqual(other.display_phone, "")

    def test_three_columns_never_use_each_other_as_fallback(self):
        from apps.accounts.models import Branch
        from apps.core.models import Department
        from apps.institution.models import OrganizationalUnit
        branch = Branch.objects.create(code="PRESENTATION-BRANCH", name="Sede física")
        unit = OrganizationalUnit.objects.create(code="PRESENTATION-UNIT", name="Dependencia", unit_type="UNIT")
        department = Department.objects.create(code="PRESENTATION-TEAM", name="Equipo de soporte")
        self.user.branch, self.user.organizational_unit, self.user.department = branch, unit, department
        self.enrich()
        self.assertEqual(self.user.display_branch, branch)
        self.assertEqual(self.user.display_unit, unit)
        self.assertEqual(self.user.display_department, department)
        self.user.branch = self.user.organizational_unit = self.user.department = None
        self.enrich()
        self.assertEqual(self.user.display_branch, "")
        self.assertEqual(self.user.display_unit, "")
        self.assertEqual(self.user.display_department, "")

    def test_inactive_or_identifier_conflicting_person_is_not_presented(self):
        for identity in (dict(self.identity, is_active=False), dict(self.identity, username="otra")):
            self.enrich([identity])
            self.assertEqual(self.user.display_phone, "")
            self.assertEqual(self.user.institutional_source, "")
