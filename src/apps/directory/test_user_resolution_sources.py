from unittest.mock import patch

from django.test import SimpleTestCase

from .services import search_directory_employees_batch, _DIRECTORY_COLUMNS
from .ad_services import search_ad_users_batch, ActiveDirectoryError


class UserResolutionSourceBatchTests(SimpleTestCase):
    @patch("apps.directory.services._open_directory_connection")
    def test_rrhh_batch_is_parameterized_and_keeps_duplicate_source_rows(self, open_connection):
        cursor = open_connection.return_value.cursor.return_value
        row = tuple({"IdPersonal": 41, "LegajoNro": "1173", "Ubicacion": "Dir.Tecno. de la Informac."}.get(column) for column in _DIRECTORY_COLUMNS)
        cursor.fetchall.return_value = [(0, *row), (0, *row), (2, *row)]
        terms = [("41", "rrhh_id"), ("1173", "employee_number"), ("Ariel%_", "name")]
        result = search_directory_employees_batch(terms)
        sql, *parameters = cursor.execute.call_args.args
        self.assertEqual(sql.count("TOP (100)"), 3)
        self.assertEqual(sql.count("UNION ALL"), 2)
        self.assertNotIn("Ariel", sql)
        self.assertEqual(parameters, ["41", "1173", "%Ariel[%][_]%"])
        self.assertEqual(len(result[terms[0]]), 2)
        self.assertEqual(result[terms[1]], [])
        self.assertEqual(result[terms[2]][0]["Ubicacion"], "Dir.Tecno. de la Informac.")
        open_connection.assert_called_once()
        open_connection.return_value.close.assert_called_once()

    @patch("apps.directory.services._open_directory_connection")
    def test_rrhh_large_list_uses_chunks_on_one_connection(self, open_connection):
        open_connection.return_value.cursor.return_value.fetchall.return_value = []
        terms = [(str(number), "rrhh_id") for number in range(1, 82)]
        self.assertEqual(search_directory_employees_batch(terms), {term: [] for term in terms})
        self.assertEqual(open_connection.return_value.cursor.return_value.execute.call_count, 3)
        open_connection.assert_called_once()

    @patch("apps.directory.services._open_directory_connection")
    def test_empty_batch_never_connects(self, open_connection):
        self.assertEqual(search_directory_employees_batch([]), {})
        open_connection.assert_not_called()

    @patch("apps.directory.ad_services._search_ad_filter")
    def test_ad_batch_partitions_both_account_keys_and_preserves_ambiguity(self, search):
        first = {"email": "ariel@petropar.gov.py", "username": "ariel"}
        second = {"email": first["email"], "username": "ariel2"}
        search.return_value = [first, second]
        terms = [(first["email"], "email"), ("ariel", "username")]
        result = search_ad_users_batch(terms)
        self.assertEqual(result[terms[0]], [first, second])
        self.assertEqual(result[terms[1]], [first])
        search.assert_called_once()

    @patch("apps.directory.ad_services._search_ad_filter")
    def test_saturated_ad_batch_is_incomplete_not_a_unique_or_empty_match(self, search):
        search.return_value = [{"email": "a@petropar.gov.py", "username": "a"}] * 100
        terms = [("a@petropar.gov.py", "email")]
        self.assertIsInstance(search_ad_users_batch(terms)[terms[0]], ActiveDirectoryError)

    @patch("apps.directory.ad_services._search_ad_filter")
    def test_saturated_shared_batch_does_not_hide_another_unique_account(self, search):
        duplicate = {"email": "a@petropar.gov.py", "username": "a"}
        unique = {"email": "b@petropar.gov.py", "username": "b"}
        search.side_effect = [[duplicate] * 100, [duplicate] * 100, [unique]]
        terms = [(duplicate["email"], "email"), (unique["email"], "email")]
        result = search_ad_users_batch(terms)
        self.assertIsInstance(result[terms[0]], ActiveDirectoryError)
        self.assertEqual(result[terms[1]], [unique])
        self.assertEqual(search.call_count, 3)
