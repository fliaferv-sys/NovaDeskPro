from io import StringIO
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.db import IntegrityError, connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import Branch, User
from apps.inventory.models import Asset, OrganizationalLocation
from apps.printing.models import PrintingContract, PrintingDevice, PrintingDeviceNetworkDetection

COMMAND = "apps.printing.management.commands.prepare_printing_master_data"


class PreparePrintingMasterDataTests(TestCase):
    def run_command(self, **kwargs):
        output = StringIO()
        call_command("prepare_printing_master_data", stdout=output, **kwargs)
        return output.getvalue()

    def test_empty_database_creates_only_approved_masters(self):
        self.assertIn("NUEVO=6", self.run_command())
        self.assertEqual(Branch.objects.count(), 3)
        self.assertEqual(OrganizationalLocation.objects.count(), 3)
        for model in (User, Asset, PrintingContract, PrintingDevice, PrintingDeviceNetworkDetection):
            self.assertEqual(model.objects.count(), 0)

    def test_existing_villa_elisa_is_reused_without_updates(self):
        branch = Branch.objects.create(code="PLANTA-VILLA-ELISA", name="Sede Villa Elisa", city="Ciudad existente")
        original = Branch.objects.values().get(pk=branch.pk)
        self.assertIn("NUEVO=5 | REUTILIZADO=1", self.run_command())
        self.assertEqual(Branch.objects.values().get(pk=branch.pk), original)

    def test_repeat_is_idempotent_with_no_writes(self):
        self.run_command()
        before = list(OrganizationalLocation.objects.values())
        with CaptureQueriesContext(connection) as queries:
            self.assertIn("NUEVO=0 | REUTILIZADO=6", self.run_command())
        self.assertEqual(list(OrganizationalLocation.objects.values()), before)
        self.assertEqual(Branch.objects.count(), 3)
        self.assert_no_writes(queries)

    def assert_no_writes(self, queries):
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))

    def test_dry_run_empty_database_has_no_writes(self):
        with CaptureQueriesContext(connection) as queries:
            self.assertIn("NUEVO=6", self.run_command(dry_run=True))
        self.assert_no_writes(queries)
        self.assertEqual(Branch.objects.count(), 0)
        self.assertEqual(OrganizationalLocation.objects.count(), 0)

    def test_conflicting_branch_code_aborts_without_overwriting(self):
        branch = Branch.objects.create(code="OFICINA-CENTRAL", name="Otra sede")
        for dry in (True, False):
            with self.subTest(dry=dry), self.assertRaisesMessage(CommandError, "Conflicto de sede"):
                self.run_command(dry_run=dry)
        branch.refresh_from_db()
        self.assertEqual(branch.name, "Otra sede")
        self.assertEqual(Branch.objects.count(), 1)
        self.assertEqual(OrganizationalLocation.objects.count(), 0)

    def test_locations_belong_to_their_branch(self):
        self.run_command()
        for location in OrganizationalLocation.objects.select_related("branch"):
            self.assertEqual(location.code, "UBICACION-PENDIENTE")
            self.assertEqual(location.name, "Ubicaci\u00f3n pendiente de verificar - " + location.branch.name)
            self.assertTrue(location.is_active)
            self.assertIsNone(location.parent_id)

    def test_rollback_after_save_error(self):
        save = OrganizationalLocation.save
        count = 0
        def failing_save(obj, *args, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                raise IntegrityError("Simulated critical failure")
            return save(obj, *args, **kwargs)
        with patch.object(OrganizationalLocation, "save", failing_save):
            with self.assertRaisesMessage(CommandError, "rollback"):
                self.run_command()
        self.assertEqual(Branch.objects.count(), 0)
        self.assertEqual(OrganizationalLocation.objects.count(), 0)

    def test_incompatible_existing_location_aborts(self):
        branch = Branch.objects.create(code="PLANTA-VILLA-ELISA", name="Planta Villa Elisa")
        location = OrganizationalLocation.objects.create(branch=branch, code="UBICACION-PENDIENTE", name="Otra ubicacion")
        with self.assertRaisesMessage(CommandError, "Conflicto de ubicacion"):
            self.run_command()
        location.refresh_from_db()
        self.assertEqual(location.name, "Otra ubicacion")
        self.assertEqual(Branch.objects.count(), 1)

    def test_inactive_or_wrong_type_branch_is_not_changed(self):
        for field, value in (("is_active", False), ("branch_type", Branch.BranchType.OTHER)):
            with self.subTest(field=field):
                branch = Branch.objects.create(code="PLANTA-VILLA-ELISA", name="Planta Villa Elisa", **{field: value})
                with self.assertRaisesMessage(CommandError, "Conflicto de sede"):
                    self.run_command()
                branch.refresh_from_db()
                self.assertEqual(getattr(branch, field), value)
                branch.delete()

    def test_central_headquarters_type_is_compatible(self):
        Branch.objects.create(code="OFICINA-CENTRAL", name="Oficina Central", branch_type=Branch.BranchType.HEADQUARTERS)
        self.assertIn("REUTILIZADO=1", self.run_command())
        self.assertEqual(Branch.objects.get(code="OFICINA-CENTRAL").branch_type, Branch.BranchType.HEADQUARTERS)

    def test_reserved_location_name_with_another_code_is_conflict(self):
        branch = Branch.objects.create(code="PLANTA-VILLA-ELISA", name="Planta Villa Elisa")
        OrganizationalLocation.objects.create(branch=branch, code="OTHER", name="Ubicaci\u00f3n pendiente de verificar - Planta Villa Elisa")
        with self.assertRaisesMessage(CommandError, "Conflicto de ubicacion"):
            self.run_command(dry_run=True)
        self.assertEqual(OrganizationalLocation.objects.count(), 1)
