import csv
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import Branch
from apps.inventory.models import OrganizationalLocation
from apps.printing.models import PrintingDevice
from apps.printing.printer_import import START_NOTES, END_NOTES
from apps.printing.location_proposals import propose_locations, proposal_summary
from apps.printing.management.commands.propose_printer_locations import CSV_FIELDS


class ProposePrinterLocationsTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code="PLANTA-VILLA-ELISA", name="Planta Villa Elisa")
        self.other = Branch.objects.create(code="OFICINA-CENTRAL", name="Oficina Central")

    def device(self, dependency, branch=None, identifier=None):
        branch = branch or self.branch
        return PrintingDevice.objects.create(branch=branch, serial_number="SER-" + str(identifier or "1"), photocopier_id=identifier,
            notes=START_NOTES + "\nSede: " + branch.name + "\nDependencia: " + dependency + "\n" + END_NOTES)

    def run_command(self, **kwargs):
        output = StringIO()
        call_command("propose_printer_locations", stdout=output, **kwargs)
        return output.getvalue()

    def test_clear_institutional_names_are_creation_proposals(self):
        for text in ("Direcci\u00f3n Jur\u00eddica", "Secretar\u00eda General", "Direcci\u00f3n de Recursos Humanos", "Direcci\u00f3n de la DTI", "Laboratorio", "Programaci\u00f3n y Evaluaci\u00f3n", "Inform\u00e1tica"):
            self.device(text)
        proposals = propose_locations()
        self.assertEqual(len(proposals), 7)
        self.assertTrue(all(p.classification=="PROPUESTA CREAR" for p in proposals))

    def test_department_abbreviation_variants_are_possible_duplicates(self):
        self.device("Dpto. Agricola")
        self.device("Departamento Agr\u00edcola")
        proposals = propose_locations()
        self.assertEqual(len(proposals), 2)
        self.assertTrue(all(p.classification=="POSIBLE DUPLICADO" for p in proposals))
        self.assertTrue(all(p.related for p in proposals))

    def test_accent_variants_in_one_group_are_reported_as_duplicates(self):
        self.device("Direccion de Recursos Humanos", identifier="1")
        self.device("Direcci\u00f3n de Recursos Humanos", identifier="2")
        proposal = propose_locations()[0]
        self.assertEqual(proposal.classification, "POSIBLE DUPLICADO")
        self.assertEqual(len(proposal.group.devices), 2)
        self.assertEqual(len(proposal.group.originals), 2)
        self.assertIn("Direcci\u00f3n de Recursos Humanos", proposal.related)

    def test_ana_cardenas_is_possible_person(self):
        self.device("Ana Cardenas")
        self.assertEqual(propose_locations()[0].classification, "POSIBLE PERSONA")

    def test_two_word_text_is_not_automatically_a_person(self):
        self.device("Costa Azul")
        self.assertEqual(propose_locations()[0].classification, "REVISAR")

    def test_empty_strange_generic_and_unwanted_structure_are_reviewed(self):
        for text in ("", "???", "1234", "Direcci\u00f3n", "Direcci\u00f3n de", "Dpto.", "Sector", "Ana Cardenas (BACKUP)", "\u00c1rea de Finanzas"):
            self.device(text)
        self.assertTrue(all(p.classification=="REVISAR" for p in propose_locations()))

    def test_same_dependency_different_branches_is_separate(self):
        self.device("Secretar\u00eda General")
        self.device("Secretar\u00eda General", branch=self.other)
        proposals = propose_locations()
        self.assertEqual(len(proposals), 2)
        self.assertTrue(all(p.classification=="PROPUESTA CREAR" for p in proposals))
        self.assertTrue(all(not p.related for p in proposals))

    def test_abbreviation_candidates_do_not_cross_branches(self):
        self.device("Dpto. Agricola")
        self.device("Departamento Agr\u00edcola", branch=self.other)
        self.assertTrue(all(p.classification=="PROPUESTA CREAR" for p in propose_locations()))

    def test_existing_location_in_other_branch_is_not_related(self):
        self.device("Laboratorio")
        OrganizationalLocation.objects.create(branch=self.other, code="LAB", name="Laboratorio", location_type=OrganizationalLocation.LocationType.OFFICE)
        self.assertEqual(propose_locations()[0].classification, "PROPUESTA CREAR")

    def test_existing_location_within_branch_requires_review_not_creation(self):
        self.device("Laboratorio")
        OrganizationalLocation.objects.create(branch=self.branch, code="LAB", name="Laboratorio", location_type=OrganizationalLocation.LocationType.OFFICE)
        proposal = propose_locations()[0]
        self.assertEqual(proposal.classification, "REVISAR")
        self.assertIn("LAB", proposal.related[0])

    def test_command_does_not_create_locations_or_update_devices(self):
        self.device("Secretar\u00eda General")
        before_devices = list(PrintingDevice.objects.values())
        before_locations = list(OrganizationalLocation.objects.values())
        with CaptureQueriesContext(connection) as queries:
            self.run_command()
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER")) for q in queries))
        self.assertEqual(list(PrintingDevice.objects.values()), before_devices)
        self.assertEqual(list(OrganizationalLocation.objects.values()), before_locations)
        self.assertEqual(OrganizationalLocation.objects.count(), 0)

    def test_csv_optional_correct_and_original_preserved(self):
        self.device("  Secretar\u00eda General  ", identifier="55/BK")
        with TemporaryDirectory() as directory:
            path = Path(directory)/"proposal.csv"
            self.run_command()
            self.assertFalse(path.exists())
            self.run_command(output=str(path))
            with path.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(reader.fieldnames, list(CSV_FIELDS))
                row = list(reader)[0]
            self.assertEqual(row["dependencia_original"], "  Secretar\u00eda General  ")
            self.assertEqual(row["ids_fotocopiadora"], "55/BK")
            self.assertEqual(row["clasificacion"], "PROPUESTA CREAR")

    def test_non_imported_devices_are_excluded(self):
        PrintingDevice.objects.create(notes="Dependencia: Laboratorio")
        self.assertEqual(propose_locations(), [])
        self.assertEqual(proposal_summary([])["total_impresoras"], 0)

    def test_inconsistent_branch_requires_review(self):
        device = self.device("Laboratorio")
        device.branch = self.other
        device.save(update_fields=["branch"])
        self.assertEqual(propose_locations()[0].classification, "REVISAR")
