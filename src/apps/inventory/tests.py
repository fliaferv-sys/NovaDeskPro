from unittest.mock import patch
import tempfile
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Branch
from apps.core.models import Department
from apps.notifications.models import Notification
from apps.tickets.models import Ticket

from .models import (
    AcquisitionBatch,
    Asset,
    OrganizationalLocation,
    StockBalance,
    StockCategory,
    StockMovement,
    StockProduct,
    StockEntryDocument,
    StockEntryLine,
    StockEntryOperation,
    StockDelivery,
    StockDeliveryLine,
    TicketStockUsage,
    TicketStockUsageLine,
)
from .services.stock import (
    register_stock_entry,
    register_stock_exit,
    register_stock_movement,
    transfer_stock,
    confirm_stock_entry,
    prepare_stock_delivery,
    complete_stock_delivery,
    confirm_ticket_stock_usage,
)
from .stock_delivery_pdf import generate_stock_delivery_pdf
from .services.notifications import generate_inventory_stock_notifications


User = get_user_model()


class InventoryPermissionsTests(TestCase):
    def setUp(self):
        self.client_user = User.objects.create_user(
            username="cliente_inventario",
            email="cliente_inventario@example.com",
            password="test-password-123",
            role="CLIENT",
        )

        self.admin_user = User.objects.create_user(
            username="admin_inventario",
            email="admin_inventario@example.com",
            password="test-password-123",
            role="ADMIN",
        )

        self.supervisor_user = User.objects.create_user(
            username="supervisor_inventario",
            email="supervisor_inventario@example.com",
            password="test-password-123",
            role="SUPERVISOR",
        )

        self.acquisition_batch = AcquisitionBatch.objects.create(
            code="LOTE-TEST-001",
            date="2026-08-02",
        )

        self.asset = Asset.objects.create(
            internal_code="ACT-TEST-001",
            patrimonial_code="PAT-TEST-001",
            asset_type=Asset.AssetType.DESKTOP,
            brand="Dell",
            model="OptiPlex Test",
            serial_number="SERIAL-TEST-001",
            acquisition_batch=self.acquisition_batch,
        )

        self.client_asset = Asset.objects.create(
            internal_code="ACT-CLIENT-001",
            patrimonial_code="PAT-CLIENT-001",
            asset_type=Asset.AssetType.LAPTOP,
            brand="Lenovo",
            model="ThinkPad Test",
            serial_number="SERIAL-CLIENT-001",
            assigned_user=self.client_user,
            operational_status=Asset.OperationalStatus.MAINTENANCE,
        )

        self.retired_client_asset = Asset.objects.create(
            internal_code="ACT-CLIENT-RETIRED",
            asset_type=Asset.AssetType.DESKTOP,
            assigned_user=self.client_user,
            operational_status=Asset.OperationalStatus.RETIRED,
        )

        self.returned_client_asset = Asset.objects.create(
            internal_code="ACT-CLIENT-RETURNED",
            asset_type=Asset.AssetType.MONITOR,
            assigned_user=None,
        )

    def valid_asset_data(self, **overrides):
        data = {
            "internal_code": "ACT-TEST-001",
            "patrimonial_code": "PAT-TEST-001",
            "asset_type": Asset.AssetType.DESKTOP,
            "brand": "Dell",
            "model": "OptiPlex Test",
            "serial_number": "SERIAL-TEST-001",
            "acquisition_batch": self.acquisition_batch.pk,
            "assigned_user": "",
            "branch": "",
            "physical_location": "",
            "department": "",
            "location": "",
            "operational_status": (
                Asset.OperationalStatus.OPERATIONAL
            ),
            "connection_status": (
                Asset.ConnectionStatus.UNKNOWN
            ),
            "operating_system": "",
            "current_ip": "",
            "mac_address": "",
            "purchase_date": "",
            "warranty_expiration": "",
            "supplier": "",
            "notes": "",
        }

        data.update(overrides)
        return data

    def test_client_cannot_create_asset(self):
        self.client.force_login(self.client_user)

        response = self.client.get(
            reverse("inventory:asset_create")
        )

        self.assertEqual(response.status_code, 403)

    def test_client_cannot_edit_asset(self):
        self.client.force_login(self.client_user)

        response = self.client.get(
            reverse(
                "inventory:asset_update",
                kwargs={"pk": self.asset.pk},
            )
        )

        self.assertEqual(response.status_code, 403)

    def test_client_cannot_update_asset(self):
        self.client.force_login(self.client_user)

        response = self.client.post(
            reverse(
                "inventory:asset_update",
                kwargs={"pk": self.asset.pk},
            ),
            data=self.valid_asset_data(
                brand="Marca prohibida",
            ),
        )

        self.assertEqual(response.status_code, 403)

        self.asset.refresh_from_db()
        self.assertEqual(self.asset.brand, "Dell")

    def test_admin_can_open_asset_create_form(self):
        self.client.force_login(self.admin_user)

        response = self.client.get(
            reverse("inventory:asset_create")
        )

        self.assertEqual(response.status_code, 200)

    def test_admin_can_open_asset_update_form(self):
        self.client.force_login(self.admin_user)

        response = self.client.get(
            reverse(
                "inventory:asset_update",
                kwargs={"pk": self.asset.pk},
            )
        )

        self.assertEqual(response.status_code, 200)

    def test_admin_can_update_asset(self):
        self.client.force_login(self.admin_user)

        response = self.client.post(
            reverse(
                "inventory:asset_update",
                kwargs={"pk": self.asset.pk},
            ),
            data=self.valid_asset_data(
                brand="Lenovo",
                model="ThinkCentre Test",
            ),
        )

        self.assertEqual(response.status_code, 302)

        self.asset.refresh_from_db()
        self.assertEqual(self.asset.brand, "Lenovo")
        self.assertEqual(
            self.asset.model,
            "ThinkCentre Test",
        )

    def test_my_assets_requires_authentication(self):
        response = self.client.get(reverse("inventory:my_asset_list"))

        self.assertEqual(response.status_code, 302)

    def test_client_sees_only_assets_assigned_to_own_user(self):
        self.client.force_login(self.client_user)

        response = self.client.get(reverse("inventory:my_asset_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.client_asset.internal_code)
        self.assertNotContains(response, self.asset.internal_code)
        self.assertNotContains(response, self.retired_client_asset.internal_code)
        self.assertNotContains(response, self.returned_client_asset.internal_code)
        self.assertEqual(list(response.context["assets"]), [self.client_asset])

    def test_client_cannot_change_asset_scope_with_query_parameters(self):
        self.client.force_login(self.client_user)

        response = self.client.get(
            reverse("inventory:my_asset_list"),
            {"user": self.admin_user.pk, "asset": self.asset.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.asset.internal_code)
        self.assertEqual(list(response.context["assets"]), [self.client_asset])

    def test_client_cannot_open_another_users_asset_detail(self):
        self.client.force_login(self.client_user)

        response = self.client.get(
            reverse("inventory:asset_detail", kwargs={"pk": self.asset.pk})
        )

        self.assertEqual(response.status_code, 403)

    def test_admin_inventory_list_remains_available(self):
        for user in (self.admin_user, self.supervisor_user):
            with self.subTest(role=user.role):
                self.client.force_login(user)

                response = self.client.get(reverse("inventory:asset_list"))

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, self.asset.internal_code)


class GenericStockTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="stock_operator",
            email="stock_operator@example.com",
            password="test-password-123",
            role="ADMIN",
        )
        self.branch = Branch.objects.create(
            code="STOCK-HQ",
            name="Sede de stock",
            branch_type=Branch.BranchType.HEADQUARTERS,
        )
        self.location = OrganizationalLocation.objects.create(
            branch=self.branch,
            code="STOCK-WH",
            name="Depósito de stock",
            location_type=OrganizationalLocation.LocationType.WAREHOUSE,
        )
        self.category = StockCategory.objects.create(
            name="Periféricos",
            code="perifericos",
            description="Accesorios informáticos",
        )
        self.product = StockProduct.objects.create(
            name="Mouse Logitech M90",
            reference_code="MOUSE-LOG-M90",
            category=self.category,
            brand="Logitech",
            model="M90",
            unit_of_measure=StockProduct.UnitOfMeasure.UNIT,
            minimum_stock=3,
            default_location=self.location,
        )
        self.balance = StockBalance.objects.create(
            product=self.product,
            branch=self.branch,
            organizational_location=self.location,
        )
        self.destination_branch = Branch.objects.create(
            code="STOCK-BRANCH-2",
            name="Sede destino",
            branch_type=Branch.BranchType.BRANCH,
        )
        self.destination_location = OrganizationalLocation.objects.create(
            branch=self.destination_branch,
            code="STOCK-WH-2",
            name="Depósito destino",
            location_type=OrganizationalLocation.LocationType.WAREHOUSE,
        )

    def register(self, *, quantity, direction, reason):
        return register_stock_movement(
            balance=self.balance,
            quantity=quantity,
            direction=direction,
            reason=reason,
            performed_by=self.user,
        )

    def test_category_can_be_created(self):
        self.assertEqual(self.category.code, "perifericos")
        self.assertTrue(self.category.is_active)

    def test_product_can_be_created(self):
        self.assertEqual(self.product.category, self.category)
        self.assertEqual(self.product.default_location, self.location)

    def test_balance_starts_at_zero(self):
        self.assertEqual(self.balance.quantity, 0)

    def test_entry_creates_movement_and_updates_balance(self):
        movement = self.register(
            quantity=10,
            direction=StockMovement.Direction.ENTRY,
            reason=StockMovement.Reason.PURCHASE,
        )

        self.balance.refresh_from_db()
        self.assertEqual(self.balance.quantity, 10)
        self.assertEqual(movement.direction, StockMovement.Direction.ENTRY)
        self.assertEqual(movement.quantity, 10)

    def test_second_entry_accumulates_stock(self):
        self.register(
            quantity=10,
            direction=StockMovement.Direction.ENTRY,
            reason=StockMovement.Reason.PURCHASE,
        )
        self.register(
            quantity=5,
            direction=StockMovement.Direction.ENTRY,
            reason=StockMovement.Reason.RETURN,
        )

        self.balance.refresh_from_db()
        self.assertEqual(self.balance.quantity, 15)

    def test_valid_exit_reduces_stock(self):
        self.register(
            quantity=15,
            direction=StockMovement.Direction.ENTRY,
            reason=StockMovement.Reason.PURCHASE,
        )
        movement = self.register(
            quantity=3,
            direction=StockMovement.Direction.EXIT,
            reason=StockMovement.Reason.DELIVERY,
        )

        self.balance.refresh_from_db()
        self.assertEqual(self.balance.quantity, 12)
        self.assertEqual(movement.direction, StockMovement.Direction.EXIT)

    def test_exit_above_stock_rolls_back_without_movement(self):
        self.register(
            quantity=10,
            direction=StockMovement.Direction.ENTRY,
            reason=StockMovement.Reason.PURCHASE,
        )
        movement_count = StockMovement.objects.count()

        with self.assertRaises(ValidationError):
            self.register(
                quantity=11,
                direction=StockMovement.Direction.EXIT,
                reason=StockMovement.Reason.CONSUMPTION,
            )

        self.balance.refresh_from_db()
        self.assertEqual(self.balance.quantity, 10)
        self.assertEqual(StockMovement.objects.count(), movement_count)

    def test_zero_quantity_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.register(
                quantity=0,
                direction=StockMovement.Direction.ENTRY,
                reason=StockMovement.Reason.PURCHASE,
            )
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_negative_quantity_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.register(
                quantity=-1,
                direction=StockMovement.Direction.ENTRY,
                reason=StockMovement.Reason.PURCHASE,
            )
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_balance_is_unique_per_product_branch_and_location(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                StockBalance.objects.create(
                    product=self.product,
                    branch=self.branch,
                    organizational_location=self.location,
                )

    def test_asset_model_continues_working(self):
        asset = Asset.objects.create(
            internal_code="ASSET-STOCK-REGRESSION",
            asset_type=Asset.AssetType.UPS,
            branch=self.branch,
            physical_location=self.location,
        )

        self.assertEqual(asset.internal_code, "ASSET-STOCK-REGRESSION")

    def test_entry_creates_missing_balance(self):
        self.balance.delete()

        movement = register_stock_entry(
            product=self.product,
            branch=self.branch,
            organizational_location=self.location,
            quantity=8,
            reason=StockMovement.Reason.INITIAL_ENTRY,
            performed_by=self.user,
        )

        balance = StockBalance.objects.get(
            product=self.product,
            branch=self.branch,
            organizational_location=self.location,
        )
        self.assertEqual(balance.quantity, 8)
        self.assertEqual(movement.balance, balance)
        self.assertEqual(movement.reason, StockMovement.Reason.INITIAL_ENTRY)

    def test_exact_exit_leaves_zero_balance(self):
        register_stock_entry(
            product=self.product,
            branch=self.branch,
            organizational_location=self.location,
            quantity=6,
            reason=StockMovement.Reason.PURCHASE,
            performed_by=self.user,
        )
        register_stock_exit(
            product=self.product,
            branch=self.branch,
            organizational_location=self.location,
            quantity=6,
            reason=StockMovement.Reason.CONSUMPTION,
            performed_by=self.user,
        )

        self.balance.refresh_from_db()
        self.assertEqual(self.balance.quantity, 0)

    def test_return_is_an_explicit_entry(self):
        movement = register_stock_entry(
            product=self.product,
            branch=self.branch,
            organizational_location=self.location,
            quantity=2,
            reason=StockMovement.Reason.RETURN,
            performed_by=self.user,
        )

        self.assertEqual(movement.direction, StockMovement.Direction.ENTRY)
        self.assertEqual(movement.reason, StockMovement.Reason.RETURN)

    def test_positive_and_negative_adjustments_are_auditable(self):
        positive = register_stock_entry(
            product=self.product,
            branch=self.branch,
            organizational_location=self.location,
            quantity=7,
            reason=StockMovement.Reason.POSITIVE_ADJUSTMENT,
            performed_by=self.user,
            observation="Corrección de conteo",
        )
        negative = register_stock_exit(
            product=self.product,
            branch=self.branch,
            organizational_location=self.location,
            quantity=2,
            reason=StockMovement.Reason.NEGATIVE_ADJUSTMENT,
            performed_by=self.user,
            observation="Corrección de conteo",
        )

        self.balance.refresh_from_db()
        self.assertEqual(self.balance.quantity, 5)
        self.assertEqual(positive.direction, StockMovement.Direction.ENTRY)
        self.assertEqual(negative.direction, StockMovement.Direction.EXIT)

    def test_write_off_is_an_exit_and_validates_availability(self):
        self.register(
            quantity=4,
            direction=StockMovement.Direction.ENTRY,
            reason=StockMovement.Reason.PURCHASE,
        )
        movement = register_stock_exit(
            product=self.product,
            branch=self.branch,
            organizational_location=self.location,
            quantity=3,
            reason=StockMovement.Reason.WRITE_OFF,
            performed_by=self.user,
        )

        self.balance.refresh_from_db()
        self.assertEqual(self.balance.quantity, 1)
        self.assertEqual(movement.reason, StockMovement.Reason.WRITE_OFF)

    def test_valid_transfer_updates_both_balances_and_history(self):
        self.register(
            quantity=10,
            direction=StockMovement.Direction.ENTRY,
            reason=StockMovement.Reason.PURCHASE,
        )
        destination_balance = StockBalance.objects.create(
            product=self.product,
            branch=self.destination_branch,
            organizational_location=self.destination_location,
            quantity=1,
        )

        exit_movement, entry_movement = transfer_stock(
            product=self.product,
            source_branch=self.branch,
            source_location=self.location,
            destination_branch=self.destination_branch,
            destination_location=self.destination_location,
            quantity=4,
            performed_by=self.user,
            document_reference="TR-001",
        )

        self.balance.refresh_from_db()
        destination_balance.refresh_from_db()
        self.assertEqual(self.balance.quantity, 6)
        self.assertEqual(destination_balance.quantity, 5)
        self.assertEqual(exit_movement.direction, StockMovement.Direction.EXIT)
        self.assertEqual(entry_movement.direction, StockMovement.Direction.ENTRY)
        self.assertEqual(exit_movement.reason, StockMovement.Reason.TRANSFER)
        self.assertEqual(entry_movement.reason, StockMovement.Reason.TRANSFER)

    def test_transfer_creates_destination_balance(self):
        self.register(
            quantity=5,
            direction=StockMovement.Direction.ENTRY,
            reason=StockMovement.Reason.PURCHASE,
        )

        transfer_stock(
            product=self.product,
            source_branch=self.branch,
            source_location=self.location,
            destination_branch=self.destination_branch,
            destination_location=self.destination_location,
            quantity=2,
            performed_by=self.user,
        )

        destination_balance = StockBalance.objects.get(
            product=self.product,
            branch=self.destination_branch,
            organizational_location=self.destination_location,
        )
        self.assertEqual(destination_balance.quantity, 2)

    def test_insufficient_transfer_rolls_back_destination_and_movements(self):
        self.register(
            quantity=3,
            direction=StockMovement.Direction.ENTRY,
            reason=StockMovement.Reason.PURCHASE,
        )
        movement_count = StockMovement.objects.count()

        with self.assertRaises(ValidationError):
            transfer_stock(
                product=self.product,
                source_branch=self.branch,
                source_location=self.location,
                destination_branch=self.destination_branch,
                destination_location=self.destination_location,
                quantity=4,
                performed_by=self.user,
            )

        self.balance.refresh_from_db()
        self.assertEqual(self.balance.quantity, 3)
        self.assertEqual(StockMovement.objects.count(), movement_count)
        self.assertFalse(
            StockBalance.objects.filter(
                product=self.product,
                branch=self.destination_branch,
                organizational_location=self.destination_location,
            ).exists()
        )

    def test_transfer_rejects_same_origin_and_destination(self):
        with self.assertRaises(ValidationError):
            transfer_stock(
                product=self.product,
                source_branch=self.branch,
                source_location=self.location,
                destination_branch=self.branch,
                destination_location=self.location,
                quantity=1,
                performed_by=self.user,
            )

        self.assertEqual(StockMovement.objects.count(), 0)

    def test_transfer_rolls_back_if_second_movement_creation_fails(self):
        self.register(
            quantity=5,
            direction=StockMovement.Direction.ENTRY,
            reason=StockMovement.Reason.PURCHASE,
        )
        destination_balance = StockBalance.objects.create(
            product=self.product,
            branch=self.destination_branch,
            organizational_location=self.destination_location,
        )
        movement_count = StockMovement.objects.count()
        original_create = StockMovement.objects.create
        calls = 0

        def fail_second_movement(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("Fallo simulado al crear el segundo movimiento")
            return original_create(**kwargs)

        with patch.object(
            StockMovement.objects,
            "create",
            side_effect=fail_second_movement,
        ):
            with self.assertRaises(RuntimeError):
                transfer_stock(
                    product=self.product,
                    source_branch=self.branch,
                    source_location=self.location,
                    destination_branch=self.destination_branch,
                    destination_location=self.destination_location,
                    quantity=2,
                    performed_by=self.user,
                )

        self.balance.refresh_from_db()
        destination_balance.refresh_from_db()
        self.assertEqual(self.balance.quantity, 5)
        self.assertEqual(destination_balance.quantity, 0)
        self.assertEqual(StockMovement.objects.count(), movement_count)

    def test_service_rejects_product_incoherent_with_balance(self):
        other_product = StockProduct.objects.create(
            name="Teclado",
            reference_code="KEYBOARD-001",
            category=self.category,
        )

        with self.assertRaises(ValidationError):
            register_stock_movement(
                balance=self.balance,
                product=other_product,
                quantity=1,
                direction=StockMovement.Direction.ENTRY,
                reason=StockMovement.Reason.PURCHASE,
                performed_by=self.user,
            )

        self.balance.refresh_from_db()
        self.assertEqual(self.balance.quantity, 0)

    def test_entry_rejects_location_from_another_branch(self):
        with self.assertRaises(ValidationError):
            register_stock_entry(
                product=self.product,
                branch=self.branch,
                organizational_location=self.destination_location,
                quantity=1,
                reason=StockMovement.Reason.PURCHASE,
                performed_by=self.user,
            )

        self.assertEqual(StockMovement.objects.count(), 0)

    def test_confirmed_movement_cannot_be_edited_or_deleted(self):
        movement = self.register(
            quantity=1,
            direction=StockMovement.Direction.ENTRY,
            reason=StockMovement.Reason.PURCHASE,
        )
        movement.observation = "Intento de edición"

        with self.assertRaises(ValidationError):
            movement.save()
        with self.assertRaises(ValidationError):
            movement.delete()

        self.assertEqual(StockMovement.objects.count(), 1)


class StockAdministrationTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="stock_admin_ui",
            email="stock_admin_ui@example.com",
            password="test-password-123",
            role="ADMIN",
        )
        self.supervisor_user = User.objects.create_user(
            username="stock_supervisor_ui",
            email="stock_supervisor_ui@example.com",
            password="test-password-123",
            role="SUPERVISOR",
        )
        self.branch = Branch.objects.create(code="UI-HQ", name="Sede UI")
        self.location = OrganizationalLocation.objects.create(
            branch=self.branch,
            code="UI-WH",
            name="Depósito UI",
            location_type=OrganizationalLocation.LocationType.WAREHOUSE,
        )
        self.other_branch = Branch.objects.create(code="UI-B2", name="Sede UI 2")
        self.other_location = OrganizationalLocation.objects.create(
            branch=self.other_branch,
            code="UI-WH-2",
            name="Depósito UI 2",
            location_type=OrganizationalLocation.LocationType.WAREHOUSE,
        )
        self.category = StockCategory.objects.create(
            name="Accesorios UI", code="accesorios-ui"
        )
        self.product = StockProduct.objects.create(
            name="Mouse UI",
            reference_code="UI-MOUSE-001",
            category=self.category,
            brand="Logitech",
            model="M90",
            minimum_stock=2,
        )

    def login_admin(self):
        self.client.force_login(self.admin_user)

    def product_data(self, **overrides):
        data = {
            "name": "Teclado UI",
            "reference_code": "UI-KEYBOARD-001",
            "category": self.category.pk,
            "brand": "Logitech",
            "model": "K120",
            "description": "Teclado de prueba",
            "unit_of_measure": StockProduct.UnitOfMeasure.UNIT,
            "minimum_stock": 3,
            "is_active": True,
            "default_location": self.location.pk,
        }
        data.update(overrides)
        return data

    def operation_data(self, **overrides):
        data = {
            "product": self.product.pk,
            "branch": self.branch.pk,
            "organizational_location": self.location.pk,
            "quantity": 5,
            "reason": StockMovement.Reason.PURCHASE,
            "observation": "Operación web",
            "document_reference": "DOC-UI-1",
        }
        data.update(overrides)
        return data

    def test_product_list_search_and_filters(self):
        self.login_admin()
        response = self.client.get(
            reverse("inventory:stock_product_list"),
            {"q": "M90", "category": self.category.pk, "active": "true"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.product.reference_code)

    def test_product_create_duplicate_validation_edit_and_deactivation(self):
        self.login_admin()
        create_response = self.client.post(
            reverse("inventory:stock_product_create"), self.product_data()
        )
        created = StockProduct.objects.get(reference_code="UI-KEYBOARD-001")
        self.assertRedirects(
            create_response,
            reverse("inventory:stock_product_detail", args=[created.pk]),
        )

        duplicate_response = self.client.post(
            reverse("inventory:stock_product_create"),
            self.product_data(name="Duplicado"),
        )
        self.assertEqual(duplicate_response.status_code, 200)
        self.assertFormError(
            duplicate_response.context["form"],
            "reference_code",
            "Ya existe Producto de stock con este Código de referencia.",
        )

        update_response = self.client.post(
            reverse("inventory:stock_product_update", args=[created.pk]),
            self.product_data(name="Teclado actualizado", is_active=False),
        )
        created.refresh_from_db()
        self.assertEqual(update_response.status_code, 302)
        self.assertEqual(created.name, "Teclado actualizado")
        self.assertFalse(created.is_active)

    def test_category_create_edit_and_deactivate(self):
        self.login_admin()
        response = self.client.post(
            reverse("inventory:stock_category_create"),
            {"name": "Cables", "code": "cables", "description": "", "is_active": True},
        )
        category = StockCategory.objects.get(code="cables")
        self.assertRedirects(response, reverse("inventory:stock_category_list"))

        response = self.client.post(
            reverse("inventory:stock_category_update", args=[category.pk]),
            {"name": "Cables varios", "code": "cables", "description": "", "is_active": False},
        )
        category.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(category.name, "Cables varios")
        self.assertFalse(category.is_active)

    def test_stock_views_permissions(self):
        urls = [
            reverse("inventory:stock_product_list"),
            reverse("inventory:stock_product_create"),
            reverse("inventory:stock_entry"),
            reverse("inventory:stock_exit"),
            reverse("inventory:stock_transfer"),
            reverse("inventory:stock_movement_list"),
        ]
        for role in ("CLIENT", "TECHNICIAN", "AUDITOR"):
            user = User.objects.create_user(
                username=f"stock_forbidden_{role.lower()}",
                email=f"stock_forbidden_{role.lower()}@example.com",
                role=role,
            )
            self.client.force_login(user)
            for url in urls:
                with self.subTest(role=role, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)
        for user in (self.admin_user, self.supervisor_user):
            self.client.force_login(user)
            self.assertEqual(
                self.client.get(reverse("inventory:stock_product_list")).status_code,
                200,
            )

    def test_entry_creates_balance_and_second_entry_accumulates(self):
        self.login_admin()
        for quantity in (5, 2):
            response = self.client.post(
                reverse("inventory:stock_entry"),
                self.operation_data(quantity=quantity),
            )
            self.assertEqual(response.status_code, 302)
        balance = StockBalance.objects.get(product=self.product)
        self.assertEqual(balance.quantity, 7)
        self.assertEqual(balance.movements.count(), 2)

    def test_entry_rejects_invalid_quantity_and_location(self):
        self.login_admin()
        response = self.client.post(
            reverse("inventory:stock_entry"), self.operation_data(quantity=0)
        )
        self.assertEqual(response.status_code, 200)
        response = self.client.post(
            reverse("inventory:stock_entry"),
            self.operation_data(organizational_location=self.other_location.pk),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(StockMovement.objects.exists())

    def test_exit_valid_exact_zero_and_insufficient_rollback(self):
        register_stock_entry(
            product=self.product,
            branch=self.branch,
            organizational_location=self.location,
            quantity=5,
            reason=StockMovement.Reason.PURCHASE,
            performed_by=self.admin_user,
        )
        self.login_admin()
        response = self.client.post(
            reverse("inventory:stock_exit"),
            self.operation_data(quantity=5, reason=StockMovement.Reason.DELIVERY),
        )
        self.assertEqual(response.status_code, 302)
        balance = StockBalance.objects.get(product=self.product)
        self.assertEqual(balance.quantity, 0)
        movement_count = StockMovement.objects.count()

        response = self.client.post(
            reverse("inventory:stock_exit"),
            self.operation_data(quantity=1, reason=StockMovement.Reason.DELIVERY),
        )
        balance.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(balance.quantity, 0)
        self.assertEqual(StockMovement.objects.count(), movement_count)

    def test_transfer_valid_new_destination_and_invalid_operations(self):
        register_stock_entry(
            product=self.product,
            branch=self.branch,
            organizational_location=self.location,
            quantity=5,
            reason=StockMovement.Reason.PURCHASE,
            performed_by=self.admin_user,
        )
        self.login_admin()
        data = {
            "product": self.product.pk,
            "source_branch": self.branch.pk,
            "source_location": self.location.pk,
            "destination_branch": self.other_branch.pk,
            "destination_location": self.other_location.pk,
            "quantity": 2,
            "observation": "Transferencia UI",
            "document_reference": "TR-UI",
        }
        response = self.client.post(reverse("inventory:stock_transfer"), data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            StockBalance.objects.get(
                product=self.product, organizational_location=self.other_location
            ).quantity,
            2,
        )

        movement_count = StockMovement.objects.count()
        response = self.client.post(
            reverse("inventory:stock_transfer"), {**data, "quantity": 99}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StockMovement.objects.count(), movement_count)
        response = self.client.post(
            reverse("inventory:stock_transfer"),
            {
                **data,
                "destination_branch": self.branch.pk,
                "destination_location": self.location.pk,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StockMovement.objects.count(), movement_count)

    def test_product_detail_and_movement_history_are_read_only_and_ordered(self):
        first = register_stock_entry(
            product=self.product,
            branch=self.branch,
            organizational_location=self.location,
            quantity=3,
            reason=StockMovement.Reason.PURCHASE,
            performed_by=self.admin_user,
            observation="Primero",
        )
        second = register_stock_exit(
            product=self.product,
            branch=self.branch,
            organizational_location=self.location,
            quantity=1,
            reason=StockMovement.Reason.CONSUMPTION,
            performed_by=self.admin_user,
            observation="Segundo",
        )
        self.login_admin()
        detail = self.client.get(
            reverse("inventory:stock_product_detail", args=[self.product.pk])
        )
        self.assertContains(detail, "Primero")
        self.assertContains(detail, "Segundo")
        self.assertEqual(detail.context["total_stock"], 2)

        history = self.client.get(
            reverse("inventory:stock_movement_list"),
            {"direction": StockMovement.Direction.EXIT, "q": "M90"},
        )
        movements = list(history.context["movements"])
        self.assertEqual(movements, [second])
        self.assertNotContains(history, "Editar movimiento")
        self.assertTrue(first.movement_date <= second.movement_date)


class DocumentedStockEntryTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="entry_admin", email="entry_admin@example.com", password="pass", role="ADMIN")
        self.supervisor = User.objects.create_user(username="entry_super", email="entry_super@example.com", password="pass", role="SUPERVISOR")
        self.branch = Branch.objects.create(code="ENTRY-HQ", name="Sede entradas")
        self.location = OrganizationalLocation.objects.create(branch=self.branch, code="ENTRY-WH", name="Depósito entradas", location_type=OrganizationalLocation.LocationType.WAREHOUSE)
        self.category = StockCategory.objects.create(name="Entradas", code="entradas-doc")
        self.product = StockProduct.objects.create(name="Mouse documentado", reference_code="DOC-MOUSE", category=self.category)
        self.product_two = StockProduct.objects.create(name="Teclado documentado", reference_code="DOC-KEY", category=self.category)

    def make_entry(self, **kwargs):
        data = {"reason": StockMovement.Reason.PURCHASE, "created_by": self.admin, "supplier": "Proveedor SA"}
        data.update(kwargs)
        return StockEntryOperation.objects.create(**data)

    def add_line(self, entry, product=None, quantity=2):
        return StockEntryLine.objects.create(entry=entry, product=product or self.product, branch=self.branch, organizational_location=self.location, quantity=quantity)

    def test_draft_number_lines_and_document(self):
        entry = self.make_entry()
        self.add_line(entry)
        self.add_line(entry, self.product_two, 3)
        document = StockEntryDocument.objects.create(entry=entry, document_type=StockEntryDocument.DocumentType.INVOICE, file="inventory/stock_entries/factura.pdf", uploaded_by=self.admin)
        self.assertRegex(entry.number, r"^STK-IN-\d{6}$")
        self.assertEqual(entry.status, StockEntryOperation.Status.DRAFT)
        self.assertEqual(entry.lines.count(), 2)
        self.assertEqual(document.uploaded_by, self.admin)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_confirm_multiple_lines_updates_balances_and_traceability(self):
        entry = self.make_entry()
        self.add_line(entry, self.product, 4)
        self.add_line(entry, self.product_two, 7)
        confirmed = confirm_stock_entry(entry=entry, confirmed_by=self.supervisor)
        self.assertEqual(confirmed.status, StockEntryOperation.Status.CONFIRMED)
        self.assertEqual(confirmed.confirmed_by, self.supervisor)
        self.assertIsNotNone(confirmed.confirmed_at)
        self.assertEqual(StockMovement.objects.filter(document_reference=entry.number).count(), 2)
        self.assertEqual(StockBalance.objects.get(product=self.product).quantity, 4)
        self.assertEqual(StockBalance.objects.get(product=self.product_two).quantity, 7)
        self.assertFalse(confirmed.lines.filter(movement=None).exists())

    def test_confirmation_rejects_empty_and_double_confirmation(self):
        empty = self.make_entry()
        with self.assertRaises(ValidationError):
            confirm_stock_entry(entry=empty, confirmed_by=self.admin)
        entry = self.make_entry()
        self.add_line(entry)
        confirm_stock_entry(entry=entry, confirmed_by=self.admin)
        with self.assertRaises(ValidationError):
            confirm_stock_entry(entry=entry, confirmed_by=self.admin)

    def test_confirmed_entry_and_lines_are_immutable(self):
        entry = self.make_entry()
        line = self.add_line(entry)
        confirm_stock_entry(entry=entry, confirmed_by=self.admin)
        entry.refresh_from_db()
        entry.supplier = "Cambio"
        with self.assertRaises(ValidationError):
            entry.save()
        line.refresh_from_db()
        line.quantity = 99
        with self.assertRaises(ValidationError):
            line.save()
        with self.assertRaises(ValidationError):
            line.delete()

    def test_invalid_line_quantity_location_and_inactive_product(self):
        entry = self.make_entry()
        with self.assertRaises(ValidationError):
            self.add_line(entry, quantity=0)
        other = Branch.objects.create(code="ENTRY-B2", name="Otra sede")
        with self.assertRaises(ValidationError):
            StockEntryLine.objects.create(entry=entry, product=self.product, branch=other, organizational_location=self.location, quantity=1)
        self.product.is_active = False
        self.product.save()
        with self.assertRaises(ValidationError):
            self.add_line(entry)

    def test_atomic_rollback_when_intermediate_line_fails(self):
        entry = self.make_entry()
        self.add_line(entry, self.product, 2)
        self.add_line(entry, self.product_two, 3)
        from .services import stock as stock_service
        original = stock_service.register_stock_entry
        calls = {"count": 0}
        def fail_second(**kwargs):
            calls["count"] += 1
            if calls["count"] == 2:
                raise ValidationError("Fallo simulado")
            return original(**kwargs)
        with patch("apps.inventory.services.stock.register_stock_entry", side_effect=fail_second):
            with self.assertRaises(ValidationError):
                confirm_stock_entry(entry=entry, confirmed_by=self.admin)
        entry.refresh_from_db()
        self.assertEqual(entry.status, StockEntryOperation.Status.DRAFT)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(StockBalance.objects.count(), 0)

    def test_views_permissions_and_post_state_actions(self):
        entry = self.make_entry()
        urls = [reverse("inventory:documented_stock_entry_list"), reverse("inventory:documented_stock_entry_detail", args=[entry.pk]), reverse("inventory:documented_stock_entry_add_line", args=[entry.pk])]
        for role in ("CLIENT", "TECHNICIAN"):
            user = User.objects.create_user(username=f"entry_{role.lower()}", email=f"entry_{role.lower()}@example.com", role=role)
            self.client.force_login(user)
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 403)
        for user in (self.admin, self.supervisor):
            self.client.force_login(user)
            self.assertEqual(self.client.get(urls[0]).status_code, 200)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("inventory:documented_stock_entry_confirm", args=[entry.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("inventory:documented_stock_entry_cancel", args=[entry.pk])).status_code, 403)


class StockDeliveryTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="delivery_admin", email="delivery_admin@example.com", password="pass", role="ADMIN", first_name="Ana", last_name="Admin")
        self.supervisor = User.objects.create_user(username="delivery_super", email="delivery_super@example.com", password="pass", role="SUPERVISOR")
        self.recipient = User.objects.create_user(username="delivery_recipient", email="delivery_recipient@example.com", first_name="Juan", last_name="Pérez", role="CLIENT")
        self.department = Department.objects.create(name="DTI entregas", code="DTI-DEL")
        self.branch = Branch.objects.create(code="DEL-HQ", name="Sede entregas")
        self.location = OrganizationalLocation.objects.create(branch=self.branch, code="DEL-WH", name="Depósito entregas", location_type=OrganizationalLocation.LocationType.WAREHOUSE)
        category = StockCategory.objects.create(name="Entrega", code="delivery-tests")
        self.product = StockProduct.objects.create(name="Mouse Logitech M90", reference_code="DEL-MOUSE", category=category, brand="Logitech", model="M90")
        self.product_two = StockProduct.objects.create(name="Teclado Logitech K120", reference_code="DEL-KEY", category=category)

    def make_delivery(self):
        return StockDelivery.objects.create(recipient=self.recipient, department=self.department, branch=self.branch, location=self.location, delivery_responsible=self.admin, created_by=self.admin)

    def add_line(self, delivery, product=None, quantity=2):
        return StockDeliveryLine.objects.create(delivery=delivery, product=product or self.product, quantity=quantity, source_branch=self.branch, source_location=self.location)

    def stock(self, product, quantity):
        return StockBalance.objects.create(product=product, branch=self.branch, organizational_location=self.location, quantity=quantity)

    def test_draft_multiple_lines_edit_and_delete(self):
        delivery = self.make_delivery()
        first = self.add_line(delivery)
        self.add_line(delivery, self.product_two, 3)
        self.assertRegex(delivery.number, r"^STK-OUT-\d{6}$")
        self.assertEqual(delivery.lines.count(), 2)
        first.delete()
        delivery.observations = "Editado"
        delivery.save()
        self.assertEqual(delivery.lines.count(), 1)

    def test_prepare_requires_lines_and_captures_history(self):
        empty = self.make_delivery()
        with self.assertRaises(ValidationError):
            prepare_stock_delivery(delivery=empty)
        delivery = self.make_delivery()
        line = self.add_line(delivery)
        prepared = prepare_stock_delivery(delivery=delivery)
        line.refresh_from_db()
        self.assertEqual(prepared.status, StockDelivery.Status.PREPARED)
        self.assertEqual(prepared.recipient_name, "Juan Pérez")
        self.assertEqual(prepared.department_name, self.department.name)
        self.assertEqual(line.product_sku, self.product.reference_code)

    def test_complete_multiple_lines_exact_zero_and_traceability(self):
        delivery = self.make_delivery()
        self.add_line(delivery, self.product, 2)
        self.add_line(delivery, self.product_two, 3)
        self.stock(self.product, 2)
        self.stock(self.product_two, 5)
        prepare_stock_delivery(delivery=delivery)
        completed = complete_stock_delivery(delivery=delivery, completed_by=self.supervisor)
        self.assertEqual(completed.status, StockDelivery.Status.COMPLETED)
        self.assertEqual(completed.completed_by, self.supervisor)
        self.assertIsNotNone(completed.completed_at)
        self.assertEqual(StockBalance.objects.get(product=self.product).quantity, 0)
        self.assertEqual(StockBalance.objects.get(product=self.product_two).quantity, 2)
        self.assertEqual(StockMovement.objects.filter(document_reference=delivery.number, recipient=self.recipient, department=self.department).count(), 2)

    def test_insufficient_stock_has_no_partial_effect(self):
        delivery = self.make_delivery()
        self.add_line(delivery, self.product, 2)
        self.add_line(delivery, self.product_two, 4)
        self.stock(self.product, 10)
        self.stock(self.product_two, 1)
        prepare_stock_delivery(delivery=delivery)
        with self.assertRaises(ValidationError):
            complete_stock_delivery(delivery=delivery, completed_by=self.admin)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, StockDelivery.Status.PREPARED)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(StockBalance.objects.get(product=self.product).quantity, 10)

    def test_intermediate_failure_rolls_back(self):
        delivery = self.make_delivery()
        self.add_line(delivery, self.product, 2)
        self.add_line(delivery, self.product_two, 2)
        self.stock(self.product, 5)
        self.stock(self.product_two, 5)
        prepare_stock_delivery(delivery=delivery)
        from .services import stock as stock_service
        original = stock_service.register_stock_exit
        calls = {"value": 0}
        def fail_second(**kwargs):
            calls["value"] += 1
            if calls["value"] == 2:
                raise ValidationError("Fallo simulado")
            return original(**kwargs)
        with patch("apps.inventory.services.stock.register_stock_exit", side_effect=fail_second):
            with self.assertRaises(ValidationError):
                complete_stock_delivery(delivery=delivery, completed_by=self.admin)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(StockBalance.objects.get(product=self.product).quantity, 5)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, StockDelivery.Status.PREPARED)

    def test_completed_delivery_is_immutable_and_not_repeatable(self):
        delivery = self.make_delivery()
        line = self.add_line(delivery, quantity=1)
        self.stock(self.product, 2)
        prepare_stock_delivery(delivery=delivery)
        complete_stock_delivery(delivery=delivery, completed_by=self.admin)
        delivery.refresh_from_db()
        delivery.observations = "Cambio"
        with self.assertRaises(ValidationError):
            delivery.save()
        line.refresh_from_db()
        line.quantity = 2
        with self.assertRaises(ValidationError):
            line.save()
        with self.assertRaises(ValidationError):
            line.delete()
        with self.assertRaises(ValidationError):
            complete_stock_delivery(delivery=delivery, completed_by=self.admin)

    def test_pdf_contains_delivery_data_and_excludes_asset_fields(self):
        delivery = self.make_delivery()
        self.add_line(delivery, quantity=1)
        prepare_stock_delivery(delivery=delivery)
        delivery.refresh_from_db()
        content = generate_stock_delivery_pdf(delivery).getvalue()
        self.assertTrue(content.startswith(b"%PDF"))
        self.assertIn(delivery.number.encode(), content)
        self.assertIn(b"Juan", content)
        self.assertIn(b"Mouse Logitech M90", content)
        self.assertNotIn(b"Hostname", content)
        self.assertNotIn(b"Patrimonio", content)

    def test_permissions_and_pdf_response(self):
        delivery = self.make_delivery()
        self.add_line(delivery)
        prepare_stock_delivery(delivery=delivery)
        list_url = reverse("inventory:stock_delivery_list")
        for role in ("CLIENT", "TECHNICIAN", "AUDITOR"):
            user = User.objects.create_user(username=f"delivery_{role.lower()}", email=f"delivery_{role.lower()}@example.com", role=role)
            self.client.force_login(user)
            self.assertEqual(self.client.get(list_url).status_code, 403)
        for user in (self.admin, self.supervisor):
            self.client.force_login(user)
            self.assertEqual(self.client.get(list_url).status_code, 200)
        response = self.client.get(reverse("inventory:stock_delivery_pdf", args=[delivery.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_signed_document_upload_and_protected_download(self):
        delivery = self.make_delivery()
        self.add_line(delivery)
        prepare_stock_delivery(delivery=delivery)
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self.client.force_login(self.admin)
            response = self.client.post(reverse("inventory:stock_delivery_signed_upload", args=[delivery.pk]), {"signed_document": SimpleUploadedFile("acta.pdf", b"signed-pdf", content_type="application/pdf"), "signed_document_verified": True})
            self.assertEqual(response.status_code, 302)
            delivery.refresh_from_db()
            self.assertEqual(delivery.signed_document_uploaded_by, self.admin)
            self.assertIsNotNone(delivery.signed_document_uploaded_at)
            self.client.force_login(self.supervisor)
            download = self.client.get(reverse("inventory:stock_delivery_signed_download", args=[delivery.pk]))
            self.assertEqual(download.status_code, 200)
            download.close()
            client_user = User.objects.create_user(username="signed_client", email="signed_client@example.com", role="CLIENT")
            self.client.force_login(client_user)
            self.assertEqual(self.client.get(reverse("inventory:stock_delivery_signed_download", args=[delivery.pk])).status_code, 403)


class InventoryStockNotificationTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code="ALERT-HQ", name="Sede alertas")
        self.locations = [
            OrganizationalLocation.objects.create(branch=self.branch, code=f"ALERT-{index}", name=f"Depósito {index}", location_type=OrganizationalLocation.LocationType.WAREHOUSE)
            for index in range(1, 5)
        ]
        self.category = StockCategory.objects.create(name="Alertas", code="alertas-stock")
        self.product = StockProduct.objects.create(name="Mouse alerta", reference_code="ALERT-MOUSE", category=self.category, minimum_stock=3)
        self.admin = User.objects.create_user(
            username="alert_admin",
            email="alert_admin@example.com",
            role="ADMIN",
        )

    def balance(self, quantity, index=0, minimum=None):
        return StockBalance.objects.create(product=self.product, branch=self.branch, organizational_location=self.locations[index], quantity=quantity, minimum_stock=minimum)

    def notification(self, prefix, balance):
        return Notification.objects.get(unique_key=f"{prefix}{balance.pk}")

    def test_out_of_stock_creates_only_stock_out_with_correct_reference_and_link(self):
        balance = self.balance(0)
        result = generate_inventory_stock_notifications()
        alert = self.notification("inventory-stock-out-", balance)
        self.assertEqual(result["created"], 1)
        self.assertTrue(alert.is_active)
        self.assertEqual(alert.notification_type, Notification.TYPE_STOCK_OUT)
        self.assertEqual(alert.object_type, "StockBalance")
        self.assertEqual(alert.object_id, str(balance.pk))
        self.assertEqual(alert.link, reverse("inventory:stock_product_detail", args=[self.product.pk]))
        self.assertFalse(Notification.objects.filter(unique_key=f"inventory-stock-low-{balance.pk}", is_active=True).exists())

    def test_low_stock_uses_product_fallback_and_deactivates_out_alert(self):
        balance = self.balance(0)
        generate_inventory_stock_notifications()
        balance.quantity = 2
        balance.save(update_fields=["quantity"])
        generate_inventory_stock_notifications()
        self.assertTrue(self.notification("inventory-stock-low-", balance).is_active)
        self.assertFalse(self.notification("inventory-stock-out-", balance).is_active)
        self.assertEqual(balance.effective_minimum_stock, 3)

    def test_balance_specific_minimum_has_priority(self):
        balance = self.balance(4, minimum=5)
        generate_inventory_stock_notifications()
        self.assertTrue(self.notification("inventory-stock-low-", balance).is_active)
        self.assertEqual(balance.effective_minimum_stock, 5)

    def test_normal_stock_deactivates_both_alert_types(self):
        balance = self.balance(0)
        generate_inventory_stock_notifications()
        balance.quantity = 2
        balance.save(update_fields=["quantity"])
        generate_inventory_stock_notifications()
        balance.quantity = 10
        balance.save(update_fields=["quantity"])
        generate_inventory_stock_notifications()
        self.assertFalse(self.notification("inventory-stock-out-", balance).is_active)
        self.assertFalse(self.notification("inventory-stock-low-", balance).is_active)

    def test_multiple_locations_are_evaluated_independently(self):
        normal = self.balance(10, 0)
        low = self.balance(1, 1)
        out = self.balance(0, 2)
        generate_inventory_stock_notifications()
        self.assertFalse(Notification.objects.filter(object_id=str(normal.pk), is_active=True).exists())
        self.assertEqual(self.notification("inventory-stock-low-", low).notification_type, Notification.TYPE_LOW_STOCK)
        self.assertEqual(self.notification("inventory-stock-out-", out).notification_type, Notification.TYPE_STOCK_OUT)

    def test_repeated_generation_does_not_duplicate_notifications(self):
        balance = self.balance(1)
        generate_inventory_stock_notifications()
        generate_inventory_stock_notifications()
        self.assertEqual(Notification.objects.filter(unique_key=f"inventory-stock-low-{balance.pk}").count(), 1)

    def test_inactive_product_deactivates_existing_alerts(self):
        balance = self.balance(0)
        generate_inventory_stock_notifications()
        self.product.is_active = False
        self.product.save(update_fields=["is_active"])
        generate_inventory_stock_notifications()
        self.assertFalse(self.notification("inventory-stock-out-", balance).is_active)
        self.assertFalse(Notification.objects.filter(object_id=str(balance.pk), is_active=True).exists())

    def test_zero_minimum_only_alerts_when_stock_is_zero(self):
        positive = self.balance(1, 0, minimum=0)
        empty = self.balance(0, 1, minimum=0)
        generate_inventory_stock_notifications()
        self.assertFalse(Notification.objects.filter(object_id=str(positive.pk), is_active=True).exists())
        self.assertTrue(self.notification("inventory-stock-out-", empty).is_active)

    def test_generate_notifications_command_includes_inventory_stock(self):
        self.balance(0)
        output = StringIO()
        call_command("generate_notifications", stdout=output)
        self.assertIn("Stock de inventario genérico", output.getvalue())
        self.assertTrue(Notification.objects.filter(unique_key__startswith="inventory-stock-out-").exists())


    def test_stock_exit_automatically_creates_low_and_out_alerts(self):
        balance = self.balance(4)

        with self.captureOnCommitCallbacks(execute=True):
            register_stock_exit(
                product=self.product,
                branch=self.branch,
                organizational_location=self.locations[0],
                quantity=1,
                reason=StockMovement.Reason.CONSUMPTION,
                performed_by=self.admin,
            )

        balance.refresh_from_db()
        self.assertEqual(balance.quantity, 3)
        self.assertTrue(
            self.notification("inventory-stock-low-", balance).is_active
        )

        with self.captureOnCommitCallbacks(execute=True):
            register_stock_exit(
                product=self.product,
                branch=self.branch,
                organizational_location=self.locations[0],
                quantity=3,
                reason=StockMovement.Reason.CONSUMPTION,
                performed_by=self.admin,
            )

        balance.refresh_from_db()
        self.assertEqual(balance.quantity, 0)
        self.assertFalse(
            self.notification("inventory-stock-low-", balance).is_active
        )
        self.assertTrue(
            self.notification("inventory-stock-out-", balance).is_active
        )

    def test_stock_entry_automatically_deactivates_existing_alert(self):
        balance = self.balance(0)
        generate_inventory_stock_notifications()

        self.assertTrue(
            self.notification("inventory-stock-out-", balance).is_active
        )

        with self.captureOnCommitCallbacks(execute=True):
            register_stock_entry(
                product=self.product,
                branch=self.branch,
                organizational_location=self.locations[0],
                quantity=5,
                reason=StockMovement.Reason.PURCHASE,
                performed_by=self.admin,
            )

        balance.refresh_from_db()
        self.assertEqual(balance.quantity, 5)
        self.assertFalse(
            self.notification("inventory-stock-out-", balance).is_active
        )
        self.assertFalse(
            Notification.objects.filter(
                unique_key=f"inventory-stock-low-{balance.pk}",
                is_active=True,
            ).exists()
        )

    def test_transfer_automatically_updates_origin_and_destination_alerts(self):
        source = self.balance(4, index=0)
        destination = self.balance(0, index=1, minimum=0)

        generate_inventory_stock_notifications()
        self.assertTrue(
            self.notification("inventory-stock-out-", destination).is_active
        )

        with self.captureOnCommitCallbacks(execute=True):
            transfer_stock(
                product=self.product,
                source_branch=self.branch,
                source_location=self.locations[0],
                destination_branch=self.branch,
                destination_location=self.locations[1],
                quantity=1,
                performed_by=self.admin,
            )

        source.refresh_from_db()
        destination.refresh_from_db()

        self.assertEqual(source.quantity, 3)
        self.assertEqual(destination.quantity, 1)

        self.assertTrue(
            self.notification("inventory-stock-low-", source).is_active
        )
        self.assertFalse(
            self.notification("inventory-stock-out-", destination).is_active
        )

    def test_failed_stock_operation_does_not_run_alert_callback(self):
        balance = self.balance(4)

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    register_stock_exit(
                        product=self.product,
                        branch=self.branch,
                        organizational_location=self.locations[0],
                        quantity=1,
                        reason=StockMovement.Reason.CONSUMPTION,
                        performed_by=self.admin,
                    )
                    raise RuntimeError("Rollback simulado")

        balance.refresh_from_db()

        self.assertEqual(balance.quantity, 4)
        self.assertEqual(len(callbacks), 0)
        self.assertFalse(
            Notification.objects.filter(
                object_id=str(balance.pk),
                is_active=True,
            ).exists()
        )

    def test_automatic_alert_does_not_duplicate_existing_notification(self):
        balance = self.balance(3)
        generate_inventory_stock_notifications()

        with self.captureOnCommitCallbacks(execute=True):
            register_stock_entry(
                product=self.product,
                branch=self.branch,
                organizational_location=self.locations[0],
                quantity=1,
                reason=StockMovement.Reason.PURCHASE,
                performed_by=self.admin,
            )

        self.assertEqual(
            Notification.objects.filter(
                unique_key=f"inventory-stock-low-{balance.pk}"
            ).count(),
            1,
        )


class TicketStockUsageTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="usage_admin", email="usage_admin@example.com", password="pass", role="ADMIN")
        self.supervisor = User.objects.create_user(username="usage_super", email="usage_super@example.com", password="pass", role="SUPERVISOR")
        self.requester = User.objects.create_user(username="usage_requester", email="usage_requester@example.com", role="CLIENT")
        self.ticket = Ticket.objects.create(title="Reparación con insumos", description="Prueba", requester=self.requester)
        self.branch = Branch.objects.create(code="USAGE-HQ", name="Sede consumos")
        self.location = OrganizationalLocation.objects.create(branch=self.branch, code="USAGE-WH", name="Depósito consumos", location_type=OrganizationalLocation.LocationType.WAREHOUSE)
        category = StockCategory.objects.create(name="Consumos", code="ticket-usages")
        self.product = StockProduct.objects.create(name="SSD Kingston 480 GB", reference_code="USAGE-SSD", category=category, brand="Kingston", model="480 GB")
        self.product_two = StockProduct.objects.create(name="Patch Cord Cat6", reference_code="USAGE-CABLE", category=category)

    def usage(self):
        return TicketStockUsage.objects.create(ticket=self.ticket, registered_by=self.admin, observation="Reparación")

    def line(self, usage, product=None, quantity=1):
        return TicketStockUsageLine.objects.create(usage=usage, product=product or self.product, source_branch=self.branch, source_location=self.location, quantity=quantity)

    def balance(self, product, quantity):
        return StockBalance.objects.create(product=product, branch=self.branch, organizational_location=self.location, quantity=quantity)

    def test_draft_supports_multiple_lines_and_line_deletion(self):
        usage = self.usage()
        first = self.line(usage)
        self.line(usage, self.product_two, 2)
        self.assertEqual(usage.status, TicketStockUsage.Status.DRAFT)
        self.assertEqual(usage.lines.count(), 2)
        first.delete()
        self.assertEqual(usage.lines.count(), 1)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_confirm_multiple_lines_creates_ticket_movements_and_snapshots(self):
        usage = self.usage()
        self.line(usage, self.product, 1)
        self.line(usage, self.product_two, 2)
        self.balance(self.product, 3)
        self.balance(self.product_two, 2)
        confirmed = confirm_ticket_stock_usage(usage=usage, confirmed_by=self.supervisor)
        self.assertEqual(confirmed.status, TicketStockUsage.Status.CONFIRMED)
        self.assertEqual(confirmed.ticket_number, self.ticket.ticket_number)
        self.assertEqual(confirmed.confirmed_by, self.supervisor)
        self.assertEqual(StockMovement.objects.filter(ticket=self.ticket, reason=StockMovement.Reason.CONSUMPTION).count(), 2)
        self.assertEqual(StockBalance.objects.get(product=self.product).quantity, 2)
        self.assertEqual(StockBalance.objects.get(product=self.product_two).quantity, 0)
        line = confirmed.lines.get(product=self.product)
        self.assertEqual(line.product_sku, "USAGE-SSD")
        self.assertEqual(line.product_name, "SSD Kingston 480 GB")
        self.assertIsNotNone(line.stock_movement)

    def test_insufficient_stock_has_no_partial_effect(self):
        usage = self.usage()
        self.line(usage, self.product, 1)
        self.line(usage, self.product_two, 5)
        self.balance(self.product, 4)
        self.balance(self.product_two, 1)
        with self.assertRaises(ValidationError):
            confirm_ticket_stock_usage(usage=usage, confirmed_by=self.admin)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(StockBalance.objects.get(product=self.product).quantity, 4)
        usage.refresh_from_db()
        self.assertEqual(usage.status, TicketStockUsage.Status.DRAFT)

    def test_intermediate_failure_rolls_back_everything(self):
        usage = self.usage()
        self.line(usage, self.product, 1)
        self.line(usage, self.product_two, 1)
        self.balance(self.product, 4)
        self.balance(self.product_two, 4)
        from .services import stock as stock_service
        original = stock_service.register_stock_exit
        calls = {"value": 0}
        def fail_second(**kwargs):
            calls["value"] += 1
            if calls["value"] == 2:
                raise ValidationError("Fallo simulado")
            return original(**kwargs)
        with patch("apps.inventory.services.stock.register_stock_exit", side_effect=fail_second):
            with self.assertRaises(ValidationError):
                confirm_ticket_stock_usage(usage=usage, confirmed_by=self.admin)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(StockBalance.objects.get(product=self.product).quantity, 4)

    def test_confirmed_usage_is_immutable_and_not_repeatable(self):
        usage = self.usage()
        line = self.line(usage)
        self.balance(self.product, 2)
        confirm_ticket_stock_usage(usage=usage, confirmed_by=self.admin)
        usage.refresh_from_db()
        usage.ticket = Ticket.objects.create(title="Otro", description="Otro", requester=self.requester)
        with self.assertRaises(ValidationError):
            usage.save()
        line.refresh_from_db()
        line.quantity = 2
        with self.assertRaises(ValidationError):
            line.save()
        with self.assertRaises(ValidationError):
            line.delete()
        with self.assertRaises(ValidationError):
            confirm_ticket_stock_usage(usage=usage, confirmed_by=self.admin)

    def test_regular_stock_movement_remains_valid_without_ticket(self):
        balance = self.balance(self.product, 0)
        movement = register_stock_movement(balance=balance, quantity=1, direction=StockMovement.Direction.ENTRY, reason=StockMovement.Reason.PURCHASE, performed_by=self.admin)
        self.assertIsNone(movement.ticket)

    def test_permissions_are_admin_and_supervisor_only(self):
        usage = self.usage()
        url = reverse("inventory:ticket_stock_usage_list")
        for role in ("CLIENT", "TECHNICIAN", "AUDITOR"):
            user = User.objects.create_user(username=f"usage_{role.lower()}", email=f"usage_{role.lower()}@example.com", role=role)
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 403)
        for user in (self.admin, self.supervisor):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("inventory:ticket_stock_usage_confirm", args=[usage.pk])).status_code, 403)


class FinalStockSafetyRegressionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="final_stock_admin", email="final_stock_admin@example.com", role="ADMIN")
        self.branch = Branch.objects.create(code="FINAL-HQ", name="Sede final")
        self.location = OrganizationalLocation.objects.create(branch=self.branch, code="FINAL-WH", name="Depósito final", location_type=OrganizationalLocation.LocationType.WAREHOUSE)
        category = StockCategory.objects.create(name="Final", code="final-safety")
        self.product = StockProduct.objects.create(name="Producto inactivo", reference_code="FINAL-INACTIVE", category=category, is_active=False)
        self.balance = StockBalance.objects.create(product=self.product, branch=self.branch, organizational_location=self.location, quantity=5)

    def test_services_reject_inactive_products(self):
        with self.assertRaises(ValidationError):
            register_stock_entry(product=self.product, branch=self.branch, organizational_location=self.location, quantity=1, reason=StockMovement.Reason.PURCHASE, performed_by=self.user)
        with self.assertRaises(ValidationError):
            register_stock_exit(product=self.product, branch=self.branch, organizational_location=self.location, quantity=1, reason=StockMovement.Reason.CONSUMPTION, performed_by=self.user)
        with self.assertRaises(ValidationError):
            transfer_stock(product=self.product, source_branch=self.branch, source_location=self.location, destination_branch=self.branch, destination_location=self.location, quantity=1, performed_by=self.user)
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.quantity, 5)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_admin_state_fields_are_readonly(self):
        from .admin import StockDeliveryAdmin, StockEntryOperationAdmin, TicketStockUsageAdmin
        self.assertIn("status", StockEntryOperationAdmin.readonly_fields)
        self.assertIn("status", StockDeliveryAdmin.readonly_fields)
        self.assertIn("status", TicketStockUsageAdmin.readonly_fields)



class EmptyInventoryViewsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="empty_inventory_admin",
            email="empty_inventory_admin@example.com",
            password="test-password-123",
            role="ADMIN",
        )
        self.client.force_login(self.admin)

    def test_empty_inventory_lists_render_without_errors(self):
        urls = [
            reverse("inventory:stock_category_list"),
            reverse("inventory:stock_product_list"),
            reverse("inventory:stock_movement_list"),
            reverse("inventory:documented_stock_entry_list"),
            reverse("inventory:stock_delivery_list"),
            reverse("inventory:ticket_stock_usage_list"),
        ]

        self.assertFalse(StockCategory.objects.exists())
        self.assertFalse(StockProduct.objects.exists())
        self.assertFalse(StockBalance.objects.exists())
        self.assertFalse(StockMovement.objects.exists())
        self.assertFalse(StockEntryOperation.objects.exists())
        self.assertFalse(StockDelivery.objects.exists())
        self.assertFalse(TicketStockUsage.objects.exists())

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
