from io import StringIO
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.printing.models import PrintingDevice
from apps.printing.printer_import import START_NOTES, END_NOTES


class ImportedPrinterOwnershipTests(TestCase):
    def imported(self, **kwargs):
        return PrintingDevice.objects.create(notes=f"{START_NOTES}\nDependencia: DTI\n{END_NOTES}", **kwargs)

    def run_command(self, **options):
        output = StringIO()
        call_command("fix_imported_printer_ownership", stdout=output, **options)
        return output.getvalue()

    def test_dry_run_reports_proposal_without_writes(self):
        device = self.imported()
        with CaptureQueriesContext(connection) as queries:
            output = self.run_command(dry_run=True)
        self.assertIn("ACTUALIZADO=1", output)
        self.assertIn("Propio -> Alquilado", output)
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))
        device.refresh_from_db()
        self.assertEqual(device.ownership_type, "OWNED")

    def test_real_run_only_updates_ownership_and_is_idempotent(self):
        device = self.imported(photocopier_id="55/BK", ip_address="192.0.2.1")
        manual = PrintingDevice.objects.create(notes="Notas manuales")
        before = PrintingDevice.objects.values().get(pk=device.pk)
        self.assertIn("ACTUALIZADO=1", self.run_command())
        after = PrintingDevice.objects.values().get(pk=device.pk)
        self.assertEqual(after.pop("ownership_type"), "RENTED")
        before.pop("ownership_type")
        self.assertEqual(after, before)
        self.assertIn("SIN CAMBIOS=1", self.run_command())
        manual.refresh_from_db()
        self.assertEqual(manual.ownership_type, "OWNED")

    def test_incompatible_and_invalid_blocks_are_not_overwritten(self):
        for ownership in ["LEASING", "LOANED", "UNKNOWN"]:
            self.imported(ownership_type=ownership)
        PrintingDevice.objects.create(notes=START_NOTES)
        self.assertIn("REVISAR=4", self.run_command())
        self.assertEqual(PrintingDevice.objects.filter(ownership_type="RENTED").count(), 0)

    def test_rollback_on_error(self):
        self.imported()
        self.imported()
        original = PrintingDevice.save
        calls = []
        def failing_save(device, *args, **kwargs):
            calls.append(device.pk)
            if len(calls) == 2:
                raise RuntimeError("test failure")
            return original(device, *args, **kwargs)
        with patch.object(PrintingDevice, "save", failing_save), self.assertRaises(CommandError):
            self.run_command()
        self.assertEqual(PrintingDevice.objects.filter(ownership_type="OWNED").count(), 2)
