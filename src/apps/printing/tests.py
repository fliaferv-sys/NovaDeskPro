from django.contrib import admin
from django.core.exceptions import FieldDoesNotExist
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User


class PrintingDashboardAccessTests(TestCase):
    def create_user(self, email, role):
        return User.objects.create_user(
            username=email,
            email=email,
            password="test-password-123",
            role=role,
        )

    def test_allowed_roles_can_open_printing_dashboard(self):
        for role in (
            User.Role.ADMIN,
            User.Role.SUPERVISOR,
            User.Role.AUDITOR,
            User.Role.TECHNICIAN,
        ):
            with self.subTest(role=role):
                user = self.create_user(
                    f"{role.lower()}@example.test",
                    role,
                )
                self.client.force_login(user)

                response = self.client.get(reverse("printing:dashboard"))

                self.assertEqual(response.status_code, 200)

                self.client.logout()

    def test_client_cannot_open_printing_dashboard(self):
        user = self.create_user(
            "printing-client@example.test",
            User.Role.CLIENT,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("printing:dashboard"))

        self.assertEqual(response.status_code, 403)


class PrintingDeviceDetailTests(TestCase):
    def test_detail_uses_existing_asset_location_relation(self):
        from apps.inventory.models import Asset
        from .models import PrintingDevice

        user = User.objects.create_user(
            username="printing-detail-admin",
            email="printing-detail-admin@example.test",
            password="test-password-123",
            role=User.Role.ADMIN,
        )
        asset = Asset.objects.create(
            internal_code="PRINT-DETAIL-001",
            asset_type=Asset.AssetType.PRINTER,
            brand="Test",
            model="DetailPrinter",
        )
        printing_device = PrintingDevice.objects.create(asset=asset)
        self.client.force_login(user)

        response = self.client.get(
            reverse("printing:device_detail", kwargs={"pk": printing_device.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["device"], printing_device)


class PrintingAdminSearchFieldsTests(TestCase):
    def test_all_printing_admin_search_fields_resolve_to_existing_fields(self):
        printing_admins = (
            model_admin
            for model, model_admin in admin.site._registry.items()
            if model._meta.app_label == "printing"
        )

        for model_admin in printing_admins:
            for search_field in model_admin.search_fields:
                model = model_admin.model
                field_path = search_field.lstrip("^=@")

                with self.subTest(
                    model=model._meta.label,
                    search_field=search_field,
                ):
                    for field_name in field_path.split("__"):
                        try:
                            field = model._meta.get_field(field_name)
                        except FieldDoesNotExist as error:
                            self.fail(str(error))
                        if field.is_relation:
                            model = field.related_model

class ConsumableStockTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="printing-stock-user",
            email="printing-stock-user@example.test",
            password="test-password-123",
            role=User.Role.ADMIN,
        )

    def test_current_stock_uses_initial_entries_and_outputs(self):
        from .models import Consumable, StockMovement

        consumable = Consumable.objects.create(
            name="Tóner negro",
            reference_code="TONER-TEST-001",
            manufacturer="Test",
            model="T-001",
            initial_stock=10,
            minimum_stock=3,
            maximum_stock=30,
        )

        StockMovement.objects.create(
            consumable=consumable,
            movement_type=StockMovement.MovementType.ENTRY,
            quantity=5,
            performed_by=self.user,
        )

        StockMovement.objects.create(
            consumable=consumable,
            movement_type=StockMovement.MovementType.ISSUE,
            quantity=4,
            performed_by=self.user,
        )

        self.assertEqual(consumable.total_entries, 5)
        self.assertEqual(consumable.total_outputs, 4)
        self.assertEqual(consumable.current_stock, 11)
    def test_output_cannot_exceed_available_stock(self):
        from django.core.exceptions import ValidationError
        from .models import Consumable, StockMovement

        consumable = Consumable.objects.create(
            name="Tóner negro límite",
            reference_code="TONER-TEST-002",
            manufacturer="Test",
            model="T-002",
            initial_stock=3,
            minimum_stock=1,
            maximum_stock=20,
        )

        movement = StockMovement(
            consumable=consumable,
            movement_type=StockMovement.MovementType.ISSUE,
            quantity=4,
            performed_by=self.user,
        )

        with self.assertRaises(ValidationError):
            movement.full_clean()

    def test_consumable_must_be_compatible_with_printing_device(self):
        from django.core.exceptions import ValidationError

        from apps.inventory.models import Asset
        from .models import Consumable, PrintingDevice, StockMovement

        asset = Asset.objects.create(
            internal_code="PRINT-TEST-001",
            asset_type=Asset.AssetType.PRINTER,
            brand="Test",
            model="Printer-001",
        )

        printing_device = PrintingDevice.objects.create(
            asset=asset,
        )

        consumable = Consumable.objects.create(
            name="Tóner incompatible",
            reference_code="TONER-TEST-003",
            manufacturer="Test",
            model="T-003",
            initial_stock=10,
            minimum_stock=2,
            maximum_stock=20,
        )

        movement = StockMovement(
            consumable=consumable,
            movement_type=StockMovement.MovementType.CONSUMPTION,
            quantity=1,
            printing_device=printing_device,
            performed_by=self.user,
        )

        with self.assertRaises(ValidationError):
            movement.full_clean()

    def test_compatible_consumable_is_valid_for_printing_device(self):
        from apps.inventory.models import Asset
        from .models import (
            Consumable,
            ConsumableCompatibility,
            PrintingDevice,
            StockMovement,
        )

        asset = Asset.objects.create(
            internal_code="PRINT-TEST-002",
            asset_type=Asset.AssetType.PRINTER,
            brand="Test",
            model="Printer-002",
        )

        printing_device = PrintingDevice.objects.create(
            asset=asset,
        )

        consumable = Consumable.objects.create(
            name="Tóner compatible",
            reference_code="TONER-TEST-004",
            manufacturer="Test",
            model="T-004",
            initial_stock=10,
            minimum_stock=2,
            maximum_stock=20,
        )

        ConsumableCompatibility.objects.create(
            printing_device=printing_device,
            consumable=consumable,
            is_active=True,
        )

        movement = StockMovement(
            consumable=consumable,
            movement_type=StockMovement.MovementType.CONSUMPTION,
            quantity=1,
            printing_device=printing_device,
            performed_by=self.user,
        )

        movement.full_clean()

class ConsumableStockProductIntegrationTests(TestCase):
    def setUp(self):
        from apps.inventory.models import StockCategory, StockProduct

        self.category = StockCategory.objects.create(
            name="Consumibles de impresión",
            code="printing-consumables-test",
        )
        self.stock_product = StockProduct.objects.create(
            name="Tóner integrado",
            reference_code="STOCK-TONER-001",
            category=self.category,
        )

    def create_consumable(self, *, reference_code, stock_product=None):
        from .models import Consumable

        return Consumable.objects.create(
            name="Tóner de prueba",
            reference_code=reference_code,
            manufacturer="Test",
            initial_stock=7,
            stock_product=stock_product,
        )

    def test_legacy_consumable_remains_valid_with_null_stock_product(self):
        consumable = self.create_consumable(reference_code="TONER-NULL-001")

        consumable.full_clean()
        self.assertIsNone(consumable.stock_product)

    def test_link_supports_forward_and_reverse_navigation(self):
        consumable = self.create_consumable(
            reference_code="TONER-LINK-001",
            stock_product=self.stock_product,
        )

        self.assertEqual(consumable.stock_product, self.stock_product)
        self.assertEqual(self.stock_product.printing_consumable, consumable)

    def test_two_consumables_cannot_link_to_same_stock_product(self):
        self.create_consumable(
            reference_code="TONER-UNIQUE-001",
            stock_product=self.stock_product,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_consumable(
                reference_code="TONER-UNIQUE-002",
                stock_product=self.stock_product,
            )

    def test_linked_stock_product_is_protected_from_deletion(self):
        self.create_consumable(
            reference_code="TONER-PROTECT-001",
            stock_product=self.stock_product,
        )

        with self.assertRaises(ProtectedError):
            self.stock_product.delete()

    def test_nullable_link_does_not_change_stock_or_create_inventory_records(self):
        from apps.inventory.models import StockBalance
        from apps.inventory.models import StockMovement as InventoryMovement

        consumable = self.create_consumable(reference_code="TONER-STOCK-001")

        self.assertEqual(consumable.current_stock, 7)
        self.assertEqual(StockBalance.objects.count(), 0)
        self.assertEqual(InventoryMovement.objects.count(), 0)

    def test_printing_stock_movement_and_compatibility_keep_working(self):
        from apps.inventory.models import Asset
        from .models import (
            ConsumableCompatibility,
            PrintingDevice,
            StockMovement,
        )

        user = User.objects.create_user(
            username="printing-integration-user",
            email="printing-integration-user@example.test",
            password="test-password-123",
            role=User.Role.ADMIN,
        )
        consumable = self.create_consumable(
            reference_code="TONER-COMPATIBILITY-001",
            stock_product=self.stock_product,
        )
        asset = Asset.objects.create(
            internal_code="PRINT-INTEGRATION-001",
            asset_type=Asset.AssetType.PRINTER,
            brand="Test",
            model="IntegrationPrinter",
        )
        device = PrintingDevice.objects.create(asset=asset)
        compatibility = ConsumableCompatibility.objects.create(
            printing_device=device,
            consumable=consumable,
            is_active=True,
        )
        movement = StockMovement(
            consumable=consumable,
            movement_type=StockMovement.MovementType.CONSUMPTION,
            quantity=1,
            printing_device=device,
            performed_by=user,
        )

        movement.full_clean()
        movement.save()

        self.assertEqual(compatibility.consumable, consumable)
        self.assertEqual(consumable.current_stock, 6)


class MeterReadingValidationTests(TestCase):
    def setUp(self):
        from apps.inventory.models import Asset
        from .models import PrintingDevice

        self.user = User.objects.create_user(
            username="meter-user",
            email="meter-user@example.test",
            password="test-password-123",
            role=User.Role.ADMIN,
        )

        asset = Asset.objects.create(
            internal_code="PRINT-METER-001",
            asset_type=Asset.AssetType.PRINTER,
            brand="Test",
            model="MeterPrinter",
        )

        self.printing_device = PrintingDevice.objects.create(
            asset=asset,
        )

    def test_meter_reading_cannot_decrease(self):
        from datetime import timedelta

        from django.core.exceptions import ValidationError
        from django.utils import timezone

        from .models import MeterReading

        previous = MeterReading.objects.create(
            printing_device=self.printing_device,
            reading_date=timezone.now() - timedelta(days=1),
            total_counter=1000,
            black_white_counter=800,
            color_counter=200,
            copy_counter=500,
            scan_counter=300,
            registered_by=self.user,
        )

        new_reading = MeterReading(
            printing_device=self.printing_device,
            reading_date=timezone.now(),
            total_counter=900,
            black_white_counter=700,
            color_counter=200,
            copy_counter=500,
            scan_counter=300,
            registered_by=self.user,
        )

        with self.assertRaises(ValidationError):
            new_reading.full_clean()

class MeterReadingHistoricalRegressionTests(TestCase):
    def setUp(self):
        from apps.inventory.models import Asset
        from .models import PrintingDevice

        self.user = User.objects.create_user(
            username="meter-user",
            email="meter-user@example.test",
            password="test-password-123",
            role=User.Role.ADMIN,
        )

        asset = Asset.objects.create(
            internal_code="PRINT-METER-001",
            asset_type=Asset.AssetType.PRINTER,
            brand="Test",
            model="MeterPrinter",
        )

        self.printing_device = PrintingDevice.objects.create(
            asset=asset,
        )

    def test_meter_reading_cannot_decrease(self):
        from datetime import timedelta

        from django.core.exceptions import ValidationError
        from django.utils import timezone

        from .models import MeterReading

        MeterReading.objects.create(
            printing_device=self.printing_device,
            reading_date=timezone.now() - timedelta(days=1),
            total_counter=1000,
            black_white_counter=800,
            color_counter=200,
            copy_counter=500,
            scan_counter=300,
            registered_by=self.user,
        )

        new_reading = MeterReading(
            printing_device=self.printing_device,
            reading_date=timezone.now(),
            total_counter=900,
            black_white_counter=700,
            color_counter=200,
            copy_counter=500,
            scan_counter=300,
            registered_by=self.user,
        )

        with self.assertRaises(ValidationError):
            new_reading.full_clean()

class MaintenanceRecordTests(TestCase):
    def setUp(self):
        from apps.inventory.models import Asset
        from .models import PrintingDevice

        self.user = User.objects.create_user(
            username="maintenance-user",
            email="maintenance-user@example.test",
            password="test-password-123",
            role=User.Role.ADMIN,
        )

        asset = Asset.objects.create(
            internal_code="PRINT-MAINT-001",
            asset_type=Asset.AssetType.PRINTER,
            brand="Test",
            model="MaintenancePrinter",
        )

        self.printing_device = PrintingDevice.objects.create(
            asset=asset,
        )

    def test_completed_maintenance_requires_performed_date(self):
        from django.core.exceptions import ValidationError
        from .models import MaintenanceRecord

        maintenance = MaintenanceRecord(
            printing_device=self.printing_device,
            maintenance_type=MaintenanceRecord.MaintenanceType.PREVENTIVE,
            status=MaintenanceRecord.Status.COMPLETED,
            description="Mantenimiento preventivo de prueba",
            registered_by=self.user,
        )

        with self.assertRaises(ValidationError):
            maintenance.full_clean()
