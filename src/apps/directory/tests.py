from contextlib import contextmanager
import ssl
from types import ModuleType
from unittest.mock import MagicMock, patch

import pyodbc
from ldap3.core.exceptions import LDAPBindError, LDAPException
from ldap3.utils.conv import escape_filter_chars
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.core.models import Department
from apps.institution.models import (
    InstitutionalIdentityAssignment,
    OrganizationalUnit,
)

from . import ad_services
from . import identity_services
from .ad_services import ActiveDirectoryError
from .services import (
    DirectoryDatabaseError,
    get_directory_employees,
    get_directory_employee_by_id_personal,
    search_directory_employees,
    test_directory_connection,
)


def make_rrhh_employee(**overrides):
    employee = {
        "IdPersonal": 1234,
        "LegajoNro": "RRHH-1234",
        "NombresApellidos": "Nombre RRHH",
        "Mail": "rrhh@example.test",
        "Telefono": "555-0100",
        "Ubicacion": "Sede RRHH",
        "Cargo": "Cargo RRHH",
        "Vinculo": "Permanente",
        "Estado": "Activo",
    }
    employee.update(overrides)
    return employee


def make_ad_user(**overrides):
    user = {
        "name": "Nombre AD",
        "first_name": "Nombre",
        "last_name": "AD",
        "email": "ad@example.test",
        "username": "ad-user",
        "user_principal_name": "ad-user@example.test",
        "is_active": True,
    }
    user.update(overrides)
    return user


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

    @patch("apps.directory.services.pyodbc.connect")
    def test_get_directory_employees_rejects_out_of_range_limits(self, connect):
        for limit in (0, -1, -5000, 5001, True, False, 50.5, "50"):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    get_directory_employees(limit=limit)
        connect.assert_not_called()

        cursor = connect.return_value.cursor.return_value
        cursor.fetchall.return_value = []
        self.assertEqual(get_directory_employees(limit=5000), [])
        connect.assert_called_once()
        self.assertTrue(cursor.execute.call_args.args[0].startswith("SELECT TOP (5000) "))
        cursor.close.assert_called_once_with()
        connect.return_value.close.assert_called_once_with()

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


@override_settings(
    DIRECTORY_AD_HOST="mock-ad.example.test",
    DIRECTORY_AD_PORT=636,
    DIRECTORY_AD_BASE_DN="DC=example,DC=test",
    DIRECTORY_AD_DOMAIN="example.test",
    DIRECTORY_AD_USER="mock-user",
    DIRECTORY_AD_PASSWORD="mock-password",
    DIRECTORY_AD_USE_SSL=True,
    DIRECTORY_AD_TLS_VALIDATE=True,
    DIRECTORY_AD_CA_CERT_FILE="",
)
class ActiveDirectoryServiceTests(SimpleTestCase):
    def make_entry(self, **overrides):
        attributes = {
            "displayName": "Ada Lovelace",
            "givenName": "Ada",
            "sn": "Lovelace",
            "mail": "ada@example.test",
            "sAMAccountName": "alovelace",
            "userPrincipalName": "alovelace@example.test",
            "userAccountControl": 512,
        }
        attributes.update(overrides)
        entry = MagicMock()
        entry.entry_attributes_as_dict = attributes
        return entry

    @contextmanager
    def bound_connection(self, connection):
        yield connection

    @contextmanager
    def mock_windows_security(self):
        class FakeWinError(Exception):
            def __init__(self, error_code):
                super().__init__(error_code, "LogonUser", "mock Windows error")
                self.winerror = error_code

        win32security = ModuleType("win32security")
        win32security.LOGON32_LOGON_NETWORK = 3
        win32security.LOGON32_PROVIDER_DEFAULT = 0
        win32security.LogonUser = MagicMock(return_value=MagicMock())

        pywintypes = ModuleType("pywintypes")
        pywintypes.error = FakeWinError

        with (
            patch.object(ad_services.sys, "platform", "win32"),
            patch.dict(
                ad_services.sys.modules,
                {
                    "win32security": win32security,
                    "pywintypes": pywintypes,
                },
            ),
            patch.object(
                ad_services,
                "win32security",
                win32security,
                create=True,
            ),
            patch.object(
                ad_services,
                "pywintypes",
                pywintypes,
                create=True,
            ),
        ):
            yield win32security, pywintypes

    def test_validate_ad_configuration_accepts_complete_settings(self):
        ad_services._validate_ad_configuration()

    def test_validate_ad_configuration_rejects_missing_user(self):
        with override_settings(DIRECTORY_AD_USER=""):
            with self.assertRaises(ad_services.ActiveDirectoryError):
                ad_services._validate_ad_configuration()

    def test_validate_ad_configuration_rejects_missing_password(self):
        with override_settings(DIRECTORY_AD_PASSWORD=""):
            with self.assertRaises(ad_services.ActiveDirectoryError):
                ad_services._validate_ad_configuration()

    def test_entry_to_user_returns_only_allowed_profile_fields(self):
        user = ad_services._entry_to_user(self.make_entry())

        self.assertEqual(
            user,
            {
                "name": "Ada Lovelace",
                "first_name": "Ada",
                "last_name": "Lovelace",
                "email": "ada@example.test",
                "username": "alovelace",
                "user_principal_name": "alovelace@example.test",
                "is_active": True,
            },
        )

    def test_entry_to_user_marks_disabled_account_inactive(self):
        user = ad_services._entry_to_user(
            self.make_entry(userAccountControl=514)
        )

        self.assertFalse(user["is_active"])

    def test_get_ad_user_by_email_rejects_invalid_email(self):
        with patch("apps.directory.ad_services._bound_ad_connection") as bound:
            for email in (None, "", "  ", 123):
                with self.subTest(email=email):
                    with self.assertRaises(ValueError):
                        ad_services.get_ad_user_by_email(email)

        bound.assert_not_called()

    def test_get_ad_user_by_email_returns_none_when_not_found(self):
        connection = MagicMock()
        connection.entries = []
        bound = self.bound_connection(connection)

        with patch(
            "apps.directory.ad_services._bound_ad_connection",
            return_value=bound,
        ):
            user = ad_services.get_ad_user_by_email("ada@example.test")

        self.assertIsNone(user)
        connection.search.assert_called_once()

    def test_get_ad_user_by_email_returns_user_and_escapes_filter(self):
        connection = MagicMock()
        connection.entries = [self.make_entry()]
        bound = self.bound_connection(connection)
        email = "ada*(test)@example.test"

        with patch(
            "apps.directory.ad_services._bound_ad_connection",
            return_value=bound,
        ):
            user = ad_services.get_ad_user_by_email(email)

        self.assertEqual(user["name"], "Ada Lovelace")
        connection.search.assert_called_once_with(
            search_base="DC=example,DC=test",
            search_filter=(
                "(&(objectCategory=person)(objectClass=user)"
                f"(mail={escape_filter_chars(email)}))"
            ),
            attributes=ad_services._AD_USER_ATTRIBUTES,
            size_limit=1,
        )

    def test_search_ad_users_rejects_invalid_query_and_limit(self):
        with patch("apps.directory.ad_services._bound_ad_connection") as bound:
            with self.assertRaises(ValueError):
                ad_services.search_ad_users(None)
            self.assertEqual(ad_services.search_ad_users(" A "), [])
            for limit in (0, 101, True, 1.5, "2"):
                with self.subTest(limit=limit):
                    with self.assertRaises(ValueError):
                        ad_services.search_ad_users("Ada", limit=limit)

        bound.assert_not_called()

    def test_search_ad_users_returns_users_and_uses_expected_filter(self):
        connection = MagicMock()
        connection.entries = [
            self.make_entry(),
            self.make_entry(
                displayName="Grace Hopper",
                givenName="Grace",
                sn="Hopper",
                mail="grace@example.test",
                sAMAccountName="ghopper",
                userPrincipalName="ghopper@example.test",
            ),
        ]
        bound = self.bound_connection(connection)

        with patch(
            "apps.directory.ad_services._bound_ad_connection",
            return_value=bound,
        ):
            users = ad_services.search_ad_users(" Ada* ", limit=2)

        self.assertEqual([user["name"] for user in users], ["Ada Lovelace", "Grace Hopper"])
        search_call = connection.search.call_args.kwargs
        self.assertEqual(search_call["search_base"], "DC=example,DC=test")
        self.assertEqual(search_call["attributes"], ad_services._AD_USER_ATTRIBUTES)
        self.assertEqual(search_call["size_limit"], 2)
        search_filter = search_call["search_filter"]
        escaped_query = escape_filter_chars("Ada*")
        for attribute in (
            "displayName",
            "mail",
            "sAMAccountName",
            "userPrincipalName",
        ):
            self.assertIn(f"({attribute}=*{escaped_query}*)", search_filter)

    @patch("apps.directory.ad_services._open_ad_connection")
    def test_bound_ad_connection_unbinds_on_normal_exit(self, open_connection):
        connection = MagicMock()
        open_connection.return_value = connection

        with ad_services._bound_ad_connection() as bound:
            self.assertIs(bound, connection)

        connection.unbind.assert_called_once_with()

    @patch("apps.directory.ad_services._open_ad_connection")
    def test_bound_ad_connection_wraps_ldap_error_from_operation(
        self,
        open_connection,
    ):
        connection = MagicMock()
        open_connection.return_value = connection

        with self.assertRaises(ad_services.ActiveDirectoryError):
            with ad_services._bound_ad_connection():
                raise LDAPException("mock operation failure")

        connection.unbind.assert_called_once_with()

    @patch("apps.directory.ad_services._open_ad_connection")
    def test_unbind_error_does_not_replace_normal_exit(self, open_connection):
        connection = MagicMock()
        connection.unbind.side_effect = LDAPException("mock unbind failure")
        open_connection.return_value = connection

        with ad_services._bound_ad_connection():
            pass

        connection.unbind.assert_called_once_with()

    @patch("apps.directory.ad_services._open_ad_connection")
    def test_test_ad_connection_returns_true_when_bound(self, open_connection):
        connection = MagicMock()
        connection.bound = True
        open_connection.return_value = connection

        self.assertTrue(ad_services.test_ad_connection())

        connection.unbind.assert_called_once_with()

    @patch("apps.directory.ad_services._open_ad_connection")
    def test_test_ad_connection_raises_when_not_bound(self, open_connection):
        connection = MagicMock()
        connection.bound = False
        open_connection.return_value = connection

        with self.assertRaises(ad_services.ActiveDirectoryError):
            ad_services.test_ad_connection()

        connection.unbind.assert_called_once_with()

    def test_authenticate_windows_credentials_uses_netbios_domain(self):
        with (
            override_settings(DIRECTORY_AD_DOMAIN="PETROPAR"),
            self.mock_windows_security() as (win32security, _),
        ):
            token = win32security.LogonUser.return_value

            result = ad_services.authenticate_windows_credentials(
                "aferreira",
                "secret",
            )

        self.assertTrue(result)
        win32security.LogonUser.assert_called_once_with(
            "aferreira",
            "PETROPAR",
            "secret",
            win32security.LOGON32_LOGON_NETWORK,
            win32security.LOGON32_PROVIDER_DEFAULT,
        )
        token.Close.assert_called_once_with()

    def test_authenticate_windows_credentials_preserves_upn(self):
        with self.mock_windows_security() as (win32security, _):
            result = ad_services.authenticate_windows_credentials(
                "  aferreira@petropar.gov.py  ",
                "secret",
            )

        self.assertTrue(result)
        args = win32security.LogonUser.call_args.args
        self.assertEqual(args[0], "aferreira@petropar.gov.py")
        self.assertIn(args[1], (None, "PETROPAR"))
        self.assertNotEqual(args[1], "PETROPAR\\aferreira@petropar.gov.py")
        self.assertEqual(args[2], "secret")

    def test_authenticate_windows_credentials_splits_domain_username(self):
        with self.mock_windows_security() as (win32security, _):
            result = ad_services.authenticate_windows_credentials(
                "PETROPAR\\aferreira",
                "secret",
            )

        self.assertTrue(result)
        args = win32security.LogonUser.call_args.args
        self.assertEqual(args[:3], ("aferreira", "PETROPAR", "secret"))

    def test_authenticate_windows_credentials_returns_false_for_error_1326(self):
        with self.mock_windows_security() as (win32security, pywintypes):
            win32security.LogonUser.side_effect = pywintypes.error(1326)

            result = ad_services.authenticate_windows_credentials(
                "aferreira",
                "incorrect-secret",
            )

        self.assertFalse(result)

    def test_authenticate_windows_credentials_handles_other_windows_errors_safely(self):
        secret = "private-secret"
        with (
            self.mock_windows_security() as (win32security, pywintypes),
            patch("builtins.print") as print_mock,
            self.assertNoLogs(level="DEBUG"),
        ):
            win32security.LogonUser.side_effect = pywintypes.error(5)
            try:
                result = ad_services.authenticate_windows_credentials(
                    "aferreira",
                    secret,
                )
            except ad_services.ActiveDirectoryError as exc:
                self.assertNotIn(secret, str(exc))
            else:
                self.assertFalse(result)

        print_mock.assert_not_called()

    def test_authenticate_windows_credentials_rejects_invalid_inputs(self):
        with self.mock_windows_security() as (win32security, _):
            invalid_inputs = (
                (None, "secret"),
                ("", "secret"),
                ("   ", "secret"),
                (123, "secret"),
                ("aferreira", None),
                ("aferreira", ""),
                ("aferreira", 123),
            )
            for identifier, password in invalid_inputs:
                with self.subTest(identifier=identifier, password=password):
                    with self.assertRaises(ValueError):
                        ad_services.authenticate_windows_credentials(
                            identifier,
                            password,
                        )

        win32security.LogonUser.assert_not_called()

    def test_authenticate_windows_credentials_preserves_password_and_never_stores_it(self):
        secret = "  password-with-spaces  "
        user_model = get_user_model()
        with (
            self.mock_windows_security() as (win32security, _),
            patch("builtins.print") as print_mock,
            patch.object(user_model, "save") as save_mock,
            self.assertNoLogs(level="DEBUG"),
        ):
            result = ad_services.authenticate_windows_credentials(
                "aferreira",
                secret,
            )

        self.assertTrue(result)
        self.assertEqual(win32security.LogonUser.call_args.args[2], secret)
        win32security.LogonUser.return_value.Close.assert_called_once_with()
        print_mock.assert_not_called()
        save_mock.assert_not_called()

    def test_authenticate_ad_credentials_expands_simple_username(self):
        connection = MagicMock()
        connection.bound = True
        with (
            patch("apps.directory.ad_services.Server") as server_class,
            patch(
                "apps.directory.ad_services.Connection",
                return_value=connection,
            ) as connection_class,
        ):
            result = ad_services.authenticate_ad_credentials(
                "  mcolman  ",
                "secret-password",
            )

        self.assertTrue(result)
        connection_class.assert_called_once_with(
            server_class.return_value,
            user="mcolman@example.test",
            password="secret-password",
            auto_bind=True,
            raise_exceptions=True,
        )
        connection.unbind.assert_called_once_with()

    def test_authenticate_ad_credentials_preserves_email_or_upn(self):
        connection = MagicMock()
        connection.bound = True
        with (
            patch("apps.directory.ad_services.Server") as server_class,
            patch(
                "apps.directory.ad_services.Connection",
                return_value=connection,
            ) as connection_class,
        ):
            result = ad_services.authenticate_ad_credentials(
                "  mcolman@example.test  ",
                "secret-password",
            )

        self.assertTrue(result)
        connection_class.assert_called_once_with(
            server_class.return_value,
            user="mcolman@example.test",
            password="secret-password",
            auto_bind=True,
            raise_exceptions=True,
        )
        connection.unbind.assert_called_once_with()

    def test_authenticate_ad_credentials_returns_false_for_invalid_bind(self):
        with (
            patch("apps.directory.ad_services.Server"),
            patch(
                "apps.directory.ad_services.Connection",
                side_effect=LDAPBindError("invalid credentials"),
            ),
        ):
            result = ad_services.authenticate_ad_credentials(
                "mcolman",
                "incorrect-password",
            )

        self.assertFalse(result)

    def test_authenticate_ad_credentials_wraps_other_ldap_errors(self):
        original_error = LDAPException("mock transport failure")
        with (
            patch("apps.directory.ad_services.Server"),
            patch(
                "apps.directory.ad_services.Connection",
                side_effect=original_error,
            ),
        ):
            with self.assertRaises(ad_services.ActiveDirectoryError) as context:
                ad_services.authenticate_ad_credentials(
                    "mcolman",
                    "secret-password",
                )

        self.assertIs(context.exception.__cause__, original_error)

    def test_authenticate_ad_credentials_rejects_invalid_identifiers(self):
        with (
            patch("apps.directory.ad_services.Server") as server_class,
            patch("apps.directory.ad_services.Connection") as connection_class,
        ):
            for identifier in (None, "", "   ", 123):
                with self.subTest(identifier=identifier):
                    with self.assertRaises(ValueError):
                        ad_services.authenticate_ad_credentials(
                            identifier,
                            "secret-password",
                        )

        server_class.assert_not_called()
        connection_class.assert_not_called()

    def test_authenticate_ad_credentials_rejects_invalid_passwords(self):
        with (
            patch("apps.directory.ad_services.Server") as server_class,
            patch("apps.directory.ad_services.Connection") as connection_class,
        ):
            for password in (None, "", 123):
                with self.subTest(password=password):
                    with self.assertRaises(ValueError):
                        ad_services.authenticate_ad_credentials(
                            "mcolman",
                            password,
                        )

        server_class.assert_not_called()
        connection_class.assert_not_called()

    def test_authenticate_ad_credentials_reuses_tls_configuration(self):
        connection = MagicMock()
        connection.bound = True
        with (
            override_settings(
                DIRECTORY_AD_HOST="custom-ad.example.test",
                DIRECTORY_AD_PORT=1636,
                DIRECTORY_AD_USE_SSL=False,
                DIRECTORY_AD_TLS_VALIDATE=False,
                DIRECTORY_AD_CA_CERT_FILE="mock-ca.pem",
            ),
            patch("apps.directory.ad_services.Tls") as tls_class,
            patch("apps.directory.ad_services.Server") as server_class,
            patch(
                "apps.directory.ad_services.Connection",
                return_value=connection,
            ),
        ):
            self.assertTrue(
                ad_services.authenticate_ad_credentials(
                    "mcolman",
                    "secret-password",
                )
            )

        tls_class.assert_called_once_with(
            validate=ssl.CERT_NONE,
            ca_certs_file="mock-ca.pem",
        )
        server_class.assert_called_once_with(
            host="custom-ad.example.test",
            port=1636,
            use_ssl=False,
            tls=tls_class.return_value,
            get_info=ad_services.ALL,
        )
        connection.unbind.assert_called_once_with()


class InstitutionalIdentityServiceTests(TestCase):
    def test_rrhh_normalization_maps_fields_and_active_state(self):
        employee = make_rrhh_employee()

        identity = identity_services._normalize_rrhh_employee(employee)

        self.assertEqual(identity["source"], "RRHH")
        self.assertEqual(identity["id_personal"], 1234)
        self.assertEqual(identity["employee_number"], "RRHH-1234")
        self.assertEqual(identity["name"], "Nombre RRHH")
        self.assertEqual(identity["email"], "rrhh@example.test")
        self.assertEqual(identity["phone"], "555-0100")
        self.assertEqual(identity["location"], "Sede RRHH")
        self.assertEqual(identity["position"], "Cargo RRHH")
        self.assertEqual(identity["employment_type"], "Permanente")
        self.assertEqual(identity["status"], "Activo")
        self.assertEqual(identity["first_name"], "")
        self.assertEqual(identity["last_name"], "")
        self.assertEqual(identity["username"], "")
        self.assertTrue(identity["is_active"])

        inactive = identity_services._normalize_rrhh_employee(
            make_rrhh_employee(Estado="Inactivo")
        )
        self.assertFalse(inactive["is_active"])

    def test_active_directory_normalization_maps_only_identity_fields(self):
        identity = identity_services._normalize_ad_user(make_ad_user())

        self.assertEqual(identity["source"], "ACTIVE_DIRECTORY")
        self.assertIsNone(identity["id_personal"])
        self.assertEqual(identity["employee_number"], "")
        self.assertEqual(identity["name"], "Nombre AD")
        self.assertEqual(identity["first_name"], "Nombre")
        self.assertEqual(identity["last_name"], "AD")
        self.assertEqual(identity["email"], "ad@example.test")
        self.assertEqual(identity["username"], "ad-user")
        self.assertEqual(identity["phone"], "")
        self.assertEqual(identity["location"], "")
        self.assertEqual(identity["position"], "")
        self.assertEqual(identity["employment_type"], "")
        self.assertEqual(identity["status"], "Activo")
        self.assertTrue(identity["is_active"])

        inactive = identity_services._normalize_ad_user(
            make_ad_user(is_active=False)
        )
        self.assertEqual(inactive["status"], "Inactivo")
        self.assertFalse(inactive["is_active"])

    @patch("apps.directory.identity_services._normalize_local_user")
    @patch("apps.directory.identity_services.get_ad_user_by_email")
    @patch("apps.directory.identity_services.search_directory_employees")
    @patch("apps.directory.identity_services.get_directory_employee_by_id_personal")
    def test_id_personal_rrhh_match_returns_immediately(
        self,
        find_by_id,
        search_rrhh,
        find_ad_user,
        normalize_local,
    ):
        employee = make_rrhh_employee()
        find_by_id.return_value = employee
        local_user = MagicMock()

        identity = identity_services.resolve_institutional_identity(
            id_personal=1234,
            email="local@example.test",
            local_user=local_user,
        )

        self.assertEqual(identity["source"], "RRHH")
        find_by_id.assert_called_once_with(1234)
        search_rrhh.assert_not_called()
        find_ad_user.assert_not_called()
        normalize_local.assert_not_called()

    @patch("apps.directory.identity_services.get_ad_user_by_email")
    @patch("apps.directory.identity_services.search_directory_employees")
    @patch("apps.directory.identity_services.get_directory_employee_by_id_personal")
    def test_id_miss_uses_exact_case_insensitive_rrhh_email_match(
        self,
        find_by_id,
        search_rrhh,
        find_ad_user,
    ):
        find_by_id.return_value = None
        search_rrhh.return_value = [
            make_rrhh_employee(Mail="  RRHH@Example.Test ")
        ]

        identity = identity_services.resolve_institutional_identity(
            id_personal=1234,
            email="  rrhh@example.test  ",
        )

        self.assertEqual(identity["source"], "RRHH")
        search_rrhh.assert_called_once_with("rrhh@example.test", limit=20)
        find_ad_user.assert_not_called()

    @patch("apps.directory.identity_services.get_ad_user_by_email")
    @patch("apps.directory.identity_services.search_directory_employees")
    def test_partial_rrhh_email_match_continues_to_active_directory(
        self,
        search_rrhh,
        find_ad_user,
    ):
        search_rrhh.return_value = [
            make_rrhh_employee(Mail="ana.otro@empresa.test")
        ]
        find_ad_user.return_value = make_ad_user(email="ana@empresa.test")

        identity = identity_services.resolve_institutional_identity(
            email="ana@empresa.test",
        )

        self.assertEqual(identity["source"], "ACTIVE_DIRECTORY")
        find_ad_user.assert_called_once_with("ana@empresa.test")

    @patch("apps.directory.identity_services.get_ad_user_by_email")
    @patch("apps.directory.identity_services.search_directory_employees", return_value=[])
    def test_active_directory_is_used_when_rrhh_has_no_email_match(
        self,
        search_rrhh,
        find_ad_user,
    ):
        find_ad_user.return_value = make_ad_user()

        identity = identity_services.resolve_institutional_identity(
            email="ad@example.test",
        )

        self.assertEqual(identity["source"], "ACTIVE_DIRECTORY")
        search_rrhh.assert_called_once_with("ad@example.test", limit=20)
        find_ad_user.assert_called_once_with("ad@example.test")

    @patch("apps.directory.identity_services.get_ad_user_by_email")
    @patch(
        "apps.directory.identity_services.search_directory_employees",
        side_effect=DirectoryDatabaseError("mock HR failure"),
    )
    def test_rrhh_search_error_continues_to_active_directory(
        self,
        search_rrhh,
        find_ad_user,
    ):
        find_ad_user.return_value = make_ad_user()

        identity = identity_services.resolve_institutional_identity(
            email="ad@example.test",
        )

        self.assertEqual(identity["source"], "ACTIVE_DIRECTORY")
        search_rrhh.assert_called_once_with("ad@example.test", limit=20)
        find_ad_user.assert_called_once_with("ad@example.test")

    @patch("apps.directory.identity_services.User.objects.filter")
    @patch("apps.directory.identity_services.get_ad_user_by_email", return_value=None)
    @patch("apps.directory.identity_services.search_directory_employees", return_value=[])
    def test_no_source_match_returns_none(self, search_rrhh, find_ad_user, user_filter):
        user_filter.return_value.first.return_value = None

        identity = identity_services.resolve_institutional_identity(
            email="missing@example.test",
        )

        self.assertIsNone(identity)
        search_rrhh.assert_called_once()
        find_ad_user.assert_called_once()
        user_filter.assert_called_once_with(email__iexact="missing@example.test")

    @patch(
        "apps.directory.identity_services.get_directory_employee_by_id_personal",
        side_effect=RuntimeError("unexpected failure"),
    )
    def test_unexpected_dependency_error_is_wrapped(self, find_by_id):
        with self.assertRaises(identity_services.InstitutionalIdentityError) as context:
            identity_services.resolve_institutional_identity(id_personal=1234)

        self.assertIsInstance(context.exception.__cause__, RuntimeError)
        find_by_id.assert_called_once_with(1234)

    def test_resolve_identity_for_user_rejects_none(self):
        with self.assertRaises(ValueError):
            identity_services.resolve_identity_for_user(None)


class InstitutionalIdentityLocalFallbackTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(
            code="IDENTITY-LOCAL-TEST",
            name="Departamento de prueba",
        )

    def create_user(self, username, email, **overrides):
        return get_user_model().objects.create_user(
            username=username,
            email=email,
            password="test-password",
            first_name="Nombre local",
            last_name="Apellido local",
            phone="555-0200",
            employee_number=f"EMP-{username}",
            id_personal=5678,
            department=self.department,
            position="Cargo local",
            **overrides,
        )

    def test_local_normalization_maps_user_fields(self):
        user = self.create_user("identity-local-normalize", "local@example.test")

        identity = identity_services._normalize_local_user(user)

        self.assertEqual(identity["source"], "LOCAL")
        self.assertEqual(identity["id_personal"], 5678)
        self.assertEqual(identity["employee_number"], "EMP-identity-local-normalize")
        self.assertEqual(identity["name"], "Nombre local Apellido local")
        self.assertEqual(identity["first_name"], "Nombre local")
        self.assertEqual(identity["last_name"], "Apellido local")
        self.assertEqual(identity["email"], "local@example.test")
        self.assertEqual(identity["phone"], "555-0200")
        self.assertEqual(identity["location"], str(self.department))
        self.assertEqual(identity["position"], "Cargo local")
        self.assertEqual(identity["employment_type"], user.get_employment_type_display())
        self.assertEqual(identity["username"], "identity-local-normalize")
        self.assertTrue(identity["is_active"])
        self.assertEqual(identity["status"], "Activo")

    @patch("apps.directory.identity_services.get_ad_user_by_email", side_effect=ActiveDirectoryError("mock AD failure"))
    @patch("apps.directory.identity_services.search_directory_employees", return_value=[])
    @patch("apps.directory.identity_services.get_directory_employee_by_id_personal", side_effect=DirectoryDatabaseError("mock HR failure"))
    def test_explicit_local_user_is_fallback_after_known_source_errors(
        self,
        find_by_id,
        search_rrhh,
        find_ad_user,
    ):
        user = self.create_user("identity-local-explicit", "explicit@example.test")

        identity = identity_services.resolve_institutional_identity(
            id_personal=user.id_personal,
            email=user.email,
            local_user=user,
        )

        self.assertEqual(identity["source"], "LOCAL")
        self.assertEqual(identity["email"], user.email)
        find_by_id.assert_called_once_with(user.id_personal)
        search_rrhh.assert_called_once_with(user.email, limit=20)
        find_ad_user.assert_called_once_with(user.email)

    @patch("apps.directory.identity_services.get_ad_user_by_email", return_value=None)
    @patch("apps.directory.identity_services.search_directory_employees", return_value=[])
    def test_local_user_is_found_by_case_insensitive_email(self, search_rrhh, find_ad_user):
        user = self.create_user("identity-local-email", "person@example.test")

        identity = identity_services.resolve_institutional_identity(
            email="PERSON@EXAMPLE.TEST",
        )

        self.assertEqual(identity["source"], "LOCAL")
        self.assertEqual(identity["id_personal"], user.id_personal)
        search_rrhh.assert_called_once_with("PERSON@EXAMPLE.TEST", limit=20)
        find_ad_user.assert_called_once_with("PERSON@EXAMPLE.TEST")

    def test_resolve_identity_for_user_passes_user_fields_to_resolver(self):
        user = self.create_user("identity-resolve-user", "user@example.test")

        with patch(
            "apps.directory.identity_services.resolve_institutional_identity",
            return_value={"source": "LOCAL"},
        ) as resolve:
            result = identity_services.resolve_identity_for_user(user)

        self.assertEqual(result, {"source": "LOCAL"})
        resolve.assert_called_once_with(
            id_personal=user.id_personal,
            email=user.email,
            local_user=user,
        )


class InstitutionalIdentitySearchTests(SimpleTestCase):
    @contextmanager
    def mock_local_users(self, users=()):
        with patch(
            "apps.directory.identity_services.User.objects.filter"
        ) as local_filter:
            local_filter.return_value.distinct.return_value = list(users)
            yield local_filter

    def test_search_validation(self):
        with (
            patch("apps.directory.identity_services.search_directory_employees") as rrhh,
            patch("apps.directory.identity_services.search_ad_users") as ad,
            self.mock_local_users() as local_filter,
        ):
            with self.assertRaises(ValueError):
                identity_services.search_institutional_identities(None)

            self.assertEqual(
                identity_services.search_institutional_identities("  A  "),
                [],
            )

            for limit in (0, 101, True, 1.5, "20"):
                with self.subTest(limit=limit):
                    with self.assertRaises(ValueError):
                        identity_services.search_institutional_identities(
                            "query",
                            limit=limit,
                        )

        rrhh.assert_not_called()
        ad.assert_not_called()
        local_filter.assert_not_called()

    def test_rrhh_and_ad_duplicate_by_case_insensitive_email(self):
        rrhh_employee = make_rrhh_employee(Mail="person@example.test")
        ad_user = make_ad_user(email="PERSON@EXAMPLE.TEST")

        with (
            patch(
                "apps.directory.identity_services.search_directory_employees",
                return_value=[rrhh_employee],
            ) as rrhh,
            patch(
                "apps.directory.identity_services.search_ad_users",
                return_value=[ad_user],
            ) as ad,
            self.mock_local_users(),
        ):
            identities = identity_services.search_institutional_identities("person")

        self.assertEqual([item["source"] for item in identities], ["RRHH"])
        rrhh.assert_called_once_with("person", limit=20)
        ad.assert_called_once_with("person", limit=20)

    def test_duplicate_id_personal_without_email_keeps_rrhh(self):
        rrhh_identity = {
            "source": "RRHH",
            "email": "",
            "id_personal": 4444,
            "username": "",
            "name": "RRHH",
            "employee_number": "",
        }
        ad_identity = {
            **rrhh_identity,
            "source": "ACTIVE_DIRECTORY",
            "name": "AD",
        }

        with (
            patch(
                "apps.directory.identity_services.search_directory_employees",
                return_value=[make_rrhh_employee()],
            ),
            patch(
                "apps.directory.identity_services.search_ad_users",
                return_value=[make_ad_user()],
            ),
            patch(
                "apps.directory.identity_services._normalize_rrhh_employee",
                return_value=rrhh_identity,
            ),
            patch(
                "apps.directory.identity_services._normalize_ad_user",
                return_value=ad_identity,
            ),
            self.mock_local_users(),
        ):
            identities = identity_services.search_institutional_identities("same")

        self.assertEqual(identities, [rrhh_identity])

    def test_duplicate_username_without_email_or_id_keeps_first_identity(self):
        rrhh_identity = {
            "source": "RRHH",
            "email": "",
            "id_personal": None,
            "username": "SharedUser",
            "name": "Primera fuente",
            "employee_number": "",
        }
        ad_identity = {
            **rrhh_identity,
            "source": "ACTIVE_DIRECTORY",
            "username": "shareduser",
            "name": "Segunda fuente",
        }

        with (
            patch(
                "apps.directory.identity_services.search_directory_employees",
                return_value=[make_rrhh_employee()],
            ),
            patch(
                "apps.directory.identity_services.search_ad_users",
                return_value=[make_ad_user()],
            ),
            patch(
                "apps.directory.identity_services._normalize_rrhh_employee",
                return_value=rrhh_identity,
            ),
            patch(
                "apps.directory.identity_services._normalize_ad_user",
                return_value=ad_identity,
            ),
            self.mock_local_users(),
        ):
            identities = identity_services.search_institutional_identities("same")

        self.assertEqual(identities, [rrhh_identity])

    def test_rrhh_error_continues_to_ad_and_returns_ad_identity(self):
        with (
            patch(
                "apps.directory.identity_services.search_directory_employees",
                side_effect=DirectoryDatabaseError("mock RRHH failure"),
            ) as rrhh,
            patch(
                "apps.directory.identity_services.search_ad_users",
                return_value=[make_ad_user()],
            ) as ad,
            self.mock_local_users(),
        ):
            identities = identity_services.search_institutional_identities("ad")

        self.assertEqual([item["source"] for item in identities], ["ACTIVE_DIRECTORY"])
        rrhh.assert_called_once_with("ad", limit=20)
        ad.assert_called_once_with("ad", limit=20)

    def test_unexpected_source_error_is_wrapped(self):
        with patch(
            "apps.directory.identity_services.search_directory_employees",
            side_effect=RuntimeError("unexpected failure"),
        ):
            with self.assertRaises(identity_services.InstitutionalIdentityError):
                identity_services.search_institutional_identities("unexpected")

    def test_final_limit_is_applied_after_collecting_sources(self):
        rrhh_employees = [
            make_rrhh_employee(
                IdPersonal=index,
                Mail=f"rrhh-{index}@example.test",
                NombresApellidos=f"RRHH {index}",
            )
            for index in range(1, 4)
        ]
        ad_users = [
            make_ad_user(
                email=f"ad-{index}@example.test",
                name=f"AD {index}",
            )
            for index in range(1, 4)
        ]

        with (
            patch(
                "apps.directory.identity_services.search_directory_employees",
                return_value=rrhh_employees,
            ) as rrhh,
            patch(
                "apps.directory.identity_services.search_ad_users",
                return_value=ad_users,
            ) as ad,
            self.mock_local_users(),
        ):
            identities = identity_services.search_institutional_identities(
                "source",
                limit=2,
            )

        self.assertEqual(len(identities), 2)
        self.assertEqual([item["name"] for item in identities], ["RRHH 1", "RRHH 2"])
        rrhh.assert_called_once_with("source", limit=2)
        ad.assert_called_once_with("source", limit=2)


class InstitutionalIdentityLocalSearchTests(TestCase):
    def create_user(self, username, email, **fields):
        user_fields = {
            "first_name": "BaseFirst",
            "last_name": "BaseLast",
            "employee_number": f"EMP-{username}",
            "id_personal": None,
        }
        user_fields.update(fields)
        return get_user_model().objects.create_user(
            username=username,
            email=email,
            password="test-password",
            **user_fields,
        )

    def search_with_external_sources_mocked(self, query, limit=20):
        with (
            patch(
                "apps.directory.identity_services.search_directory_employees",
                return_value=[],
            ),
            patch(
                "apps.directory.identity_services.search_ad_users",
                return_value=[],
            ),
        ):
            return identity_services.search_institutional_identities(
                query,
                limit=limit,
            )

    def test_source_priority_is_rrhh_then_ad_then_local(self):
        local_user = self.create_user(
            "priority-local-account",
            "priority-local@example.test",
        )

        with (
            patch(
                "apps.directory.identity_services.search_directory_employees",
                return_value=[make_rrhh_employee(Mail="priority-rrhh@example.test")],
            ) as rrhh,
            patch(
                "apps.directory.identity_services.search_ad_users",
                return_value=[make_ad_user(email="priority-ad@example.test")],
            ) as ad,
        ):
            identities = identity_services.search_institutional_identities("priority")

        self.assertEqual(
            [item["source"] for item in identities],
            ["RRHH", "ACTIVE_DIRECTORY", "LOCAL"],
        )
        self.assertEqual(identities[2]["email"], local_user.email)
        rrhh.assert_called_once_with("priority", limit=20)
        ad.assert_called_once_with("priority", limit=20)

    def test_ad_and_local_duplicate_by_email_keeps_ad(self):
        self.create_user("shared-local-account", "shared@example.test")

        with (
            patch(
                "apps.directory.identity_services.search_directory_employees",
                return_value=[],
            ),
            patch(
                "apps.directory.identity_services.search_ad_users",
                return_value=[make_ad_user(email="SHARED@EXAMPLE.TEST")],
            ),
        ):
            identities = identity_services.search_institutional_identities("shared")

        self.assertEqual([item["source"] for item in identities], ["ACTIVE_DIRECTORY"])

    def test_distinct_people_from_all_sources_are_retained(self):
        self.create_user("all-sources-local", "all-sources-local@example.test")

        with (
            patch(
                "apps.directory.identity_services.search_directory_employees",
                return_value=[make_rrhh_employee(Mail="all-sources-rrhh@example.test")],
            ),
            patch(
                "apps.directory.identity_services.search_ad_users",
                return_value=[make_ad_user(email="all-sources-ad@example.test")],
            ),
        ):
            identities = identity_services.search_institutional_identities(
                "all-sources"
            )

        self.assertEqual(
            [item["source"] for item in identities],
            ["RRHH", "ACTIVE_DIRECTORY", "LOCAL"],
        )

    def test_local_search_matches_text_fields(self):
        cases = (
            (
                self.create_user(
                    "email-account",
                    "needle-email@example.test",
                ),
                "needle-email",
            ),
            (
                self.create_user(
                    "needle-username",
                    "username-search@example.test",
                ),
                "needle-username",
            ),
            (
                self.create_user(
                    "first-name-account",
                    "first-name-search@example.test",
                    first_name="NeedleFirst",
                ),
                "needlefirst",
            ),
            (
                self.create_user(
                    "last-name-account",
                    "last-name-search@example.test",
                    last_name="NeedleLast",
                ),
                "needlelast",
            ),
            (
                self.create_user(
                    "employee-number-account",
                    "employee-number-search@example.test",
                    employee_number="NEEDLE-EMPLOYEE",
                ),
                "needle-employee",
            ),
        )

        for expected_user, query in cases:
            with self.subTest(field=query):
                identities = self.search_with_external_sources_mocked(query)
                self.assertEqual(len(identities), 1)
                self.assertEqual(identities[0]["email"], expected_user.email)
                self.assertEqual(identities[0]["source"], "LOCAL")

    def test_numeric_query_matches_local_id_personal(self):
        user = self.create_user(
            "numeric-personal-account",
            "numeric-personal@example.test",
            id_personal=987654321,
        )

        identities = self.search_with_external_sources_mocked("987654321")

        self.assertEqual(len(identities), 1)
        self.assertEqual(identities[0]["source"], "LOCAL")
        self.assertEqual(identities[0]["id_personal"], user.id_personal)

    def test_ad_error_continues_to_local_user(self):
        user = self.create_user("local-fallback-account", "local-fallback@example.test")

        with (
            patch(
                "apps.directory.identity_services.search_directory_employees",
                return_value=[],
            ),
            patch(
                "apps.directory.identity_services.search_ad_users",
                side_effect=ActiveDirectoryError("mock AD failure"),
            ),
        ):
            identities = identity_services.search_institutional_identities(
                "local-fallback"
            )

        self.assertEqual([item["source"] for item in identities], ["LOCAL"])
        self.assertEqual(identities[0]["email"], user.email)


class InstitutionalIdentityOrganizationalUnitTests(TestCase):
    def setUp(self):
        self.presidency = OrganizationalUnit.objects.create(
            name="Presidencia",
            code="TEST-PRES",
            unit_type=OrganizationalUnit.UnitType.PRESIDENCY,
        )
        self.directorate = OrganizationalUnit.objects.create(
            name="Dirección de Tecnología de la Información",
            code="TEST-DTI",
            unit_type=OrganizationalUnit.UnitType.DIRECTORATE,
            parent=self.presidency,
        )
        self.technical_unit = OrganizationalUnit.objects.create(
            name="Unidad Técnica",
            code="TEST-DTI-UT",
            unit_type=OrganizationalUnit.UnitType.UNIT,
            parent=self.directorate,
        )
        self.technical_department = OrganizationalUnit.objects.create(
            name="Dpto. Servicios Tecnológicos",
            code="TEST-DTI-UT-ST",
            unit_type=OrganizationalUnit.UnitType.DEPARTMENT,
            parent=self.technical_unit,
        )

    def create_assignment(self, organizational_unit, **identifiers):
        return InstitutionalIdentityAssignment.objects.create(
            organizational_unit=organizational_unit,
            **identifiers,
        )

    def test_identity_with_id_personal_is_enriched_with_unit_and_path(self):
        self.create_assignment(
            self.technical_department,
            id_personal=1234,
        )
        identity = {
            "id_personal": 1234,
            "email": "employee@example.test",
            "username": "employee",
        }

        enriched = identity_services._enrich_with_organizational_unit(identity)

        self.assertEqual(
            enriched["organizational_unit"],
            {
                "code": "TEST-DTI-UT-ST",
                "name": "Dpto. Servicios Tecnológicos",
                "type": OrganizationalUnit.UnitType.DEPARTMENT,
                "type_display": self.technical_department.get_unit_type_display(),
            },
        )
        path = enriched["organizational_path"]
        self.assertEqual(
            [item["code"] for item in path],
            ["TEST-PRES", "TEST-DTI", "TEST-DTI-UT", "TEST-DTI-UT-ST"],
        )
        self.assertEqual(
            [item["name"] for item in path],
            [
                "Presidencia",
                "Dirección de Tecnología de la Información",
                "Unidad Técnica",
                "Dpto. Servicios Tecnológicos",
            ],
        )
        for item in path:
            self.assertIn("type", item)
            self.assertIn("type_display", item)

    def test_id_personal_assignment_has_priority_over_email_and_username(self):
        id_assignment = self.create_assignment(
            self.directorate,
            id_personal=1234,
        )
        self.create_assignment(
            self.technical_unit,
            email="employee@example.test",
        )
        self.create_assignment(
            self.technical_department,
            username="employee",
        )

        enriched = identity_services._enrich_with_organizational_unit(
            {
                "id_personal": 1234,
                "email": "employee@example.test",
                "username": "employee",
            }
        )

        self.assertEqual(
            enriched["organizational_unit"]["code"],
            id_assignment.organizational_unit.code,
        )

    def test_email_assignment_enriches_identity_without_id_personal(self):
        self.create_assignment(
            self.technical_department,
            email="person.ad@example.test",
        )

        enriched = identity_services._enrich_with_organizational_unit(
            {
                "id_personal": None,
                "email": "PERSON.AD@example.test",
                "username": "person.ad",
            }
        )

        self.assertEqual(
            enriched["organizational_unit"]["code"],
            "TEST-DTI-UT-ST",
        )

    def test_username_assignment_enriches_identity_without_email_match(self):
        self.create_assignment(
            self.technical_unit,
            username="person.ad",
        )

        enriched = identity_services._enrich_with_organizational_unit(
            {
                "id_personal": None,
                "email": "unmatched@example.test",
                "username": "PERSON.AD",
            }
        )

        self.assertEqual(
            enriched["organizational_unit"]["code"],
            "TEST-DTI-UT",
        )

    def test_identity_without_assignment_gets_none_organizational_unit(self):
        identity = {
            "id_personal": 9999,
            "email": "unassigned@example.test",
            "username": "unassigned",
        }

        enriched = identity_services._enrich_with_organizational_unit(identity)

        self.assertEqual(enriched["id_personal"], 9999)
        self.assertEqual(enriched["email"], "unassigned@example.test")
        self.assertEqual(enriched["username"], "unassigned")
        self.assertIsNone(enriched["organizational_unit"])
        self.assertEqual(enriched["organizational_path"], [])

    def test_inactive_assignment_is_ignored(self):
        self.create_assignment(
            self.technical_department,
            id_personal=1234,
            is_active=False,
        )

        enriched = identity_services._enrich_with_organizational_unit(
            {"id_personal": 1234, "email": "", "username": ""}
        )

        self.assertIsNone(enriched["organizational_unit"])
        self.assertEqual(enriched["organizational_path"], [])

    def test_rrhh_identity_by_id_personal_includes_assignment(self):
        self.create_assignment(
            self.technical_department,
            id_personal=1234,
        )

        with patch(
            "apps.directory.identity_services.get_directory_employee_by_id_personal",
            return_value=make_rrhh_employee(IdPersonal=1234),
        ):
            identity = identity_services.resolve_institutional_identity(
                id_personal=1234,
            )

        self.assertEqual(identity["source"], "RRHH")
        self.assertEqual(
            identity["organizational_unit"]["code"],
            "TEST-DTI-UT-ST",
        )
        self.assertEqual(
            identity["organizational_path"][-1]["code"],
            "TEST-DTI-UT-ST",
        )

    def test_active_directory_identity_by_email_includes_assignment(self):
        self.create_assignment(
            self.technical_department,
            email="ad@example.test",
        )

        with (
            patch(
                "apps.directory.identity_services.search_directory_employees",
                return_value=[],
            ),
            patch(
                "apps.directory.identity_services.get_ad_user_by_email",
                return_value=make_ad_user(email="ad@example.test"),
            ),
        ):
            identity = identity_services.resolve_institutional_identity(
                email="ad@example.test",
            )

        self.assertEqual(identity["source"], "ACTIVE_DIRECTORY")
        self.assertEqual(
            identity["organizational_unit"]["code"],
            "TEST-DTI-UT-ST",
        )

    def test_local_user_identity_includes_email_assignment(self):
        user = get_user_model().objects.create_user(
            username="org-unit-local-user",
            email="org-unit-local@example.test",
            password="test-password",
        )
        self.create_assignment(
            self.technical_department,
            email=user.email,
        )

        with (
            patch(
                "apps.directory.identity_services.search_directory_employees",
                return_value=[],
            ),
            patch(
                "apps.directory.identity_services.get_ad_user_by_email",
                return_value=None,
            ),
        ):
            identity = identity_services.resolve_institutional_identity(
                email=user.email,
                local_user=user,
            )

        self.assertEqual(identity["source"], "LOCAL")
        self.assertEqual(
            identity["organizational_unit"]["code"],
            "TEST-DTI-UT-ST",
        )

    def test_identity_without_assignment_has_no_organizational_unit(self):
        with (
            patch(
                "apps.directory.identity_services.search_directory_employees",
                return_value=[],
            ),
            patch(
                "apps.directory.identity_services.get_ad_user_by_email",
                return_value=make_ad_user(
                    email="unassigned@example.test",
                ),
            ),
        ):
            identity = identity_services.resolve_institutional_identity(
                email="unassigned@example.test",
            )

        self.assertEqual(identity["source"], "ACTIVE_DIRECTORY")
        self.assertIsNone(identity["organizational_unit"])
        self.assertEqual(identity["organizational_path"], [])


class DirectoryEmployeeSearchApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="directory-api-user",
            email="directory-api-user@example.test",
            password="test-password",
        )
        self.url = reverse("directory:employee_search_api")

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            f"{reverse('login')}?next={self.url}",
        )

    @patch("apps.directory.views.search_institutional_identities")
    def test_short_query_returns_empty_list_without_searching(self, search):
        self.client.force_login(self.user)

        response = self.client.get(self.url, {"q": "A"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"employees": []})
        search.assert_not_called()

    @patch("apps.directory.views.search_institutional_identities")
    def test_search_returns_safe_employee_json(self, search):
        search.return_value = [
            {
                "source": "RRHH",
                "id_personal": 1234,
                "employee_number": "999",
                "name": "Funcionario Institucional",
                "first_name": "",
                "last_name": "",
                "location": "Ubicacion institucional",
                "phone": "0981000000",
                "email": "persona@example.test",
                "status": "Activo",
                "employment_type": "Permanente",
                "position": "Cargo institucional",
                "username": "",
                "is_active": True,
            }
        ]
        self.client.force_login(self.user)

        response = self.client.get(self.url, {"q": "Ariel"})

        self.assertEqual(response.status_code, 200)
        search.assert_called_once_with("Ariel", limit=20)
        employee = response.json()["employees"][0]
        self.assertEqual(
            set(employee),
            {
                "source",
                "id_personal",
                "employee_number",
                "name",
                "first_name",
                "last_name",
                "location",
                "phone",
                "email",
                "status",
                "employment_type",
                "position",
                "username",
                "is_active",
                "organizational_unit",
                "organizational_path",
            },
        )
        self.assertEqual(employee["source"], "RRHH")
        self.assertEqual(employee["id_personal"], 1234)
        self.assertEqual(employee["employee_number"], "999")
        self.assertEqual(employee["name"], "Funcionario Institucional")
        self.assertIs(employee["is_active"], True)
        self.assertIsNone(employee["organizational_unit"])
        self.assertEqual(employee["organizational_path"], [])
        self.assertNotIn("DesvinculacionFecha", employee)

    @patch("apps.directory.views.search_institutional_identities")
    def test_search_error_returns_service_unavailable(self, search):
        search.side_effect = identity_services.InstitutionalIdentityError(
            "mock failure"
        )
        self.client.force_login(self.user)

        response = self.client.get(self.url, {"q": "Ariel"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {
                "employees": [],
                "error": "No fue posible consultar el Directorio Institucional.",
            },
        )


@override_settings(
    STORAGES={
        **settings.STORAGES,
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    },
)
class DirectoryHomeViewTests(TestCase):
    def setUp(self):
        # The home view loads the full RR.HH. directory even for GET searches.
        # Keep these rendering tests independent of the external SQL server.
        directory_patch = patch(
            "apps.directory.views.get_institutional_directory",
            return_value=[
                {"name": "Ana de prueba", "employment_type": "Permanente"},
                {"name": "Zoe de prueba", "employment_type": "Contratado"},
            ],
        )
        self.directory = directory_patch.start()
        self.addCleanup(directory_patch.stop)
        self.user = get_user_model().objects.create_user(
            username="directory-user",
            email="directory-user@example.com",
            password="test-password",
        )

    @patch("apps.directory.views.search_institutional_identities")
    def test_authenticated_user_can_access_directory_home(self, search):
        self.client.force_login(self.user)

        response = self.client.get(reverse("directory:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Directorio Institucional")
        self.assertEqual(response.context["employees"], self.directory.return_value)
        self.directory.assert_called_once_with()
        search.assert_not_called()

    @patch("apps.directory.views.search_institutional_identities")
    def test_directory_home_displays_mocked_employees(self, search):
        search.return_value = [
            {
                "source": "RRHH",
                "id_personal": 2002,
                "employee_number": "TEST-002",
                "name": "Persona de prueba",
                "first_name": "",
                "last_name": "",
                "location": "Sede de prueba",
                "phone": "000000001",
                "email": "persona@example.invalid",
                "status": "Activo",
                "employment_type": "Permanente",
                "position": "Cargo de prueba",
                "username": "",
                "is_active": True,
            }
        ]
        self.client.force_login(self.user)

        response = self.client.get(reverse("directory:home"), {"q": "Persona"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Persona de prueba")
        self.assertContains(response, "TEST-002")
        self.assertContains(response, "RR.HH.")
        self.assertEqual(response.context["employees"], search.return_value)
        self.assertEqual(
            response.context["directory_kpis"],
            {"total": 2, "permanent": 1, "contracted": 1, "outsourced": 0, "other": 0},
        )
        self.directory.assert_called_once_with()
        search.assert_called_once_with("Persona", limit=100)

    @patch("apps.directory.views.search_institutional_identities", return_value=[])
    def test_directory_home_preserves_search_query(self, search):
        self.client.force_login(self.user)

        response = self.client.get(reverse("directory:home"), {"q": "  Ana  "})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["search_query"], "Ana")
        search.assert_called_once_with("Ana", limit=100)

    @patch("apps.directory.views.search_institutional_identities")
    def test_institutional_identity_error_renders_friendly_message(self, search):
        search.side_effect = identity_services.InstitutionalIdentityError(
            "technical secret details"
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("directory:home"), {"q": "Ariel"})

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
