from io import StringIO
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.db import IntegrityError, connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.printing.models import PrintingDevice
from apps.printing.printer_import import START_NOTES, END_NOTES
from apps.printing.management.commands.clean_printer_import_contract_notes import cleaned_notes, TARGET_LINE


class CleanPrinterImportContractNotesTests(TestCase):
    def run_command(self, **options):
        output = StringIO()
        call_command("clean_printer_import_contract_notes", stdout=output, **options)
        return output.getvalue()

    def notes(self):
        return "\n".join(("Nota manual: " + TARGET_LINE, START_NOTES,
            "Dependencia:  Sector   original ", "Responsable: Persona original",
            "IP anterior: 192.0.2.1", "IP actual: 192.0.2.2", TARGET_LINE,
            "Observaciones: contrato pendiente de confirmar", END_NOTES,
            "Otra nota manual " + TARGET_LINE))

    def test_removes_only_contract_and_preserves_every_other_character(self):
        notes = self.notes()
        device = PrintingDevice.objects.create(serial_number="CLEAN-1", notes=notes)
        output = self.run_command()
        self.assertIn("ACTUALIZADO=1", output)
        device.refresh_from_db()
        expected = notes.replace("\n" + TARGET_LINE + "\n", "\n")
        self.assertEqual(device.notes, expected)
        for label in ("Dependencia", "Responsable", "IP anterior", "IP actual"):
            self.assertIn(label + ":", device.notes)
        self.assertIn("Nota manual: " + TARGET_LINE, device.notes)
        self.assertIn("Otra nota manual " + TARGET_LINE, device.notes)

    def test_dry_run_does_not_write(self):
        device = PrintingDevice.objects.create(notes=self.notes())
        before = PrintingDevice.objects.values().get(pk=device.pk)
        with CaptureQueriesContext(connection) as queries:
            output = self.run_command(dry_run=True)
        self.assertIn("Impresoras que serian limpiadas=1", output)
        self.assertEqual(PrintingDevice.objects.values().get(pk=device.pk), before)
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))

    def test_second_execution_has_no_changes_or_writes(self):
        device = PrintingDevice.objects.create(notes=self.notes())
        self.run_command()
        before = PrintingDevice.objects.values().get(pk=device.pk)
        with CaptureQueriesContext(connection) as queries:
            output = self.run_command()
        self.assertIn("ACTUALIZADO=0 | SIN CAMBIOS=1", output)
        self.assertEqual(PrintingDevice.objects.values().get(pk=device.pk), before)
        self.assertFalse(any(q["sql"].lstrip().upper().startswith("UPDATE") for q in queries))

    def test_absent_contract_is_unchanged(self):
        notes = START_NOTES + "\nDependencia: Sector\n" + END_NOTES
        device = PrintingDevice.objects.create(notes=notes)
        self.assertIn("SIN CAMBIOS=1", self.run_command())
        device.refresh_from_db()
        self.assertEqual(device.notes, notes)

    def test_manual_contract_without_block_is_unchanged(self):
        self.assertEqual(cleaned_notes(TARGET_LINE), TARGET_LINE)

    def test_other_contract_or_contract_in_observation_is_preserved(self):
        notes = START_NOTES + "\nContrato: OTRO\nObservaciones: " + TARGET_LINE + "\n" + END_NOTES
        self.assertEqual(cleaned_notes(notes), notes)

    def test_crlf_and_whitespace_preserved_except_target_line(self):
        notes = START_NOTES + "\r\nDependencia:  Sector \r\n  " + TARGET_LINE + "  \r\n" + END_NOTES
        self.assertEqual(cleaned_notes(notes), START_NOTES + "\r\nDependencia:  Sector \r\n" + END_NOTES)

    def test_bad_block_aborts_all_real_changes(self):
        device = PrintingDevice.objects.create(notes=self.notes())
        PrintingDevice.objects.create(notes=START_NOTES + "\n" + TARGET_LINE)
        with self.assertRaisesMessage(CommandError, "ERROR"):
            self.run_command()
        device.refresh_from_db()
        self.assertEqual(device.notes, self.notes())

    def test_duplicate_and_reversed_markers_are_errors(self):
        for notes in (START_NOTES + END_NOTES + START_NOTES + END_NOTES, END_NOTES + START_NOTES):
            with self.subTest(notes=notes), self.assertRaises(ValueError):
                cleaned_notes(notes)

    def test_rollback_on_critical_save_error(self):
        devices = [PrintingDevice.objects.create(notes=self.notes()) for _ in range(2)]
        original_save = PrintingDevice.save
        count = 0
        def failing_save(device, *args, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                raise IntegrityError("Synthetic failure")
            return original_save(device, *args, **kwargs)
        with patch.object(PrintingDevice, "save", failing_save):
            with self.assertRaises(CommandError):
                self.run_command()
        for device in devices:
            device.refresh_from_db()
            self.assertEqual(device.notes, self.notes())
