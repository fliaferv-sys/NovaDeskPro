from django.contrib import admin
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.accounts.models import Branch, User
from apps.inventory.models import OrganizationalLocation
from apps.printing.models import PrintingDevice


class PhotocopierAdminOrderingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser(username="printing-order", password="test")

    def changelist_ids(self, descending=False):
        request = RequestFactory().get(
            reverse("admin:printing_printingdevice_changelist"),
            {"o": "-1" if descending else "1"},
        )
        request.user = self.user
        model_admin = admin.site._registry[PrintingDevice]
        changelist = model_admin.get_changelist_instance(request)
        return list(changelist.get_queryset(request).values_list("photocopier_id", flat=True))

    def test_clickable_numeric_and_alphanumeric_order_both_directions(self):
        for identifier in ["55/BK", "11", "10", "2", "1"]:
            PrintingDevice.objects.create(photocopier_id=identifier)
        expected = ["1", "2", "10", "11", "55/BK"]
        self.assertEqual(self.changelist_ids(), expected)
        self.assertEqual(self.changelist_ids(descending=True), expected[::-1])

    def test_leading_zeroes_long_numbers_empty_and_stable_alphanumeric(self):
        identifiers = [None, "B-2", "A_1", "9" * 50, "1" + "0" * 49, "10", "002", "0", "00"]
        for identifier in identifiers:
            PrintingDevice.objects.create(photocopier_id=identifier)
        before = list(PrintingDevice.objects.order_by("pk").values())
        self.assertEqual(self.changelist_ids(), ["0", "00", "002", "10", "1" + "0" * 49, "9" * 50, "A_1", "B-2", None])
        self.assertEqual(list(PrintingDevice.objects.order_by("pk").values()), before)

    def test_compact_headers_and_readable_branch_and_location_cells(self):
        branch = Branch.objects.create(name="Planta Villa Elisa", code="PLANTA-VILLA-ELISA")
        location = OrganizationalLocation.objects.create(branch=branch, name="Dpto. Comercial")
        device = PrintingDevice.objects.create(branch=branch, organizational_location=location, photocopier_id="1")
        model_admin = admin.site._registry[PrintingDevice]
        for method, label in {
            "ordered_photocopier_id": "ID Equipo", "patrimony_display": "N° Patrimonio",
            "serial_display": "Serie", "type_display": "Tipo", "ownership_display": "Propiedad",
        }.items():
            self.assertEqual(getattr(model_admin, method).short_description, label)
        self.assertEqual(model_admin.branch_display(device), "Planta Villa Elisa")
        self.assertEqual(model_admin.location_display(device), "Planta Villa Elisa - Dpto. Comercial")
        self.client.force_login(self.user)
        response = self.client.get(reverse("admin:printing_printingdevice_changelist"))
        self.assertContains(response, "Planta Villa Elisa - Dpto. Comercial")
        self.assertNotContains(response, "PLANTA-VILLA-ELISA")
        self.assertContains(response, "N° Patrimonio")
        location.name = "Ubicación pendiente de verificar - Planta Villa Elisa"
        self.assertEqual(model_admin.location_display(device), location.name)
        device.organizational_location = None
        self.assertIsNone(model_admin.location_display(device))
