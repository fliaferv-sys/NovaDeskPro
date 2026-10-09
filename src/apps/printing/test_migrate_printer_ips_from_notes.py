from io import StringIO
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command, CommandError
from django.db import IntegrityError, connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.printing.models import PrintingDevice, PrintingDeviceNetworkDetection
from apps.printing.printer_import import START_NOTES, END_NOTES


class MigratePrinterIpsFromNotesTests(TestCase):
    def notes(self, ip="192.0.2.1"):
        return "Manual IP actual: 192.0.2.99\n" + START_NOTES + "\nDependencia: Sector\nIP anterior: 192.0.2.2\nIP actual: " + ip + "\n" + END_NOTES + "\nOtra nota manual"

    def run_command(self, **options):
        output = StringIO()
        call_command("migrate_printer_ips_from_notes", stdout=output, **options)
        return output.getvalue()

    def test_model_accepts_ipv4_and_empty_but_rejects_ipv6(self):
        device = PrintingDevice(is_outsourced=False, ip_address="192.0.2.1")
        device.full_clean()
        device.ip_address = None
        device.full_clean()
        device.ip_address = "2001:db8::1"
        with self.assertRaises(ValidationError):
            device.full_clean()

    def test_migration_changes_only_ip_not_notes_or_timestamps(self):
        device = PrintingDevice.objects.create(notes=self.notes())
        before = PrintingDevice.objects.values().get(pk=device.pk)
        self.assertIn("ACTUALIZADO=1", self.run_command())
        after = PrintingDevice.objects.values().get(pk=device.pk)
        self.assertEqual(after.pop("ip_address"), "192.0.2.1")
        before.pop("ip_address")
        self.assertEqual(after, before)
        self.assertEqual(PrintingDeviceNetworkDetection.objects.count(), 0)

    def test_dry_run_no_writes(self):
        device = PrintingDevice.objects.create(notes=self.notes())
        with CaptureQueriesContext(connection) as queries:
            self.assertIn("ACTUALIZADO=1", self.run_command(dry_run=True))
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))
        device.refresh_from_db()
        self.assertIsNone(device.ip_address)

    def test_repeat_has_no_changes_or_updates(self):
        device = PrintingDevice.objects.create(notes=self.notes())
        self.run_command()
        with CaptureQueriesContext(connection) as queries:
            self.assertIn("SIN CAMBIOS=1", self.run_command())
        self.assertFalse(any(q["sql"].lstrip().upper().startswith("UPDATE") for q in queries))
        device.refresh_from_db()
        self.assertEqual(device.ip_address, "192.0.2.1")

    def test_conflicting_existing_ip_is_reviewed_and_not_overwritten(self):
        device = PrintingDevice.objects.create(notes=self.notes(), ip_address="192.0.2.5")
        self.assertIn("REVISAR=1", self.run_command())
        device.refresh_from_db()
        self.assertEqual(device.ip_address, "192.0.2.5")

    def test_invalid_ipv4_and_ipv6_are_reviewed(self):
        for ip in ("999.1.2.3", "2001:db8::1", "192.0.2.01", "192.0.2.1/24"):
            with self.subTest(ip=ip):
                device = PrintingDevice.objects.create(notes=self.notes(ip))
                self.assertIn("REVISAR=1", self.run_command())
                device.refresh_from_db()
                self.assertIsNone(device.ip_address)
                device.delete()

    def test_missing_or_empty_current_ip_is_unchanged(self):
        for notes in ("IP actual: 192.0.2.1", START_NOTES + "\nIP anterior: 192.0.2.1\n" + END_NOTES, self.notes("")):
            with self.subTest(notes=notes):
                device = PrintingDevice.objects.create(notes=notes)
                self.assertIn("SIN CAMBIOS=1", self.run_command())
                device.refresh_from_db()
                self.assertIsNone(device.ip_address)
                device.delete()

    def test_multiple_ip_lines_are_reviewed(self):
        PrintingDevice.objects.create(notes=self.notes("192.0.2.1\nIP actual: 192.0.2.3"))
        self.assertIn("REVISAR=1", self.run_command())
        self.assertIsNone(PrintingDevice.objects.get().ip_address)

    def test_damaged_block_aborts_real_run_before_writes(self):
        good = PrintingDevice.objects.create(notes=self.notes())
        PrintingDevice.objects.create(notes=START_NOTES + "\nIP actual: 192.0.2.2")
        with self.assertRaisesMessage(CommandError, "ERROR"):
            self.run_command()
        good.refresh_from_db()
        self.assertIsNone(good.ip_address)

    def test_critical_error_rolls_back_all_ip_updates(self):
        for _ in range(2):
            PrintingDevice.objects.create(notes=self.notes())
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
        self.assertEqual(PrintingDevice.objects.filter(ip_address__isnull=True).count(), 2)
