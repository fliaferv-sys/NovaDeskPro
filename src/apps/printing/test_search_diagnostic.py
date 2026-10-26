"""Read-only diagnostic coverage; these fixtures do not claim MESATI's cause."""
import ast
import base64
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.http import QueryDict
from django.test import TestCase, SimpleTestCase
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import Department
from apps.printing.models import PrintingDevice, PrintingDeviceUserAssignment
from apps.printing import inventory_users


class PrintingDiagnosticInputTests(SimpleTestCase):
    def setUp(self):
        source = (Path(settings.BASE_DIR)/"tools/Diagnosticar_Busqueda_Printing_SoloLectura.ps1").read_text(encoding="utf-8-sig")
        tree = ast.parse(source.split("$Codigo = @'",1)[1].split("'@",1)[0])
        functions = [n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {"read_input","classify_query"}]
        self.namespace = {"json":json,"base64":base64}
        exec(compile(ast.Module(body=functions,type_ignores=[]),"diagnostic-input-tests","exec"),self.namespace)

    def test_empty_service_fields_are_preserved_without_index_error(self):
        data = dict(ariel_url="/psline/equipos/?search=Ariel",silvio_url="/psline/equipos/?search=Silvio",
            third_url="/psline/equipos/?search=comercial&department=&user_unit=&installation=",
            service_directory="",service_python="",service_module="",service_settings="")
        encoded = base64.b64encode(json.dumps(data).encode()).decode()
        self.assertEqual(self.namespace["read_input"](["-",encoded]),data)
        with self.assertRaisesRegex(RuntimeError,"INPUT_ARGUMENT_MISSING"):
            self.namespace["read_input"](["-"])

    def test_comercial_with_empty_department_fields_is_text_search(self):
        query = QueryDict("search=comercial&department=&user_unit=&installation=")
        actual = self.namespace["classify_query"](query)
        self.assertEqual(actual["query_kind"],"text_search")
        self.assertEqual(actual["active_department_fields"],[])

    def test_nonempty_department_field_is_required_for_department_filter(self):
        for key in ("department","user_unit","installation"):
            actual = self.namespace["classify_query"](QueryDict(f"search=comercial&{key}=1"))
            self.assertEqual(actual["query_kind"],"department_filter")
            self.assertEqual(actual["active_department_fields"],[key])


class PrintingSearchDiagnosticTests(TestCase):
    def setUp(self):
        sync = patch("apps.accounts.signals.try_sync_user_institutional_data")
        sync.start()
        self.addCleanup(sync.stop)
        self.department = Department.objects.create(name="Financiera", code="DIAG-FIN")
        self.ariel = User.objects.create_user(username="diag-ariel", email="private-ariel@example.test", first_name="Ariel", last_name="PrivateSurname", department=self.department)
        self.silvio = User.objects.create_user(username="diag-silvio", email="private-silvio@example.test", first_name="Silvio", last_name="OtherPrivateSurname", department=self.department)

    def diagnostic(self, department_query=None):
        source = (Path(settings.BASE_DIR)/"tools/Diagnosticar_Busqueda_Printing_SoloLectura.ps1").read_text(encoding="utf-8-sig")
        embedded = source.split("$Codigo = @'", 1)[1].split("'@", 1)[0]
        tree = ast.parse(embedded)
        main = next(node for node in tree.body if isinstance(node, ast.Try))
        snapshot = next(node for node in main.body if isinstance(node, ast.With))
        helper_nodes = [node for node in main.body if isinstance(node, ast.FunctionDef)]
        sql_guard = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "sql_guard")
        import sqlite3
        namespace = dict(connection=connection, transaction=transaction, get_user_model=get_user_model,
            PrintingDevice=PrintingDevice, PrintingDeviceUserAssignment=PrintingDeviceUserAssignment,
            inventory_users=inventory_users, Q=Q, QueryDict=QueryDict, patch=patch, SimpleNamespace=SimpleNamespace,
            report={}, sqlite3=sqlite3,
            requests={"Ariel":QueryDict("search=Ariel&lifecycle=all"), "Silvio":QueryDict("search=Silvio&lifecycle=all"),
                      "department":QueryDict(department_query or f"department={self.department.pk}&lifecycle=all")},
            allowed_filters=("lifecycle", "department", "user_unit", "installation", "location", "brand", "model", "status"))
        exec(compile(ast.Module(body=[sql_guard,*helper_nodes],type_ignores=[]),"diagnostic-helpers","exec"),namespace)
        connection.ensure_connection()
        connection.cursor().execute("PRAGMA query_only=ON")
        connection.connection.set_authorizer(namespace["sql_guard"])
        try:
            exec(compile(ast.Module(body=[snapshot],type_ignores=[]),"diagnostic-snapshot","exec"),namespace)
        finally:
            connection.connection.set_authorizer(None)
            connection.cursor().execute("PRAGMA query_only=OFF")
        return namespace["report"]

    def test_identifies_common_legacy_text_source_for_people_and_department(self):
        PrintingDevice.objects.create(photocopier_id="12", notes="Responsable: Ariel PrivateSurname. Departamento: Financiera.")
        PrintingDevice.objects.create(photocopier_id="27", notes="Responsable: Silvio OtherPrivateSurname. Departamento: Financiera.")
        report = self.diagnostic()
        for name in ("Ariel", "Silvio"):
            self.assertEqual(report["actual_queries"][name]["received_url"]["total"],1)
            self.assertEqual(report["people"][name]["stored_matches"]["responsible_fk"],0)
            self.assertTrue(report["people"][name]["printer_match_sources"][0]["notes_has_term"])
        self.assertEqual(report["actual_queries"]["department"]["received_url"]["total"],0)
        self.assertEqual(report["selected_departments"]["department"]["catalog_label_in_legacy_notes_count"],2)

    def test_compares_responsible_snapshot_and_current_and_ended_assignments(self):
        first = PrintingDevice.objects.create(photocopier_id="12",responsible_user=self.ariel)
        second = PrintingDevice.objects.create(photocopier_id="27",responsible_identity={"name":"Silvio OtherPrivateSurname"})
        PrintingDeviceUserAssignment.objects.create(device=second,user=self.ariel,assigned_by=self.ariel)
        ended_device = PrintingDevice.objects.create(photocopier_id="45")
        at = timezone.now()
        PrintingDeviceUserAssignment.objects.create(device=ended_device,user=self.silvio,assigned_by=self.ariel,
            assigned_at=at,ended_at=at,ended_by=self.ariel)
        report=self.diagnostic()
        self.assertEqual(report["actual_queries"]["Ariel"]["received_url"]["total"],2)
        self.assertEqual(report["actual_queries"]["Silvio"]["received_url"]["total"],1)
        self.assertEqual(report["people"]["Ariel"]["stored_matches"]["responsible_fk"],1)
        self.assertEqual(report["people"]["Ariel"]["stored_matches"]["current_assignment_printers"],1)
        self.assertEqual(report["people"]["Silvio"]["stored_matches"]["responsible_json_name_sql"],1)
        self.assertEqual(report["people"]["Silvio"]["stored_matches"]["ended_assignment_printers"],1)

    def test_reports_filter_exclusion_without_printing_personal_values(self):
        PrintingDevice.objects.create(photocopier_id="12", responsible_user=self.ariel)
        report=self.diagnostic("department=invalid&lifecycle=all")
        self.assertEqual(report["actual_queries"]["department"]["received_url"]["total"],0)
        self.assertEqual(report["actual_queries"]["department"]["without_each_filter"]["department"],1)
        self.assertFalse(report["selected_departments"]["department"]["valid_id_format"])
        serialized=json.dumps(report)
        self.assertNotIn("PrivateSurname",serialized)
        self.assertNotIn("@example.test",serialized)
        self.assertNotIn(str(self.ariel.pk),serialized)

    def test_diagnostic_preserves_all_local_relation_rows(self):
        PrintingDevice.objects.create(photocopier_id="12",responsible_user=self.ariel)
        models=(PrintingDevice, PrintingDeviceUserAssignment,User,Department)
        before=[list(model.objects.order_by("pk").values()) for model in models]
        self.diagnostic()
        self.assertEqual([list(model.objects.order_by("pk").values()) for model in models],before)
