from copy import deepcopy
from django.test import SimpleTestCase
from .identity_services import _merge_linked_identities


class MergeMissingIdentifiersTests(SimpleTestCase):
    def records(self, source="RRHH"):
        local = {"source": "LOCAL", "email": "persona@example.test", "username": "persona", "rrhh_id": 1,
            "local_user_id": "local-id", "_locator": {"source": "LOCAL", "id": "local-id"},
            "document_number": "123", "employee_number": "001"}
        institutional = {"source": source, "email": "persona@example.test", "username": "persona", "rrhh_id": 1,
            "_locator": {"source": source, "id": 1}, "is_active": True}
        return [local, institutional]

    def test_missing_institutional_identifiers_do_not_raise_for_rrhh_or_ad(self):
        for source in ("RRHH", "ACTIVE_DIRECTORY"):
            records = self.records(source)
            before = deepcopy(records)
            with self.subTest(source=source):
                result = _merge_linked_identities(records)
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0]["local_user_id"], "local-id")
                self.assertEqual(records, before)

    def test_missing_local_identifiers_do_not_raise(self):
        records = self.records()
        for key in ("document_number", "employee_number"):
            records[0].pop(key)
            records[1][key] = "123"
        self.assertEqual(len(_merge_linked_identities(records)), 1)

    def test_present_conflicting_identifiers_still_prevent_merge(self):
        for key in ("document_number", "employee_number"):
            records = self.records()
            records[1][key] = "conflicting"
            with self.subTest(key=key):
                self.assertEqual(_merge_linked_identities(records), records)

    def test_email_alone_and_duplicate_sources_still_do_not_merge(self):
        records = self.records("ACTIVE_DIRECTORY")
        records[1]["username"] = "another-person"
        self.assertEqual(_merge_linked_identities(records), records)
        records = self.records()
        records.append(dict(records[1], _locator={"source": "RRHH", "id": 2}))
        self.assertEqual(_merge_linked_identities(records), records)
