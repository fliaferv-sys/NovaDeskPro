from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Branch

from .models import (
    AcquisitionBatch,
    Asset,
    OrganizationalLocation,
    StockBalance,
    StockCategory,
    StockMovement,
    StockProduct,
)
from .services.stock import (
    register_stock_entry,
    register_stock_exit,
    register_stock_movement,
    transfer_stock,
)


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
