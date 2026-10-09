from io import StringIO
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.db import IntegrityError, connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.printing.models import PrintingDevice
from apps.printing.printer_import import START_NOTES, END_NOTES
from apps.printing.printer_ids import origin_id


class MigratePrinterIdsFromNotesTests(TestCase):
    def notes(self, identifier="1"):
        return "ID origen: MANUAL\n" + START_NOTES + "\nN\u00b0 origen: 99\nID origen: " + identifier + "\nDependencia: Sector\nResponsable: Persona\nIP actual: 192.0.2.1\n" + END_NOTES + "\nNota manual final"

    def run_command(self, **options):
        output = StringIO()
        call_command("migrate_printer_ids_from_notes", stdout=output, **options)
        return output.getvalue()

    def test_migrates_valid_id_and_only_changes_photocopier_id(self):
        device = PrintingDevice.objects.create(notes=self.notes("001"), serial_number="SER-1", ip_address="192.0.2.3")
        before = PrintingDevice.objects.values().get(pk=device.pk)
        self.assertIn("ACTUALIZADO=1", self.run_command())
        after = PrintingDevice.objects.values().get(pk=device.pk)
        self.assertEqual(after.pop("photocopier_id"), "001")
        before.pop("photocopier_id")
        self.assertEqual(after, before)

    def test_dry_run_no_writes(self):
        device = PrintingDevice.objects.create(notes=self.notes())
        with CaptureQueriesContext(connection) as queries:
            self.assertIn("Impresoras que recibirian ID=1", self.run_command(dry_run=True))
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))
        device.refresh_from_db()
        self.assertIsNone(device.photocopier_id)

    def test_second_run_has_no_updates(self):
        PrintingDevice.objects.create(notes=self.notes())
        self.run_command()
        with CaptureQueriesContext(connection) as queries:
            self.assertIn("SIN CAMBIOS=1", self.run_command())
        self.assertFalse(any(q["sql"].lstrip().upper().startswith("UPDATE") for q in queries))

    def test_existing_matching_id_is_unchanged(self):
        PrintingDevice.objects.create(notes=self.notes(), photocopier_id="1")
        self.assertIn("ACTUALIZADO=0 | SIN CAMBIOS=1", self.run_command())

    def test_existing_different_id_is_not_overwritten(self):
        device = PrintingDevice.objects.create(notes=self.notes(), photocopier_id="OTHER")
        output = self.run_command()
        self.assertIn("REVISAR=1", output)
        self.assertIn("existente distinto", output)
        device.refresh_from_db()
        self.assertEqual(device.photocopier_id, "OTHER")

    def test_id_used_by_non_imported_printer_is_reviewed(self):
        PrintingDevice.objects.create(photocopier_id="1", notes="Solo nota manual")
        device = PrintingDevice.objects.create(notes=self.notes())
        output = self.run_command()
        self.assertIn("REVISAR=1", output)
        self.assertIn("ya usado por otra impresora", output)
        self.assertIn("Total impresoras con bloque importado=1", output)
        device.refresh_from_db()
        self.assertIsNone(device.photocopier_id)

    def test_duplicate_candidates_all_reviewed_before_saving(self):
        for value in ("ID-1", "id-1"):
            PrintingDevice.objects.create(notes=self.notes(value))
        output = self.run_command()
        self.assertIn("REVISAR=2", output)
        self.assertIn("duplicado en el lote", output)
        self.assertEqual(PrintingDevice.objects.filter(photocopier_id__isnull=True).count(), 2)

    def test_missing_and_empty_id_never_use_origin_row_number(self):
        for notes in (self.notes(""), START_NOTES + "\nN\u00b0 origen: 88\n" + END_NOTES):
            with self.subTest(notes=notes):
                device = PrintingDevice.objects.create(notes=notes)
                self.assertIn("SIN CAMBIOS=1", self.run_command())
                device.refresh_from_db()
                self.assertIsNone(device.photocopier_id)
                device.delete()

    def test_invalid_ids_require_review(self):
        for value in ("S/N", "N/A", "0", "000", "X" * 51, "ID WITH SPACE", "-1", "1.5", "<bad>"):
            with self.subTest(value=value):
                device = PrintingDevice.objects.create(notes=self.notes(value))
                self.assertIn("REVISAR=1", self.run_command())
                device.refresh_from_db()
                self.assertIsNone(device.photocopier_id)
                device.delete()

    def test_without_imported_block_is_not_processed(self):
        PrintingDevice.objects.create(notes="ID origen: 1")
        self.assertIn("Total impresoras con bloque importado=0", self.run_command())
        self.assertIsNone(PrintingDevice.objects.get().photocopier_id)

    def test_multiple_id_lines_require_review(self):
        PrintingDevice.objects.create(notes=self.notes("1\nID origen: 2"))
        self.assertIn("REVISAR=1", self.run_command())
        self.assertIsNone(PrintingDevice.objects.get().photocopier_id)

    def test_malformed_block_aborts_all_changes(self):
        good = PrintingDevice.objects.create(notes=self.notes())
        PrintingDevice.objects.create(notes=START_NOTES + "\nID origen: 2")
        with self.assertRaisesMessage(CommandError, "ERROR"):
            self.run_command()
        good.refresh_from_db()
        self.assertIsNone(good.photocopier_id)

    def test_critical_save_error_rolls_back_batch(self):
        for value in ("1", "2"):
            PrintingDevice.objects.create(notes=self.notes(value))
        original_save = PrintingDevice.save
        count = 0
        def failing_save(device, *args, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                raise IntegrityError("Synthetic concurrent unique collision")
            return original_save(device, *args, **kwargs)
        with patch.object(PrintingDevice, "save", failing_save):
            with self.assertRaises(CommandError):
                self.run_command()
        self.assertEqual(PrintingDevice.objects.filter(photocopier_id__isnull=True).count(), 2)

    def test_raw_excel_integer_is_valid_but_other_types_not_coerced(self):
        self.assertEqual(origin_id(1), "1")
        self.assertEqual(origin_id(" 001 "), "001")
        for value in (True, 1.5, 1.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                origin_id(value)

    def test_slash_id_is_valid_and_preserved_exactly(self):
        self.assertEqual(origin_id("55/BK"), "55/BK")
        device = PrintingDevice.objects.create(notes=self.notes("55/BK"))
        self.assertIn("ACTUALIZADO=1", self.run_command())
        device.refresh_from_db()
        self.assertEqual(device.photocopier_id, "55/BK")
        self.assertIn("SIN CAMBIOS=1", self.run_command())

    def test_slash_duplicates_in_batch_are_reviewed(self):
        for value in ("55/BK", "55/bk"):
            PrintingDevice.objects.create(notes=self.notes(value))
        self.assertIn("REVISAR=2", self.run_command())
        self.assertEqual(PrintingDevice.objects.filter(photocopier_id__isnull=True).count(), 2)

    def test_slash_existing_duplicate_is_reviewed(self):
        PrintingDevice.objects.create(photocopier_id="55/bk")
        device = PrintingDevice.objects.create(notes=self.notes("55/BK"))
        self.assertIn("REVISAR=1", self.run_command())
        device.refresh_from_db()
        self.assertIsNone(device.photocopier_id)

    def test_invalid_markers_with_slash_remain_invalid(self):
        for value in ("S/N", "s/n", "N/A", "n/a", "55 /BK", "55/ BK", "55/BK" + "X" * 46):
            with self.subTest(value=value), self.assertRaises(ValueError):
                origin_id(value)
