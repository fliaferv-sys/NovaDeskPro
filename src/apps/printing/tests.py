from django.contrib import admin
from django.core.exceptions import FieldDoesNotExist
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

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


class ConsumableStageFourAdminTests(TestCase):
    def setUp(self):
        from apps.inventory.models import StockCategory, StockProduct

        self.user = User.objects.create_superuser(
            username="printing-stage-four-admin",
            email="printing-stage-four@example.test",
            password="test-password-123",
        )
        self.client.force_login(self.user)
        self.category = StockCategory.objects.create(
            name="Categoría existente",
            code="existing-stage-four",
        )
        self.stock_product = StockProduct.objects.create(
            name="Producto existente",
            reference_code="EXISTING-001",
            category=self.category,
        )
        self.add_url = reverse("admin:printing_consumable_add")

    def consumable_data(self, **overrides):
        data = {
            "name": "Tóner etapa cuatro",
            "consumable_type": "TONER",
            "reference_code": "NEW-TONER-001",
            "stock_product": "",
            "manufacturer": "Fabricante",
            "model": "Modelo 1",
            "color": "Negro",
            "minimum_stock": 2,
            "maximum_stock": "",
            "estimated_yield_pages": 5000,
            "unit_price": "0",
            "notes": "",
            "is_active": "on",
            "_save": "Guardar",
            "initial_stock": 99,
        }
        data.update(overrides)
        return data

    def test_admin_allows_consumable_without_stock_product_and_ignores_initial_stock(self):
        from .models import Consumable

        response = self.client.post(self.add_url, self.consumable_data())

        self.assertEqual(response.status_code, 302)
        consumable = Consumable.objects.get(reference_code="NEW-TONER-001")
        self.assertIsNone(consumable.stock_product)
        self.assertEqual(consumable.initial_stock, 0)

    def test_candidate_detection_returns_unique_exact_normalized_match(self):
        from .forms import find_stock_product_candidates

        candidates = find_stock_product_candidates(" existing_001 ")

        self.assertEqual(candidates, [self.stock_product])

    def test_admin_candidate_endpoint_exposes_unique_suggestion(self):
        response = self.client.get(
            reverse("admin:printing_consumable_stock_product_candidates"),
            {"reference_code": " existing_001 "},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(
            response.json()["candidates"][0]["id"],
            str(self.stock_product.pk),
        )

    def test_candidate_detection_does_not_choose_ambiguous_match(self):
        from apps.inventory.models import StockProduct
        from .forms import find_stock_product_candidates

        StockProduct.objects.create(
            name="Producto ambiguo uno",
            reference_code="AMB-001",
            category=self.category,
        )
        StockProduct.objects.create(
            name="Producto ambiguo dos",
            reference_code="AMB_001",
            category=self.category,
        )

        candidates = find_stock_product_candidates("AMB001")

        self.assertEqual(len(candidates), 2)

    def test_admin_links_existing_product_explicitly(self):
        from .models import Consumable

        response = self.client.post(
            self.add_url,
            self.consumable_data(stock_product=str(self.stock_product.pk)),
        )

        consumable = Consumable.objects.get(reference_code="NEW-TONER-001")
        self.assertEqual(consumable.stock_product, self.stock_product)
        self.assertRedirects(
            response,
            reverse(
                "inventory:stock_product_detail",
                args=[self.stock_product.pk],
            ),
        )

    def test_admin_creates_and_links_product_without_stock_records(self):
        from apps.inventory.models import StockBalance, StockProduct
        from apps.inventory.models import StockMovement as InventoryMovement
        from .models import Consumable, StockMovement as PrintingMovement

        response = self.client.post(
            self.add_url,
            self.consumable_data(create_stock_product="on"),
        )

        product = StockProduct.objects.get(reference_code="NEW-TONER-001")
        consumable = Consumable.objects.get(reference_code="NEW-TONER-001")
        self.assertEqual(consumable.stock_product, product)
        self.assertEqual(consumable.initial_stock, 0)
        self.assertEqual(product.name, consumable.name)
        self.assertEqual(product.brand, consumable.manufacturer)
        self.assertEqual(product.model, consumable.model)
        self.assertEqual(
            product.unit_of_measure,
            StockProduct.UnitOfMeasure.UNIT,
        )
        self.assertEqual(product.category.code, "printing-consumables")
        self.assertTrue(product.is_active)
        self.assertFalse(StockBalance.objects.filter(product=product).exists())
        self.assertFalse(InventoryMovement.objects.filter(product=product).exists())
        self.assertFalse(PrintingMovement.objects.filter(consumable=consumable).exists())
        self.assertRedirects(
            response,
            reverse("inventory:stock_product_detail", args=[product.pk]),
        )

    def test_admin_rejects_new_product_with_duplicate_normalized_reference(self):
        from apps.inventory.models import StockProduct
        from .models import Consumable

        response = self.client.post(
            self.add_url,
            self.consumable_data(
                reference_code="EXISTING_001",
                create_stock_product="on",
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Selecciónelo explícitamente")
        self.assertFalse(
            Consumable.objects.filter(reference_code="EXISTING_001").exists()
        )
        self.assertEqual(StockProduct.objects.count(), 1)

    def test_consumable_changelist_renders_linked_and_unlinked_statuses(self):
        from .models import Consumable

        Consumable.objects.create(
            name="Consumible sin vínculo",
            reference_code="UNLINKED-STAGE-FOUR",
            manufacturer="Fabricante",
            initial_stock=0,
        )
        Consumable.objects.create(
            name="Consumible vinculado",
            reference_code="LINKED-STAGE-FOUR",
            manufacturer="Fabricante",
            initial_stock=0,
            stock_product=self.stock_product,
        )

        response = self.client.get(reverse("admin:printing_consumable_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sin producto de stock")
        self.assertContains(response, "Vinculado")


class ConsumableStockReconciliationTests(TestCase):
    def setUp(self):
        from apps.inventory.models import StockCategory

        self.user = User.objects.create_user(
            username="reconciliation-admin",
            email="reconciliation@example.test",
            password="test-password-123",
            role=User.Role.ADMIN,
        )
        self.category = StockCategory.objects.create(
            name="Conciliación", code="reconciliation-test"
        )

    def product(self, code, *, active=True):
        from apps.inventory.models import StockProduct

        return StockProduct.objects.create(
            name=f"Producto {code}", reference_code=code,
            category=self.category, is_active=active,
        )

    def consumable(self, code, *, initial=0, active=True, product=None):
        from .models import Consumable

        return Consumable.objects.create(
            name=f"Consumible {code}", reference_code=code,
            manufacturer="Test", initial_stock=initial,
            is_active=active, stock_product=product,
        )

    def batch(self):
        from .models import ConsumableStockMigrationBatch

        return ConsumableStockMigrationBatch.objects.create(created_by=self.user)

    def generate(self, batch):
        from .reconciliation import generate_consumable_stock_migration_batch

        return generate_consumable_stock_migration_batch(batch=batch)

    def test_batch_population_is_idempotent_and_unique(self):
        from django.core.exceptions import ValidationError
        from .models import ConsumableStockMigrationItem

        consumable = self.consumable("NO-MATCH")
        batch = self.batch()
        self.generate(batch)
        self.generate(batch)

        self.assertEqual(batch.items.filter(consumable=consumable).count(), 1)
        self.assertEqual(ConsumableStockMigrationItem.objects.count(), 1)
        with self.assertRaises(ValidationError):
            ConsumableStockMigrationItem.objects.create(
                batch=batch, consumable=consumable,
                printing_reference_snapshot="X", printing_name_snapshot="X",
                printing_active_snapshot=True, printing_initial_stock_snapshot=0,
                printing_entries_snapshot=0, printing_outputs_snapshot=0,
                printing_transfers_snapshot=0, printing_current_stock_snapshot=0,
                match_status=ConsumableStockMigrationItem.MatchStatus.NO_MATCH,
                quantity_status=ConsumableStockMigrationItem.QuantityStatus.NO_PRODUCT,
            )

    def test_detects_linked_unique_candidate_ambiguous_and_no_match(self):
        from .models import ConsumableStockMigrationItem as Item

        linked_product = self.product("LINKED-P")
        linked = self.consumable("OTHER-CODE", product=linked_product)
        candidate_product = self.product(" exact-01 ")
        candidate = self.consumable("EXACT_01")
        self.product("AMB-01")
        self.product("AMB 01")
        ambiguous = self.consumable("AMB_01")
        no_match = self.consumable("NONE-01")
        batch = self.generate(self.batch())

        self.assertEqual(batch.items.get(consumable=linked).match_status, Item.MatchStatus.LINKED)
        candidate_item = batch.items.get(consumable=candidate)
        self.assertEqual(candidate_item.match_status, Item.MatchStatus.EXACT_CODE_MATCH)
        self.assertEqual(candidate_item.stock_product_candidate, candidate_product)
        self.assertEqual(batch.items.get(consumable=ambiguous).match_status, Item.MatchStatus.AMBIGUOUS_CODE)
        self.assertEqual(batch.items.get(consumable=no_match).match_status, Item.MatchStatus.NO_MATCH)

    def test_snapshots_movements_and_transfer_without_changing_current_stock(self):
        from .models import ConsumableStockMigrationItem as Item, StockMovement

        consumable = self.consumable("MOV-01", initial=10)
        for movement_type, quantity in (
            (StockMovement.MovementType.ENTRY, 5),
            (StockMovement.MovementType.ISSUE, 4),
            (StockMovement.MovementType.TRANSFER, 9),
        ):
            StockMovement.objects.create(
                consumable=consumable, movement_type=movement_type,
                quantity=quantity, performed_by=self.user,
            )
        before = consumable.current_stock
        item = self.generate(self.batch()).items.get(consumable=consumable)

        self.assertEqual(item.printing_entries_snapshot, 5)
        self.assertEqual(item.printing_outputs_snapshot, 4)
        self.assertEqual(item.printing_transfers_snapshot, 9)
        self.assertEqual(item.printing_current_stock_snapshot, 11)
        self.assertEqual(consumable.current_stock, before)
        self.assertEqual(item.quantity_status, Item.QuantityStatus.NO_PRODUCT)

    def test_inventory_total_and_positive_zero_negative_differences(self):
        from apps.accounts.models import Branch
        from apps.inventory.models import OrganizationalLocation, StockBalance
        from .models import ConsumableStockMigrationItem as Item

        branch = Branch.objects.create(code="REC-HQ", name="Sede conciliación")
        location = OrganizationalLocation.objects.create(
            branch=branch, name="Depósito", location_type=OrganizationalLocation.LocationType.WAREHOUSE,
        )
        expected = []
        for index, (printing, inventory, status) in enumerate((
            (7, 5, Item.QuantityStatus.PRINTING_GREATER),
            (5, 5, Item.QuantityStatus.MATCH),
            (3, 5, Item.QuantityStatus.INVENTORY_GREATER),
        )):
            product = self.product(f"DIFF-{index}")
            consumable = self.consumable(f"DIFF-C-{index}", initial=printing, product=product)
            StockBalance.objects.create(
                product=product, branch=branch, organizational_location=location, quantity=inventory,
            )
            expected.append((consumable, printing - inventory, status))
        batch = self.generate(self.batch())
        for consumable, difference, status in expected:
            item = batch.items.get(consumable=consumable)
            self.assertEqual(item.inventory_total_stock_snapshot, 5)
            self.assertEqual(item.difference, difference)
            self.assertEqual(item.quantity_status, status)

    def test_negative_inactive_product_inactive_and_no_balance_are_detected(self):
        from .models import ConsumableStockMigrationItem as Item, StockMovement

        negative = self.consumable("NEG-01")
        StockMovement.objects.create(
            consumable=negative, movement_type=StockMovement.MovementType.ISSUE,
            quantity=1, performed_by=self.user,
        )
        inactive_product = self.product("INACTIVE-P", active=False)
        inactive = self.consumable("INACTIVE-C", active=False, product=inactive_product)
        batch = self.generate(self.batch())
        negative_item = batch.items.get(consumable=negative)
        inactive_item = batch.items.get(consumable=inactive)

        self.assertEqual(negative_item.quantity_status, Item.QuantityStatus.NEGATIVE_PRINTING_STOCK)
        self.assertFalse(inactive_item.printing_active_snapshot)
        self.assertFalse(inactive_item.stock_product_active_snapshot)
        self.assertFalse(inactive_item.inventory_has_balance_snapshot)
        self.assertEqual(inactive_item.quantity_status, Item.QuantityStatus.NO_BALANCE)

    def test_manual_decision_and_future_destination_are_persisted(self):
        from apps.accounts.models import Branch
        from apps.inventory.models import OrganizationalLocation
        from .models import ConsumableStockMigrationItem as Item

        consumable = self.consumable("DECISION-01")
        item = self.generate(self.batch()).items.get(consumable=consumable)
        branch = Branch.objects.create(code="REC-DEST", name="Destino")
        location = OrganizationalLocation.objects.create(
            branch=branch, name="Almacén futuro",
            location_type=OrganizationalLocation.LocationType.WAREHOUSE,
        )
        item.decision_status = Item.DecisionStatus.PHYSICAL_COUNT_REQUIRED
        item.destination_branch = branch
        item.destination_location = location
        item.approved_quantity = 4
        item.reviewed_by = self.user
        item.reviewed_at = timezone.now()
        item.save()
        item.refresh_from_db()

        self.assertEqual(item.destination_location, location)
        self.assertEqual(item.approved_quantity, 4)
        self.assertEqual(item.reviewed_by, self.user)

    def test_completed_batch_cannot_be_recalculated(self):
        from django.core.exceptions import ValidationError
        from .models import ConsumableStockMigrationBatch
        from .reconciliation import complete_consumable_stock_migration_batch

        self.consumable("COMPLETE-01")
        batch = self.generate(self.batch())
        complete_consumable_stock_migration_batch(batch=batch)
        self.assertEqual(batch.status, ConsumableStockMigrationBatch.Status.COMPLETED)
        with self.assertRaises(ValidationError):
            self.generate(batch)

    def test_generation_does_not_create_or_modify_operational_stock(self):
        from apps.inventory.models import StockBalance
        from apps.inventory.models import StockMovement as InventoryMovement
        from .models import StockMovement

        consumable = self.consumable("SAFE-01", initial=3)
        printing_movement = StockMovement.objects.create(
            consumable=consumable, movement_type=StockMovement.MovementType.ENTRY,
            quantity=2, performed_by=self.user,
        )
        before = consumable.current_stock
        self.generate(self.batch())

        self.assertEqual(StockBalance.objects.count(), 0)
        self.assertEqual(InventoryMovement.objects.count(), 0)
        self.assertEqual(StockMovement.objects.get(pk=printing_movement.pk).quantity, 2)
        self.assertEqual(consumable.current_stock, before)

    def consolidation_destination(self, suffix="ONE"):
        from apps.accounts.models import Branch
        from apps.inventory.models import OrganizationalLocation

        branch = Branch.objects.create(code=f"CON-{suffix}", name=f"Sede {suffix}")
        location = OrganizationalLocation.objects.create(
            branch=branch,
            name=f"Depósito {suffix}",
            location_type=OrganizationalLocation.LocationType.WAREHOUSE,
        )
        return branch, location

    def approved_item(self, *, code="CONSOL-01", quantity=3, product_active=True,
                      consumable_active=True):
        from .models import ConsumableStockMigrationItem as Item

        product = self.product(f"{code}-PRODUCT", active=product_active)
        consumable = self.consumable(code, initial=quantity, active=consumable_active)
        batch = self.generate(self.batch())
        item = batch.items.get(consumable=consumable)
        branch, location = self.consolidation_destination(code)
        item.stock_product_candidate = product
        item.decision_status = Item.DecisionStatus.USE_PRINTING
        item.approved_quantity = quantity
        item.destination_branch = branch
        item.destination_location = location
        item.save()
        return item, consumable, product, branch, location

    def consolidate(self, *items):
        from .reconciliation import consolidate_consumable_stock_items

        return consolidate_consumable_stock_items(items=items, performed_by=self.user)

    def test_consolidation_links_product_creates_movement_and_updates_balance(self):
        from apps.inventory.models import StockBalance
        from apps.inventory.models import StockMovement as InventoryMovement

        item, consumable, product, branch, location = self.approved_item(quantity=3)
        movements = self.consolidate(item)
        item.refresh_from_db()
        consumable.refresh_from_db()

        self.assertEqual(consumable.stock_product, product)
        self.assertEqual(len(movements), 1)
        movement = movements[0]
        self.assertEqual(movement.direction, InventoryMovement.Direction.ENTRY)
        self.assertEqual(movement.reason, InventoryMovement.Reason.INITIAL_ENTRY)
        self.assertEqual(movement.quantity, 3)
        self.assertIn(str(item.pk), movement.document_reference)
        self.assertEqual(
            StockBalance.objects.get(
                product=product, branch=branch, organizational_location=location
            ).quantity,
            3,
        )
        self.assertEqual(item.inventory_stock_movement, movement)
        self.assertEqual(item.consolidated_quantity, 3)
        self.assertEqual(item.consolidated_by, self.user)
        self.assertIsNotNone(item.consolidated_at)

    def test_second_consolidation_is_rejected_without_adding_stock(self):
        from django.core.exceptions import ValidationError
        from apps.inventory.models import StockBalance, StockMovement as InventoryMovement

        item, _consumable, product, branch, location = self.approved_item(quantity=2)
        self.consolidate(item)
        item.refresh_from_db()
        with self.assertRaises(ValidationError):
            self.consolidate(item)

        self.assertEqual(InventoryMovement.objects.filter(product=product).count(), 1)
        self.assertEqual(
            StockBalance.objects.get(
                product=product, branch=branch, organizational_location=location
            ).quantity,
            2,
        )

    def test_selected_items_roll_back_together_when_one_is_invalid(self):
        from django.core.exceptions import ValidationError
        from apps.inventory.models import StockBalance
        from apps.inventory.models import StockMovement as InventoryMovement

        valid, consumable, _product, _branch, _location = self.approved_item(
            code="ROLLBACK-01", quantity=2
        )
        invalid, *_ = self.approved_item(code="ROLLBACK-02", quantity=1)
        invalid.destination_branch = None
        invalid.save(update_fields=["destination_branch", "updated_at"])

        with self.assertRaises(ValidationError):
            self.consolidate(valid, invalid)

        consumable.refresh_from_db()
        self.assertIsNone(consumable.stock_product)
        self.assertEqual(StockBalance.objects.count(), 0)
        self.assertEqual(InventoryMovement.objects.count(), 0)

    def test_invalid_quantity_missing_branch_and_cross_branch_location_are_rejected(self):
        from django.core.exceptions import ValidationError

        item, *_ = self.approved_item(code="VALIDATE-01")
        item.approved_quantity = None
        item.destination_branch = None
        item.save(update_fields=["approved_quantity", "destination_branch", "updated_at"])
        with self.assertRaises(ValidationError):
            self.consolidate(item)

        item, *_ = self.approved_item(code="VALIDATE-02")
        other_branch, _ = self.consolidation_destination("OTHER")
        item.destination_branch = other_branch
        ConsumableStockMigrationItem = type(item)
        ConsumableStockMigrationItem.objects.filter(pk=item.pk).update(
            destination_branch=other_branch
        )
        item.refresh_from_db()
        with self.assertRaises(ValidationError):
            self.consolidate(item)

    def test_inactive_product_and_consumable_are_rejected(self):
        from django.core.exceptions import ValidationError
        from apps.inventory.models import StockBalance

        inactive_product_item, *_ = self.approved_item(
            code="INACTIVE-P-01", product_active=False
        )
        with self.assertRaises(ValidationError):
            self.consolidate(inactive_product_item)

        inactive_consumable_item, *_ = self.approved_item(
            code="INACTIVE-C-01", consumable_active=False
        )
        with self.assertRaises(ValidationError):
            self.consolidate(inactive_consumable_item)
        self.assertEqual(StockBalance.objects.count(), 0)

    def test_consolidation_preserves_printing_history_compatibility_and_other_domains(self):
        from apps.inventory.models import Asset, StockBalance
        from apps.tickets.models import Ticket
        from .models import ConsumableCompatibility, PrintingDevice, StockMovement

        item, consumable, _product, _branch, _location = self.approved_item(
            code="PRESERVE-01", quantity=2
        )
        unrelated_product = self.product("UNRELATED-01")
        asset = Asset.objects.create(
            internal_code="CONSOLIDATION-PRINTER-01",
            asset_type=Asset.AssetType.PRINTER,
            brand="Test", model="Printer",
        )
        device = PrintingDevice.objects.create(asset=asset)
        compatibility = ConsumableCompatibility.objects.create(
            printing_device=device, consumable=consumable
        )
        legacy = StockMovement.objects.create(
            consumable=consumable, movement_type=StockMovement.MovementType.ENTRY,
            quantity=4, performed_by=self.user,
        )
        ticket_count = Ticket.objects.count()
        self.consolidate(item)

        self.assertTrue(StockMovement.objects.filter(pk=legacy.pk, quantity=4).exists())
        self.assertTrue(ConsumableCompatibility.objects.filter(pk=compatibility.pk).exists())
        self.assertFalse(StockBalance.objects.filter(product=unrelated_product).exists())
        self.assertEqual(Ticket.objects.count(), ticket_count)


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
