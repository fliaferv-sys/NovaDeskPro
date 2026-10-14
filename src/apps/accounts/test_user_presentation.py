from pathlib import Path
from html.parser import HTMLParser
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import User
from apps.accounts.user_presentation import enrich_user_list
from apps.directory.identity_services import get_user_photo_url
from apps.directory.services import DirectoryDatabaseError
from apps.accounts.tests import TEST_STORAGES


class UserRowParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cells = []
        self.in_row = False
        self.in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag == "tr" and "data-user-row" in dict(attrs):
            self.in_row = True
        if tag == "td" and self.in_row:
            self.in_cell = True
            self.cells.append("")

    def handle_data(self, data):
        if self.in_cell:
            self.cells[-1] += data

    def handle_endtag(self, tag):
        if tag == "td":
            self.in_cell = False
        if tag == "tr":
            self.in_row = False


class UserPresentationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sample", email="sample@petropar.gov.py", role="ADMIN")
        self.identity = dict(id_personal=12, email=self.user.email, employee_number="1002",
                             phone="123456", position="Cargo institucional", location="Secretaría",
                             source="RRHH", source_label="AD + RR.HH.", is_active=True)

    def batch_rows(self, terms, identities=None):
        identities = [self.identity] if identities is None else identities
        columns = {"rrhh_id": "id_personal", "employee_number": "employee_number", "email": "email", "name": "name"}
        def row(identity):
            return dict(IdPersonal=identity.get("id_personal"), LegajoNro=identity.get("employee_number"),
                        Mail=identity.get("email"), NombresApellidos=identity.get("name"),
                        Telefono=identity.get("phone"), Cargo=identity.get("position"), Ubicacion=identity.get("location"),
                        Estado="Activo" if identity.get("is_active") else "Inactivo")
        return {term: [row(identity) for identity in identities
                       if str(identity.get(columns[term[1]]) or "").strip().casefold() == term[0].strip().casefold()] for term in terms}

    def enrich(self, identities=None):
        with patch("apps.directory.user_resolution.search_directory_employees_batch",
                   side_effect=lambda terms: self.batch_rows(terms, identities)) as lookup, patch(
                   "apps.directory.user_resolution.search_ad_users_batch", side_effect=lambda terms: {term: [] for term in terms}):
            enrich_user_list([self.user])
            lookup.assert_called_once()

    def test_fallback_fields_and_no_writes(self):
        before = User.objects.values().get(pk=self.user.pk)
        with self.assertNumQueries(2):
            self.enrich()
        self.assertEqual(self.user.display_employee_number, "1002")
        self.assertEqual(self.user.display_phone, "123456")
        self.assertEqual(self.user.display_position, "Cargo institucional")
        self.assertEqual(self.user.display_location, "Secretaría")
        self.assertEqual(self.user.institutional_source, "RR.HH.")
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
            self.assertEqual(self.user.display_location, "")

    def test_id_personal_conflict_rejected(self):
        self.user.id_personal = 99
        self.enrich()
        self.assertEqual(self.user.display_phone, "")

    def test_source_unavailable_retains_local_data(self):
        with patch("apps.directory.user_resolution.search_directory_employees_batch", side_effect=DirectoryDatabaseError("Unavailable")):
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
        with patch("apps.directory.user_resolution.search_directory_employees_batch", side_effect=self.batch_rows):
            response = self.client.get(reverse("user_list"))
        self.assertEqual(response.status_code, 200)
        for value in ("123456", "1002", "Cargo institucional", self.user.email, self.user.username):
            self.assertContains(response, value)

    def test_batch_load_once_for_multiple_accounts(self):
        other = User.objects.create_user(username="other", email="other@example.test")
        with patch("apps.directory.user_resolution.search_directory_employees_batch", side_effect=self.batch_rows) as lookup:
            enrich_user_list([self.user, other])
        lookup.assert_called_once()
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
        self.assertEqual(self.user.display_location, "Secretaría")
        self.user.branch = self.user.organizational_unit = self.user.department = None
        self.enrich()
        self.assertEqual(self.user.display_branch, "")
        self.assertEqual(self.user.display_unit, "")
        self.assertEqual(self.user.display_department, "")
        self.assertEqual(self.user.display_location, "Secretaría")

    def test_inactive_or_identifier_conflicting_person_is_not_presented(self):
        for identity in (dict(self.identity, is_active=False), dict(self.identity, email="otra@petropar.gov.py")):
            self.enrich([identity])
            self.assertEqual(self.user.display_phone, "")
            self.assertEqual(self.user.institutional_source, "")
            self.assertEqual(self.user.display_location, "")

    @override_settings(STORAGES=TEST_STORAGES)
    def test_location_column_is_institutional_independent_and_get_does_not_write(self):
        from apps.accounts.models import Branch
        from apps.core.models import Department
        from apps.institution.models import OrganizationalUnit
        self.user.branch = Branch.objects.create(code="LOCATION-BRANCH", name="Sede local")
        self.user.organizational_unit = OrganizationalUnit.objects.create(
            code="LOCATION-UNIT", name="Dependencia local", unit_type="UNIT")
        self.user.department = Department.objects.create(code="LOCATION-TEAM", name="Equipo operativo")
        self.user.save(update_fields=["branch", "organizational_unit", "department"])
        self.client.force_login(self.user)
        before = User.objects.values().get(pk=self.user.pk)
        for location, expected in (("Ubicación RRHH", "Ubicación RRHH"), ("", "Sin registrar"),
                                   (None, "Sin registrar"), ("   ", "Sin registrar")):
            identity = dict(self.identity, location=location, organizational_unit={"name": "Mapping institucional"})
            with self.subTest(location=location), patch(
                "apps.directory.user_resolution.search_directory_employees_batch", side_effect=lambda terms: self.batch_rows(terms, [identity])
            ), patch("apps.accounts.institutional_sync.try_sync_user_institutional_data") as sync, CaptureQueriesContext(connection) as queries:
                response = self.client.get(reverse("user_list"))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "<th>Ubicación</th>", html=True)
            self.assertNotContains(response, "<th>Sede o planta</th>", html=True)
            parser = UserRowParser()
            parser.feed(response.content.decode())
            cells = [" ".join(cell.split()) for cell in parser.cells]
            self.assertEqual(cells[3], expected)
            self.assertEqual(cells[4], "Dependencia local")
            self.assertEqual(cells[5], "Equipo operativo")
            self.assertNotContains(response, "Sede local")
            self.assertEqual(User.objects.values().get(pk=self.user.pk), before)
            self.assertFalse(any(query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for query in queries))
            sync.assert_not_called()

    def test_location_does_not_replace_safe_institutional_unit_mapping(self):
        from apps.institution.models import OrganizationalUnit, InstitutionalIdentityAssignment
        unit = OrganizationalUnit.objects.create(code="MAPPING-UNIT", name="Dependencia por mapping", unit_type="UNIT")
        InstitutionalIdentityAssignment.objects.create(id_personal=12, organizational_unit=unit)
        self.enrich()
        self.assertEqual(self.user.display_location, "Secretaría")
        self.assertEqual(self.user.display_unit, "Dependencia por mapping")
        self.assertEqual(self.user.display_department, "")
