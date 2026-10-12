from io import StringIO
from unittest.mock import patch

from django.contrib import admin
from django.core.management import call_command, CommandError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import Branch
from apps.inventory.models import OrganizationalLocation
from apps.printing.models import PrintingDevice
from apps.printing.printer_import import START_NOTES, END_NOTES, PROVISIONAL_LOCATION_CODE


class AssignPrinterLocationsTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code="PLANTA-VILLA-ELISA", name="Planta Villa Elisa")
        self.other = Branch.objects.create(code="OFICINA-CENTRAL", name="Oficina Central")

    def location(self, name="Dpto. Comercial", branch=None, code="REAL", **kwargs):
        return OrganizationalLocation.objects.create(branch=branch or self.branch, code=code,
            name=name, location_type=OrganizationalLocation.LocationType.OFFICE, **kwargs)

    def device(self, dependency="Dpto. Comercial", sede="Villa Elisa", **kwargs):
        return PrintingDevice.objects.create(branch=self.branch,
            notes=f"Manual\n{START_NOTES}\nSede: {sede}\nDependencia: {dependency}\n{END_NOTES}", **kwargs)

    def run_command(self, **kwargs):
        output = StringIO()
        call_command("assign_printer_locations", stdout=output, **kwargs)
        return output.getvalue()

    def test_manual_location_exact_assigns_only_fk_and_is_idempotent(self):
        candidate = self.location()
        device = self.device(ip_address="192.0.2.1", ownership_type="RENTED",
            responsible_identity={"name": "Persona Institucional"})
        before = PrintingDevice.objects.values().get(pk=device.pk)
        self.assertIn("ACTUALIZADO=1", self.run_command())
        after = PrintingDevice.objects.values().get(pk=device.pk)
        self.assertEqual(after.pop("organizational_location_id"), candidate.pk)
        before.pop("organizational_location_id")
        self.assertEqual(after, before)
        self.assertIn("SIN CAMBIOS=1", self.run_command())

    def test_dry_run_has_no_writes(self):
        self.location()
        device = self.device()
        with CaptureQueriesContext(connection) as queries:
            self.assertIn("ACTUALIZADO=1", self.run_command(dry_run=True))
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE")) for q in queries))
        self.assertFalse(any("responsible_identity" in q["sql"] for q in queries))
        device.refresh_from_db()
        self.assertIsNone(device.organizational_location_id)

    def test_absent_or_other_branch_or_inactive_location_pending(self):
        device = self.device()
        self.assertIn("PENDIENTE=1", self.run_command())
        self.location(branch=self.other)
        self.assertIn("PENDIENTE=1", self.run_command())
        self.location(is_active=False)
        self.assertIn("PENDIENTE=1", self.run_command())
        device.refresh_from_db()
        self.assertIsNone(device.organizational_location_id)

    def test_multiple_normalized_matches_are_reviewed(self):
        self.device("Dirección Jurídica")
        self.location("Direccion Juridica")
        self.location(" DIRECCION   JURÍDICA ", code="SECOND")
        self.assertIn("REVISAR=1", self.run_command())

    def test_real_different_location_is_never_overwritten(self):
        current = self.location("Secretaría General")
        self.location(code="TARGET")
        device = self.device(organizational_location=current)
        self.assertIn("REVISAR=1", self.run_command())
        device.refresh_from_db()
        self.assertEqual(device.organizational_location_id, current.pk)

    def test_provisional_location_replaced_with_normalized_exact_match(self):
        provisional = self.location("Ubicación pendiente de verificar - Planta Villa Elisa", code=PROVISIONAL_LOCATION_CODE)
        target = self.location("Dirección Jurídica")
        device = self.device("  DIRECCION   JURIDICA ", organizational_location=provisional)
        self.assertIn("ACTUALIZADO=1", self.run_command())
        device.refresh_from_db()
        self.assertEqual(device.organizational_location_id, target.pk)

    def test_possible_abbreviation_not_applied(self):
        self.location("Departamento Agrícola")
        device = self.device("Dpto. Agricola")
        self.assertIn("REVISAR=1", self.run_command())
        device.refresh_from_db()
        self.assertIsNone(device.organizational_location_id)

    def test_note_branch_mismatch_or_foreign_current_location_reviewed(self):
        self.location()
        self.device(sede="Centro")
        self.device(organizational_location=self.location(branch=self.other))
        self.assertIn("REVISAR=2", self.run_command())

    def test_non_imported_device_untouched_and_no_locations_created(self):
        manual = PrintingDevice.objects.create(branch=self.branch, notes="Manual")
        self.device()
        count = OrganizationalLocation.objects.count()
        self.assertIn("Total importados=1", self.run_command())
        self.assertEqual(OrganizationalLocation.objects.count(), count)
        manual.refresh_from_db()
        self.assertIsNone(manual.organizational_location_id)

    def test_real_run_is_atomic_and_rolls_back_on_save_error(self):
        self.location()
        self.device()
        self.device()
        original = PrintingDevice.save
        calls = []
        def failing_save(device, *args, **kwargs):
            self.assertTrue(connection.in_atomic_block)
            calls.append(device.pk)
            if len(calls) == 2:
                raise RuntimeError("test rollback")
            return original(device, *args, **kwargs)
        with patch.object(PrintingDevice, "save", failing_save), self.assertRaises(CommandError):
            self.run_command()
        self.assertEqual(len(calls), 2)
        self.assertFalse(PrintingDevice.objects.exclude(organizational_location=None).exists())

    def test_invalid_block_aborts_real_run_before_writes(self):
        self.location()
        self.device()
        PrintingDevice.objects.create(branch=self.branch, notes=START_NOTES)
        with self.assertRaises(CommandError):
            self.run_command()
        self.assertFalse(PrintingDevice.objects.exclude(organizational_location=None).exists())

    def test_location_admin_supports_manual_management(self):
        location_admin = admin.site._registry[OrganizationalLocation]
        self.assertTrue({"branch", "name", "is_active"}.issubset(location_admin.list_display))
