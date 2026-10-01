from unittest.mock import MagicMock, patch

import pyodbc
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .services import (
    DirectoryDatabaseError,
    get_directory_employees,
    get_directory_employee_by_id_personal,
    search_directory_employees,
    test_directory_connection,
)


@override_settings(
    DIRECTORY_SQL_HOST="mock-host.invalid",
    DIRECTORY_SQL_PORT="1433",
    DIRECTORY_SQL_DATABASE="mock-directory",
    DIRECTORY_SQL_USER="mock-user",
    DIRECTORY_SQL_PASSWORD="mock-password",
    DIRECTORY_SQL_DRIVER="ODBC Driver 18 for SQL Server",
)
class DirectoryDatabaseServiceTests(SimpleTestCase):
    def test_incomplete_configuration_raises_directory_database_error(self):
        with override_settings(DIRECTORY_SQL_PASSWORD=""):
            with patch("apps.directory.services.pyodbc.connect") as connect:
                with self.assertRaises(DirectoryDatabaseError) as context:
                    test_directory_connection()

        self.assertIn("DIRECTORY_SQL_PASSWORD", str(context.exception))
        connect.assert_not_called()

    @patch("apps.directory.services.pyodbc.connect")
    def test_connection_check_returns_true_and_closes_resources(self, connect):
        connection = MagicMock()
        connect.return_value = connection

        self.assertTrue(test_directory_connection())

        connection.cursor.return_value.execute.assert_called_once_with("SELECT 1")
        connection.cursor.return_value.close.assert_called_once_with()
        connection.close.assert_called_once_with()
        self.assertEqual(connect.call_args.kwargs["timeout"], 5)

    @patch("apps.directory.services.pyodbc.connect")
    def test_pyodbc_connection_error_is_wrapped_with_original_cause(self, connect):
        original_error = pyodbc.Error("mock connection failure")
        connect.side_effect = original_error

        with self.assertRaises(DirectoryDatabaseError) as context:
            test_directory_connection()

        self.assertIs(context.exception.__cause__, original_error)

    @patch("apps.directory.services.pyodbc.connect")
    def test_get_directory_employees_returns_column_dictionaries(self, connect):
        connection = MagicMock()
        cursor = connection.cursor.return_value
        cursor.description = [
            (column,)
            for column in (
                "LegajoNro",
                "NombresApellidos",
                "IdPersonal",
                "Ubicacion",
                "Telefono",
                "Mail",
                "Estado",
                "Vinculo",
                "DesvinculacionFecha",
                "Cargo",
            )
        ]
        cursor.fetchall.return_value = [
            (
                "TEST-001",
                "Funcionario de prueba",
                1001,
                "Ubicación de prueba",
                "000000000",
                "test@example.invalid",
                "Activo",
                "Permanente",
                None,
                "Cargo de prueba",
            )
        ]
        connect.return_value = connection

        employees = get_directory_employees()

        self.assertEqual(
            employees,
            [
                {
                    "LegajoNro": "TEST-001",
                    "NombresApellidos": "Funcionario de prueba",
                    "IdPersonal": 1001,
                    "Ubicacion": "Ubicación de prueba",
                    "Telefono": "000000000",
                    "Mail": "test@example.invalid",
                    "Estado": "Activo",
                    "Vinculo": "Permanente",
                    "DesvinculacionFecha": None,
                    "Cargo": "Cargo de prueba",
                }
            ],
        )
        query = cursor.execute.call_args.args[0]
        self.assertTrue(query.startswith("SELECT TOP (50) "))
        self.assertIn("dbo.FuncionariosFotosVista", query)
        self.assertIn("ORDER BY NombresApellidos", query)
        self.assertNotIn("SELECT *", query)
        self.assertNotRegex(query, r"\b(INSERT|UPDATE|DELETE)\b")
        cursor.close.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_get_directory_employees_rejects_out_of_range_limits(self):
        for limit in (0, 201, True, 50.5, "50"):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    get_directory_employees(limit=limit)

    @patch("apps.directory.services.pyodbc.connect")
    def test_search_directory_employees_without_query_lists_in_name_order(
        self,
        connect,
    ):
        connection = MagicMock()
        cursor = connection.cursor.return_value
        cursor.fetchall.return_value = []
        connect.return_value = connection

        self.assertEqual(search_directory_employees("  ", limit=12), [])

        call = cursor.execute.call_args
        query = call.args[0]
        self.assertEqual(len(call.args), 1)
        self.assertIn("SELECT TOP (12)", query)
        self.assertIn("dbo.FuncionariosFotosVista", query)
        self.assertIn("ORDER BY NombresApellidos", query)
        self.assertNotIn("WHERE", query)
        self.assertNotIn("SELECT *", query)
        cursor.close.assert_called_once_with()
        connection.close.assert_called_once_with()

    @patch("apps.directory.services.pyodbc.connect")
    def test_search_directory_employees_passes_search_as_sql_parameters(
        self,
        connect,
    ):
        connection = MagicMock()
        cursor = connection.cursor.return_value
        cursor.fetchall.return_value = []
        connect.return_value = connection

        self.assertEqual(
            search_directory_employees("  Ana Pérez  ", limit=25),
            [],
        )

        call = cursor.execute.call_args
        query = call.args[0]
        self.assertEqual(call.args[1:], ("%Ana Pérez%",) * 4)
        self.assertEqual(query.count("LIKE ?"), 4)
        self.assertNotIn("Ana Pérez", query)
        self.assertIn("LegajoNro", query)
        self.assertIn("NombresApellidos", query)
        self.assertIn("Ubicacion", query)
        self.assertIn("Mail", query)
        self.assertIn("ORDER BY NombresApellidos", query)
        self.assertNotRegex(query, r"\b(INSERT|UPDATE|DELETE)\b")

    def test_search_directory_employees_rejects_invalid_limits(self):
        for limit in (0, 201, True, 50.5, "50"):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    search_directory_employees("", limit=limit)

    @patch("apps.directory.services.pyodbc.connect")
    def test_get_directory_employee_by_id_personal_returns_employee(self, connect):
        connection = MagicMock()
        cursor = connection.cursor.return_value
        cursor.fetchone.return_value = (
            "TEST-003",
            "Funcionario individual de prueba",
            3003,
            "Sede de prueba",
            "000000002",
            "individual@example.invalid",
            "Activo",
            "Permanente",
            None,
            "Cargo de prueba",
        )
        connect.return_value = connection

        employee = get_directory_employee_by_id_personal(" 3003 ")

        self.assertEqual(
            employee,
            {
                "LegajoNro": "TEST-003",
                "NombresApellidos": "Funcionario individual de prueba",
                "IdPersonal": 3003,
                "Ubicacion": "Sede de prueba",
                "Telefono": "000000002",
                "Mail": "individual@example.invalid",
                "Estado": "Activo",
                "Vinculo": "Permanente",
                "DesvinculacionFecha": None,
                "Cargo": "Cargo de prueba",
            },
        )
        call = cursor.execute.call_args
        sql = call.args[0]
        self.assertIn("FROM dbo.FuncionariosFotosVista", sql)
        self.assertIn("WHERE IdPersonal = ?", sql)
        self.assertNotIn("3003", sql)
        self.assertEqual(call.args[1:], (3003,))
        self.assertNotRegex(sql, r"\b(INSERT|UPDATE|DELETE)\b")
        cursor.close.assert_called_once_with()
        connection.close.assert_called_once_with()

    @patch("apps.directory.services.pyodbc.connect")
    def test_get_directory_employee_by_id_personal_returns_none_when_missing(
        self,
        connect,
    ):
        connection = MagicMock()
        connection.cursor.return_value.fetchone.return_value = None
        connect.return_value = connection

        self.assertIsNone(get_directory_employee_by_id_personal(4004))

        cursor = connection.cursor.return_value
        self.assertEqual(
            cursor.execute.call_args.args[1:],
            (4004,),
        )
        cursor.close.assert_called_once_with()
        connection.close.assert_called_once_with()

    @patch("apps.directory.services.pyodbc.connect")
    def test_get_directory_employee_by_id_personal_rejects_invalid_ids(
        self,
        connect,
    ):
        invalid_ids = (None, "", "  ", 0, "0", -1, "-1", True, False, "abc", 1.5)
        for id_personal in invalid_ids:
            with self.subTest(id_personal=id_personal):
                with self.assertRaisesRegex(ValueError, "IdPersonal"):
                    get_directory_employee_by_id_personal(id_personal)

        connect.assert_not_called()

    @patch("apps.directory.services.pyodbc.connect")
    def test_get_directory_employee_by_id_personal_wraps_pyodbc_error(self, connect):
        connection = MagicMock()
        cursor = connection.cursor.return_value
        original_error = pyodbc.Error("mock query failure")
        cursor.execute.side_effect = original_error
        connect.return_value = connection

        with self.assertRaises(DirectoryDatabaseError) as context:
            get_directory_employee_by_id_personal(5005)

        self.assertIs(context.exception.__cause__, original_error)
        cursor.close.assert_called_once_with()
        connection.close.assert_called_once_with()


class DirectoryHomeViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="directory-user",
            email="directory-user@example.com",
            password="test-password",
        )

    @patch("apps.directory.views.search_directory_employees", return_value=[])
    def test_authenticated_user_can_access_directory_home(self, search):
        self.client.force_login(self.user)

        response = self.client.get(reverse("directory:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Directorio Institucional")
        search.assert_called_once_with("", limit=100)

    @patch("apps.directory.views.search_directory_employees")
    def test_directory_home_displays_mocked_employees(self, search):
        search.return_value = [
            {
                "LegajoNro": "TEST-002",
                "NombresApellidos": "Persona de prueba",
                "IdPersonal": 2002,
                "Ubicacion": "Sede de prueba",
                "Telefono": "000000001",
                "Mail": "persona@example.invalid",
                "Estado": "Activo",
                "Vinculo": "Permanente",
                "DesvinculacionFecha": None,
                "Cargo": "Cargo de prueba",
            }
        ]
        self.client.force_login(self.user)

        response = self.client.get(reverse("directory:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Persona de prueba")
        self.assertContains(response, "TEST-002")
        self.assertEqual(response.context["employees"], search.return_value)

    @patch("apps.directory.views.search_directory_employees", return_value=[])
    def test_directory_home_preserves_search_query(self, search):
        self.client.force_login(self.user)

        response = self.client.get(reverse("directory:home"), {"q": "  Ana  "})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["search_query"], "Ana")
        search.assert_called_once_with("Ana", limit=100)

    @patch("apps.directory.views.search_directory_employees")
    def test_directory_database_error_renders_friendly_message(self, search):
        search.side_effect = DirectoryDatabaseError("technical secret details")
        self.client.force_login(self.user)

        response = self.client.get(reverse("directory:home"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["employees"], [])
        self.assertContains(
            response,
            "No fue posible consultar el Directorio Institucional "
            "en este momento.",
        )
        self.assertNotContains(response, "technical secret details")

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("directory:home"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            f"{reverse('login')}?next={reverse('directory:home')}",
        )
