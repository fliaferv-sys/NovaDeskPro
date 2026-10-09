import csv
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command, CommandError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import Branch
from apps.inventory.models import OrganizationalLocation
from apps.printing.models import PrintingDevice
from apps.printing.printer_import import START_NOTES, END_NOTES
from apps.printing.location_analysis import analyze_locations, normalize_dependency, comparison_alias, analysis_summary
from apps.printing.management.commands.analyze_printer_locations import CSV_FIELDS


class AnalyzePrinterLocationsTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code="PLANTA-VILLA-ELISA", name="Planta Villa Elisa")
        self.other = Branch.objects.create(code="OFICINA-CENTRAL", name="Oficina Central")
        self.provisional = OrganizationalLocation.objects.create(branch=self.branch, code="UBICACION-PENDIENTE", name="Ubicacion pendiente de verificar - Planta Villa Elisa", location_type=OrganizationalLocation.LocationType.OTHER)

    def device(self, dependency, branch=None, identifier=None):
        note = "Sede: Villa Elisa\nDependencia: " + dependency
        return PrintingDevice.objects.create(
            branch=branch or self.branch, organizational_location=self.provisional if not branch or branch==self.branch else None,
            photocopier_id=identifier, serial_number="SER-" + str(identifier or "TEST"),
            notes="Nota manual\n" + START_NOTES + "\n" + note + "\n" + END_NOTES,
        )

    def location(self, name, branch=None, code="REAL"):
        return OrganizationalLocation.objects.create(branch=branch or self.branch, code=code, name=name, location_type=OrganizationalLocation.LocationType.OFFICE)

    def run_command(self, **options):
        output = StringIO()
        call_command("analyze_printer_locations", stdout=output, **options)
        return output.getvalue()

    def test_groups_by_branch_and_normalized_dependency_preserves_originals(self):
        self.device("Secretar\u00eda General", identifier="1")
        self.device("  SECRETARIA   GENERAL  ", identifier="2")
        self.device("Secretaria General", branch=self.other, identifier="3")
        groups = analyze_locations()
        self.assertEqual(len(groups), 2)
        villa = next(g for g in groups if g.branch==self.branch)
        self.assertEqual(len(villa.devices), 2)
        self.assertEqual(villa.originals, {"Secretar\u00eda General", "  SECRETARIA   GENERAL  "})
        self.assertEqual(analysis_summary(groups)["total_impresoras"], 3)
        self.assertEqual(analysis_summary(groups)["dependencias_unicas"], 2)

    def test_accent_case_and_spacing_normalization(self):
        self.assertEqual(normalize_dependency("  Direcci\u00f3n   JUR\u00cdDICA "), "direccion juridica")

    def test_dpto_department_is_possible_not_exact(self):
        self.device("Dpto. Agricola")
        candidate = self.location("Departamento Agr\u00edcola")
        group = analyze_locations()[0]
        self.assertEqual(comparison_alias("Dpto. Agricola"), "departamento agricola")
        self.assertEqual(group.status, "POSIBLE COINCIDENCIA")
        self.assertEqual(group.candidates, [candidate])

    def test_unique_exact_location_within_branch(self):
        self.device("Secretar\u00eda General")
        candidate = self.location("SECRETARIA   GENERAL")
        group = analyze_locations()[0]
        self.assertEqual(group.status, "COINCIDENCIA EXACTA")
        self.assertEqual(group.candidates, [candidate])

    def test_identical_description_in_other_branch_not_used(self):
        self.device("Laboratorio")
        self.location("Laboratorio", branch=self.other)
        self.assertEqual(analyze_locations()[0].status, "NO EXISTE")

    def test_possible_candidate_is_never_applied(self):
        device = self.device("Inform\u00e1tica")
        self.location("Oficina de Inform\u00e1tica")
        before = PrintingDevice.objects.values().get(pk=device.pk)
        self.assertIn("POSIBLE COINCIDENCIA", self.run_command())
        self.assertEqual(PrintingDevice.objects.values().get(pk=device.pk), before)

    def test_compatible_locations_are_ambiguous(self):
        self.device("Secretaria General")
        self.location("Secretaria General", code="ONE")
        self.location("SECRETAR\u00cdA GENERAL", code="TWO")
        group = analyze_locations()[0]
        self.assertEqual(group.status, "AMBIGUA")
        self.assertEqual(len(group.candidates), 2)

    def test_empty_and_missing_dependencies(self):
        self.device("   ")
        PrintingDevice.objects.create(branch=self.branch, notes=START_NOTES + "\nSede: Villa Elisa\n" + END_NOTES)
        group = analyze_locations()[0]
        self.assertEqual(group.status, "SIN DEPENDENCIA")
        self.assertEqual(len(group.devices), 2)
        self.assertEqual(analysis_summary([group])["dependencias_unicas"], 0)

    def test_command_only_reads_database(self):
        device = self.device("Laboratorio")
        before = PrintingDevice.objects.values().get(pk=device.pk)
        locations = list(OrganizationalLocation.objects.values())
        with CaptureQueriesContext(connection) as queries:
            self.run_command()
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER")) for q in queries))
        self.assertEqual(PrintingDevice.objects.values().get(pk=device.pk), before)
        self.assertEqual(list(OrganizationalLocation.objects.values()), locations)

    def test_optional_csv_contains_required_fields_and_original_text(self):
        self.device("  Direcci\u00f3n Jur\u00eddica  ", identifier="55/BK")
        with TemporaryDirectory() as directory:
            path = Path(directory)/"report.csv"
            self.run_command()
            self.assertFalse(path.exists())
            self.run_command(output=str(path))
            with path.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(reader.fieldnames, list(CSV_FIELDS))
                row = list(reader)[0]
            self.assertEqual(row["dependencia_original"], "  Direcci\u00f3n Jur\u00eddica  ")
            self.assertEqual(row["ids_fotocopiadora"], "55/BK")
            self.assertEqual(row["dependencia_normalizada"], "direccion juridica")
            with self.assertRaises(CommandError):
                self.run_command(output=str(path))

    def test_manual_notes_and_non_imported_devices_excluded(self):
        PrintingDevice.objects.create(notes="Dependencia: Laboratorio")
        self.assertEqual(analyze_locations(), [])

    def test_damaged_or_duplicate_dependency_block_not_guessed(self):
        for notes in (START_NOTES + "\nDependencia: Sector", START_NOTES + "\nDependencia: A\nDependencia: B\n" + END_NOTES):
            device = PrintingDevice.objects.create(notes=notes)
            with self.assertRaises(CommandError):
                self.run_command()
            device.delete()

    def test_inactive_and_provisional_candidates_excluded(self):
        self.device(self.provisional.name)
        self.assertEqual(analyze_locations()[0].status, "NO EXISTE")
        candidate = self.location(self.provisional.name, code="INACTIVE")
        candidate.is_active = False
        candidate.save()
        self.assertEqual(analyze_locations()[0].status, "NO EXISTE")

    def test_no_fuzzy_matching_for_similar_spelling(self):
        self.device("Juridica")
        self.location("Juridico")
        self.assertEqual(analyze_locations()[0].status, "NO EXISTE")

    def test_missing_branch_is_not_inferred_from_note(self):
        device = self.device("Laboratorio")
        device.branch = None
        device.save(update_fields=["branch"])
        self.location("Laboratorio")
        group = analyze_locations()[0]
        self.assertIsNone(group.branch)
        self.assertEqual(group.status, "NO EXISTE")
        self.assertTrue(group.warnings)
