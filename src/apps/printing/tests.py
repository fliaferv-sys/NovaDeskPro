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

class MeterReadingTests(TestCase):
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

class MeterReadingTests(TestCase):
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