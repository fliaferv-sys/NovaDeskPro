from django.contrib import admin
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.accounts.models import User
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
