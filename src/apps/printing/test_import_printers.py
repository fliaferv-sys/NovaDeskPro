from datetime import date
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.db import IntegrityError, connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from openpyxl import Workbook

from apps.accounts.models import Branch, User
from apps.inventory.models import Asset, OrganizationalLocation
from .models import PrintingContract, PrintingDevice, PrintingDeviceNetworkDetection
from .printer_import import COLUMNS, END_NOTES, START_NOTES, save_import_row


class ImportPrintersTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "printers.xlsx"
        self.branch = Branch.objects.create(code="HQ", name="Sede Principal")
        self.location = OrganizationalLocation.objects.create(branch=self.branch, code="TI", name="Informática")
        self.responsible = User.objects.create_user(username="responsible", email="responsible@example.test")

    def row(self, **changes):
        row = dict.fromkeys(COLUMNS, "")
        row.update({"Serie": "SERIAL-001", "Modelo": "MX622ADHE", "Sede": "HQ", "Dependencia": "TI", "Estado validación": "VALIDADO"})
        row.update(changes)
        return row

    def workbook(self, rows, columns=COLUMNS, sheet="IMPORTACION_PRINTING"):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = sheet
        worksheet.append(list(columns))
        for row in rows:
            worksheet.append([row.get(name, "") for name in columns])
        workbook.save(self.path)
        workbook.close()

    def run_import(self, rows=None, *, dry_run=False, brand="Lexmark"):
        if rows is not None:
            self.workbook(rows)
        output = StringIO()
        call_command("import_printers", str(self.path), dry_run=dry_run, brand=brand, stdout=output)
        return output.getvalue()

    def device(self, **changes):
        values = dict(serial_number="SERIAL-001", model="Modelo Anterior", brand="Lexmark", branch=self.branch, organizational_location=self.location)
        values.update(changes)
        return PrintingDevice.objects.create(**values)

    def test_valid_file_dry_run_has_no_writes_of_any_kind(self):
        self.workbook([self.row()])
        with CaptureQueriesContext(connection) as queries:
            output = self.run_import(dry_run=True)
        self.assertIn("NUEVO=1", output)
        self.assertEqual(PrintingDevice.objects.count(), 0)
        self.assertEqual(PrintingDeviceNetworkDetection.objects.count(), 0)
        self.assertEqual(User.objects.count(), 1)
        writes = [query["sql"] for query in queries if query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
        self.assertEqual(writes, [])

    def test_real_import_preserves_source_text_without_creating_other_entities(self):
        output = self.run_import([self.row(**{"Responsable": "Persona sin cuenta", "IP actual": "192.0.2.5", "IP anterior": "2001:db8::1", "ID origen": "ORIGIN-1", "Nombre impresora": "Impresora Prueba", "Calcomanía": "STICKER-1", "Observaciones": "Dato de origen"})])
        self.assertIn("NUEVO=1", output)
        device = PrintingDevice.objects.get()
        self.assertEqual(device.serial_number, "SERIAL-001")
        self.assertEqual(device.branch, self.branch)
        self.assertEqual(device.organizational_location, self.location)
        self.assertIsNone(device.responsible_user)
        self.assertEqual(device.photocopier_id, "ORIGIN-1")
        self.assertIn("Responsable: Persona sin cuenta", device.notes)
        self.assertIn("IP actual: 192.0.2.5", device.notes)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Asset.objects.count(), 0)
        self.assertEqual(PrintingDeviceNetworkDetection.objects.count(), 0)
        self.assertNotIn("Persona sin cuenta", output)

    def test_duplicate_serial_in_excel_rejects_all_occurrences(self):
        output = self.run_import([self.row(), self.row(**{"Serie": "  serial-001  "}), self.row(**{"Serie": "UNIQUE-002"})])
        self.assertIn("RECHAZADO=2", output)
        self.assertIn("NUEVO=1", output)
        self.assertEqual(list(PrintingDevice.objects.values_list("serial_number", flat=True)), ["UNIQUE-002"])

    def test_duplicate_serial_already_in_database_rejects_without_changes(self):
        self.device()
        self.device(serial_number="  serial-001  ")
        output = self.run_import([self.row()])
        self.assertIn("RECHAZADO=1", output)
        self.assertEqual(PrintingDevice.objects.count(), 2)
        self.assertEqual(set(PrintingDevice.objects.values_list("model", flat=True)), {"Modelo Anterior"})

    def test_update_and_repeat_are_idempotent_and_preserve_unrelated_fields(self):
        device = self.device(notes="Nota manual", photocopier_id="OPS-001", snmp_enabled=True)
        output = self.run_import([self.row()])
        self.assertIn("ACTUALIZADO=1", output)
        device.refresh_from_db()
        self.assertEqual(device.model, "MX622ADHE")
        self.assertEqual(device.brand, "Lexmark")
        self.assertEqual(device.photocopier_id, "OPS-001")
        self.assertTrue(device.snmp_enabled)
        self.assertTrue(device.notes.startswith("Nota manual\n\n"))
        updated_at = device.updated_at
        output = self.run_import(dry_run=False)
        self.assertIn("SIN CAMBIOS=1", output)
        device.refresh_from_db()
        self.assertEqual(device.updated_at, updated_at)
        self.assertEqual(device.notes.count(START_NOTES), 1)
        self.assertEqual(PrintingDevice.objects.count(), 1)

    def test_update_dry_run_preserves_database_values(self):
        device = self.device(notes="Original")
        output = self.run_import([self.row()], dry_run=True)
        self.assertIn("ACTUALIZADO=1", output)
        device.refresh_from_db()
        self.assertEqual(device.model, "Modelo Anterior")
        self.assertEqual(device.notes, "Original")

    def test_valid_ipv4_and_ipv6_are_accepted(self):
        output = self.run_import([self.row(**{"IP actual": " 192.0.2.1 ", "IP anterior": "2001:db8:0:0::1"})])
        self.assertIn("NUEVO=1", output)
        self.assertIn("IP anterior: 2001:db8::1", PrintingDevice.objects.get().notes)

    def test_invalid_current_or_previous_ip_rejects_entire_row(self):
        for name in ("IP actual", "IP anterior"):
            with self.subTest(name=name):
                output = self.run_import([self.row(**{name: "999.1.2.3"})])
                self.assertIn("RECHAZADO=1", output)
                self.assertEqual(PrintingDevice.objects.count(), 0)

    def test_review_row_is_ignored_before_validation_and_duplicate_detection(self):
        output = self.run_import([self.row(**{"Estado validación": " revisar ", "IP actual": "invalid"}), self.row()])
        self.assertIn("IGNORADO=1", output)
        self.assertIn("NUEVO=1", output)
        self.assertEqual(PrintingDevice.objects.count(), 1)

    def test_serial_validation_and_text_identifiers(self):
        rows = [self.row(**{"Serie": serial}) for serial in ("", "S/N", "---", "X" * 151, 12345)]
        output = self.run_import(rows)
        self.assertIn("RECHAZADO=5", output)
        self.assertEqual(PrintingDevice.objects.count(), 0)

    def test_whitespace_normalization_keeps_leading_zero_text_serial(self):
        output = self.run_import([self.row(**{"Serie": " 00123 ", "Modelo": " MX622ADHE "})])
        self.assertIn("NUEVO=1", output)
        self.assertEqual(PrintingDevice.objects.get().serial_number, "00123")
        self.assertEqual(PrintingDevice.objects.get().model, "MX622ADHE")

    def test_missing_columns_are_critical_and_write_nothing(self):
        self.workbook([self.row()], columns=[name for name in COLUMNS if name != "Serie"])
        with self.assertRaisesMessage(CommandError, "Faltan columnas"):
            self.run_import()
        self.assertEqual(PrintingDevice.objects.count(), 0)

    def test_wrong_sheet_and_duplicate_headers_are_critical(self):
        self.workbook([self.row()], sheet="OTRA")
        with self.assertRaisesMessage(CommandError, "Falta la hoja"):
            self.run_import()
        self.workbook([self.row()], columns=[*COLUMNS, "Serie"])
        with self.assertRaisesMessage(CommandError, "encabezados duplicados"):
            self.run_import()

    def test_missing_or_corrupt_file_is_critical(self):
        with self.assertRaises(CommandError):
            self.run_import()
        self.path.write_text("Not an Excel", encoding="utf-8")
        with self.assertRaises(CommandError):
            self.run_import()

    def test_formula_row_is_rejected(self):
        output = self.run_import([self.row(**{"Modelo": '=CONCAT("Modelo", "Prueba")'})])
        self.assertIn("RECHAZADO=1", output)
        self.assertEqual(PrintingDevice.objects.count(), 0)

    def test_rollback_on_critical_error_including_updates(self):
        device = self.device(notes="Original")
        contract = PrintingContract.objects.create(contract_number="CONTRACT-1", provider="Proveedor Prueba", start_date=date(2026, 1, 1), end_date=date(2027, 1, 1))
        self.workbook([self.row(**{"Contrato": "CONTRACT-1"}), self.row(**{"Serie": "SERIAL-002"})])
        count = 0
        def failing_save(row):
            nonlocal count
            count += 1
            if count == 2:
                raise IntegrityError("Critical synthetic error")
            save_import_row(row)
        with patch("apps.printing.management.commands.import_printers.save_import_row", side_effect=failing_save):
            with self.assertRaisesMessage(CommandError, "rollback"):
                self.run_import()
        device.refresh_from_db()
        self.assertEqual(device.model, "Modelo Anterior")
        self.assertEqual(device.notes, "Original")
        self.assertEqual(PrintingDevice.objects.count(), 1)
        self.assertEqual(contract.devices.count(), 0)

    def test_responsible_exact_email_or_username_only(self):
        output = self.run_import([self.row(**{"Responsable": " RESPONSIBLE@EXAMPLE.TEST "})])
        self.assertIn("NUEVO=1", output)
        self.assertEqual(PrintingDevice.objects.get().responsible_user, self.responsible)
        self.responsible.first_name = "Nombre"
        self.responsible.last_name = "Completo"
        self.responsible.save()
        self.run_import([self.row(**{"Responsable": "Nombre Completo"})])
        self.assertIn("Responsable: Nombre Completo", PrintingDevice.objects.get().notes)
        self.assertEqual(User.objects.count(), 1)

    def test_ambiguous_responsible_and_unknown_contract_are_pending(self):
        User.objects.create_user(username="other", email="RESPONSIBLE@EXAMPLE.TEST")
        output = self.run_import([self.row(**{"Responsable": "responsible@example.test", "Contrato": "NOT-FOUND"})])
        self.assertIn("NUEVO=1", output)
        self.assertIn("pendientes=1", output)
        device = PrintingDevice.objects.get()
        self.assertIsNone(device.responsible_user)
        self.assertEqual(device.contracts.count(), 0)
        self.assertEqual(PrintingContract.objects.count(), 0)

    def test_existing_contract_is_ignored_without_link_or_notes(self):
        contract = PrintingContract.objects.create(contract_number="CONTRACT-1", provider="Proveedor Prueba", start_date=date(2026, 1, 1), end_date=date(2027, 1, 1))
        output = self.run_import([self.row(**{"Contrato": "contract-1"})])
        self.assertIn("NUEVO=1", output)
        self.assertEqual(contract.devices.count(), 0)
        self.assertIn("SIN CAMBIOS=1", self.run_import())
        self.assertEqual(contract.devices.count(), 0)
        self.assertNotIn("Contrato:", PrintingDevice.objects.get().notes)

    def test_confirmed_model_infers_brand_without_explicit_option(self):
        output = self.run_import([self.row()], brand="")
        self.assertIn("NUEVO=1", output)
        self.assertEqual(PrintingDevice.objects.get().brand, "Lexmark")
        self.assertEqual(PrintingDevice.objects.count(), 1)

    def test_unknown_or_ambiguous_location_does_not_create_locations(self):
        output = self.run_import([self.row(**{"Dependencia": "No existe"})])
        self.assertIn("RECHAZADO=1", output)
        OrganizationalLocation.objects.create(branch=self.branch, code="OTHER", name="Informática")
        output = self.run_import([self.row(**{"Dependencia": "Informática"})])
        self.assertIn("RECHAZADO=1", output)
        self.assertEqual(OrganizationalLocation.objects.count(), 2)

    def test_foreign_key_updates_are_saved_correctly(self):
        device = self.device()
        branch = Branch.objects.create(code="OTHER", name="Otra sede")
        location = OrganizationalLocation.objects.create(branch=branch, code="TI", name="Informática")
        output = self.run_import([self.row(**{"Sede": "OTHER", "Dependencia": "TI", "Responsable": "responsible"})])
        self.assertIn("ACTUALIZADO=1", output)
        device.refresh_from_db()
        self.assertEqual(device.branch, branch)
        self.assertEqual(device.organizational_location, location)
        self.assertEqual(device.responsible_user, self.responsible)

    def test_asset_serial_fallback_prevents_duplicate_printing_device(self):
        asset = Asset.objects.create(internal_code="ASSET-1", serial_number="SERIAL-001")
        device = self.device(serial_number="", asset=asset)
        output = self.run_import([self.row()])
        self.assertIn("ACTUALIZADO=1", output)
        self.assertEqual(PrintingDevice.objects.count(), 1)
        device.refresh_from_db()
        self.assertEqual(device.serial_number, "SERIAL-001")
        self.assertEqual(device.asset, asset)

    def test_approved_aliases_use_only_their_provisional_location(self):
        branches = {}
        for code in ("PLANTA-VILLA-ELISA", "OFICINA-CENTRAL", "PLANTA-MAURICIO-JOSE-TROCHE"):
            branch = Branch.objects.create(code=code, name=code)
            location = OrganizationalLocation.objects.create(branch=branch, code="UBICACION-PENDIENTE", name="Pendiente " + code)
            branches[code] = (branch, location)
        aliases = {"Villa Elisa": "PLANTA-VILLA-ELISA", "Viila Elisa": "PLANTA-VILLA-ELISA", "Centro": "OFICINA-CENTRAL", "Troche": "PLANTA-MAURICIO-JOSE-TROCHE"}
        for index, (alias, code) in enumerate(aliases.items()):
            with self.subTest(alias=alias):
                output = self.run_import([self.row(**{"Serie": "ALIAS-" + str(index), "Sede": alias, "Dependencia": "  Dependencia   original  "})], brand="")
                self.assertIn("NUEVO=1", output)
                device = PrintingDevice.objects.get(serial_number="ALIAS-" + str(index))
                self.assertEqual(device.branch, branches[code][0])
                self.assertEqual(device.organizational_location, branches[code][1])
                self.assertIn("Dependencia:   Dependencia   original  ", device.notes)
                self.assertIsNone(device.asset)
        self.assertEqual(PrintingContract.objects.count(), 0)
        self.assertEqual(PrintingDeviceNetworkDetection.objects.count(), 0)

    def test_all_approved_families_infer_lexmark(self):
        families = ("MX622", "MX611", "MX521", "MX632", "MX711", "MX722", "CX622", "CX725")
        output = self.run_import([self.row(**{"Serie": family, "Modelo": family + "ADHE"}) for family in families], brand="")
        self.assertIn("NUEVO=8", output)
        self.assertEqual(set(PrintingDevice.objects.values_list("brand", flat=True)), {"Lexmark"})

    def test_unknown_models_cannot_be_overridden_by_brand(self):
        for model in ("MX999", "MX6221", "MX622-UNKNOWN", "OTHER", ""):
            with self.subTest(model=model):
                output = self.run_import([self.row(**{"Modelo": model})], brand="Lexmark")
                self.assertIn("RECHAZADO=1", output)
                self.assertIn("REVISAR", output)
        self.assertEqual(PrintingDevice.objects.count(), 0)

    def test_existing_conflicting_brand_rejects_without_change(self):
        device = self.device(brand="Other")
        self.assertIn("RECHAZADO=1", self.run_import([self.row()], brand=""))
        device.refresh_from_db()
        self.assertEqual(device.brand, "Other")

    def test_provisional_does_not_replace_valid_existing_location(self):
        device = self.device()
        OrganizationalLocation.objects.create(branch=self.branch, code="UBICACION-PENDIENTE", name="Pendiente")
        self.assertIn("ACTUALIZADO=1", self.run_import([self.row(**{"Dependencia": "Unmapped"})], brand=""))
        device.refresh_from_db()
        self.assertEqual(device.organizational_location, self.location)

    def test_provisional_does_not_resolve_unknown_branch(self):
        OrganizationalLocation.objects.create(branch=self.branch, code="UBICACION-PENDIENTE", name="Pendiente")
        self.assertIn("RECHAZADO=1", self.run_import([self.row(**{"Sede": "Unknown", "Dependencia": "Unmapped"})], brand=""))
        self.assertEqual(PrintingDevice.objects.count(), 0)

    def test_unconfirmed_contract_ignored_and_not_queried(self):
        self.workbook([self.row(**{"Contrato": "PR/PR N\u00b0 012/22"})])
        with CaptureQueriesContext(connection) as queries:
            self.run_import()
        device = PrintingDevice.objects.get()
        self.assertNotIn("Contrato:", device.notes)
        self.assertNotIn("012/22", device.notes)
        self.assertEqual(PrintingContract.objects.count(), 0)
        self.assertFalse(any("printing_printingcontract" in q["sql"].lower() for q in queries))

    def test_contract_formula_is_ignored(self):
        self.assertIn("NUEVO=1", self.run_import([self.row(**{"Contrato": '=CONCAT("PR", "012/22")'})]))

    def test_current_ipv4_is_saved_and_previous_ip_stays_in_notes(self):
        self.run_import([self.row(**{"IP actual": " 192.0.2.15 ", "IP anterior": "192.0.2.14"})])
        device = PrintingDevice.objects.get()
        self.assertEqual(device.ip_address, "192.0.2.15")
        self.assertIn("IP anterior: 192.0.2.14", device.notes)
        self.assertIn("IP actual: 192.0.2.15", device.notes)
        self.assertEqual(PrintingDeviceNetworkDetection.objects.count(), 0)
        self.assertEqual(device.web_interface_url, "")

    def test_empty_current_ip_is_null_for_new_and_existing_device(self):
        self.run_import([self.row()])
        device = PrintingDevice.objects.get()
        self.assertIsNone(device.ip_address)
        device.ip_address = "192.0.2.1"
        device.save(update_fields=["ip_address"])
        self.run_import([self.row()])
        device.refresh_from_db()
        self.assertIsNone(device.ip_address)

    def test_invalid_current_ip_reviews_only_bad_rows(self):
        output = self.run_import([self.row(**{"IP actual": "2001:db8::1"}), self.row(**{"Serie": "GOOD-IP", "IP actual": "192.0.2.2"})])
        self.assertIn("RECHAZADO=1", output)
        self.assertIn("REVISAR", output)
        self.assertIn("NUEVO=1", output)
        self.assertEqual(PrintingDevice.objects.get().ip_address, "192.0.2.2")

    def test_origin_id_saved_and_not_replaced_by_row_number(self):
        self.run_import([self.row(**{"ID origen": 17, "N\u00b0 origen": 99})])
        self.assertEqual(PrintingDevice.objects.get().photocopier_id, "17")
        self.assertIn("SIN CAMBIOS=1", self.run_import())

    def test_origin_id_empty_preserves_existing_identifier(self):
        device = self.device(photocopier_id="OLD-1")
        self.run_import([self.row(**{"N\u00b0 origen": 99})])
        device.refresh_from_db()
        self.assertEqual(device.photocopier_id, "OLD-1")

    def test_duplicate_origin_ids_reject_all_claiming_rows(self):
        output = self.run_import([self.row(**{"ID origen": "ID-1"}), self.row(**{"Serie": "SECOND", "ID origen": "id-1"})])
        self.assertIn("RECHAZADO=2", output)
        self.assertIn("REVISAR", output)
        self.assertEqual(PrintingDevice.objects.count(), 0)

    def test_id_conflict_with_existing_owner_rejects_without_updates(self):
        device = self.device(serial_number="OTHER", photocopier_id="ID-1")
        output = self.run_import([self.row(**{"ID origen": "ID-1"})])
        self.assertIn("RECHAZADO=1", output)
        self.assertEqual(PrintingDevice.objects.count(), 1)
        device.refresh_from_db()
        self.assertEqual(device.serial_number, "OTHER")

    def test_existing_different_id_and_invalid_id_require_review(self):
        device = self.device(photocopier_id="OLD-1")
        for identifier in ("NEW-1", "S/N", "ID WITH SPACE", "0", "X" * 51):
            with self.subTest(identifier=identifier):
                self.assertIn("RECHAZADO=1", self.run_import([self.row(**{"ID origen": identifier})]))
                device.refresh_from_db()
                self.assertEqual(device.photocopier_id, "OLD-1")

    def test_import_preserves_slash_id_and_rejects_slash_duplicates(self):
        self.run_import([self.row(**{"ID origen": "55/BK"})])
        self.assertEqual(PrintingDevice.objects.get().photocopier_id, "55/BK")
        output = self.run_import([self.row(**{"Serie": "NEW-1", "ID origen": "66/BK"}), self.row(**{"Serie": "NEW-2", "ID origen": "66/bk"})])
        self.assertIn("RECHAZADO=2", output)
        self.assertEqual(PrintingDevice.objects.count(), 1)
