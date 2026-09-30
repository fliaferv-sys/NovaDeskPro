from unittest.mock import patch
import tempfile
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.forms import inlineformset_factory
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Branch
from apps.core.models import Department
from apps.notifications.models import Notification
from apps.tickets.models import Ticket
from apps.monitoring.models import DeviceHeartbeat
from apps.deliveries.models import AssetCustodyMovement

from .forms import AssetForm
from .admin import ToolAdminForm, ToolLoanItemAdminForm, ToolLoanItemInlineFormSet
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
    Tool,
    ToolLoan,
    ToolLoanItem,
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
from .services.tool_loans import register_tool_loan, register_tool_return, register_tool_partial_return
from .stock_delivery_pdf import generate_stock_delivery_pdf
from .services.notifications import generate_inventory_stock_notifications


User = get_user_model()


class AssetRelationshipTests(TestCase):
    def create_asset(self, internal_code, asset_type):
        return Asset.objects.create(
            internal_code=internal_code,
            asset_type=asset_type,
        )

    def assert_parent_asset_invalid(self, asset):
        with self.assertRaises(ValidationError) as context:
            asset.full_clean()

        self.assertIn("parent_asset", context.exception.error_dict)

    def test_desktop_label_and_internal_key(self):
        self.assertEqual(Asset.AssetType.DESKTOP, "DESKTOP")
        self.assertEqual(
            dict(Asset.AssetType.choices)[Asset.AssetType.DESKTOP],
            "CPU / Unidad de sistema",
        )

    def test_monitor_can_be_associated_with_desktop(self):
        desktop = self.create_asset("REL-DESKTOP-VALID", Asset.AssetType.DESKTOP)
        monitor = Asset(
            internal_code="REL-MONITOR-VALID",
            asset_type=Asset.AssetType.MONITOR,
            parent_asset=desktop,
        )

        monitor.full_clean()

    def test_monitor_cannot_be_associated_with_laptop(self):
        laptop = self.create_asset("REL-LAPTOP-MONITOR", Asset.AssetType.LAPTOP)
        monitor = Asset(
            internal_code="REL-MONITOR-LAPTOP",
            asset_type=Asset.AssetType.MONITOR,
            parent_asset=laptop,
        )

        self.assert_parent_asset_invalid(monitor)

    def test_desktop_cannot_be_associated_with_desktop(self):
        parent = self.create_asset("REL-DESKTOP-PARENT", Asset.AssetType.DESKTOP)
        desktop = Asset(
            internal_code="REL-DESKTOP-CHILD",
            asset_type=Asset.AssetType.DESKTOP,
            parent_asset=parent,
        )

        self.assert_parent_asset_invalid(desktop)

    def test_laptop_cannot_be_associated_with_desktop(self):
        desktop = self.create_asset("REL-DESKTOP-LAPTOP", Asset.AssetType.DESKTOP)
        laptop = Asset(
            internal_code="REL-LAPTOP-CHILD",
            asset_type=Asset.AssetType.LAPTOP,
            parent_asset=desktop,
        )

        self.assert_parent_asset_invalid(laptop)

    def test_asset_cannot_be_associated_with_itself(self):
        monitor = self.create_asset("REL-MONITOR-SELF", Asset.AssetType.MONITOR)
        monitor.parent_asset = monitor

        self.assert_parent_asset_invalid(monitor)

    def test_asset_form_parent_queryset_contains_only_desktops(self):
        desktop = self.create_asset("REL-FORM-DESKTOP", Asset.AssetType.DESKTOP)
        self.create_asset("REL-FORM-LAPTOP", Asset.AssetType.LAPTOP)
        self.create_asset("REL-FORM-MONITOR", Asset.AssetType.MONITOR)

        form = AssetForm()

        self.assertEqual(
            list(form.fields["parent_asset"].queryset.values_list("pk", flat=True)),
            [desktop.pk],
        )

    def test_asset_form_rejects_manipulated_parent_for_laptop(self):
        desktop = self.create_asset("REL-FORM-MANIPULATED-DESKTOP", Asset.AssetType.DESKTOP)
        batch = AcquisitionBatch.objects.create(
            code="REL-FORM-MANIPULATED-BATCH",
            date=timezone.localdate(),
        )
        form = AssetForm(
            data={
                "internal_code": "REL-FORM-MANIPULATED-LAPTOP",
                "patrimonial_code": "REL-FORM-MANIPULATED-PAT",
                "asset_type": Asset.AssetType.LAPTOP,
                "parent_asset": str(desktop.pk),
                "brand": "Marca de prueba",
                "model": "Modelo de prueba",
                "serial_number": "REL-FORM-MANIPULATED-SERIAL",
                "acquisition_batch": str(batch.pk),
                "operational_status": Asset.OperationalStatus.OPERATIONAL,
                "connection_status": Asset.ConnectionStatus.UNKNOWN,
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("parent_asset", form.errors)


class AssetTechnicalSpecificationsTests(TestCase):
    def test_asset_without_technical_specifications_is_valid(self):
        asset = Asset(internal_code="TECH-EMPTY")
        asset.full_clean()
        asset.save()

        self.assertIsNone(asset.ram_gb)
        self.assertEqual(asset.disk_type, "")
        self.assertIsNone(asset.storage_capacity_gb)

    def test_valid_ram_and_storage_are_accepted(self):
        asset = Asset(
            internal_code="TECH-VALID",
            ram_gb=Decimal("16.50"),
            storage_capacity_gb=Decimal("512"),
        )
        asset.full_clean()

    def test_non_positive_ram_is_rejected(self):
        for value in (Decimal("0"), Decimal("-1")):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                Asset(internal_code=f"RAM-{value}", ram_gb=value).full_clean()

    def test_all_disk_type_choices_are_accepted(self):
        for value in (
            Asset.DiskType.HDD,
            Asset.DiskType.SSD,
            Asset.DiskType.NVME,
            Asset.DiskType.SSHD,
            Asset.DiskType.OTHER,
        ):
            with self.subTest(value=value):
                Asset(internal_code=f"DISK-{value}", disk_type=value).full_clean()

    def test_invalid_disk_type_is_rejected(self):
        with self.assertRaises(ValidationError):
            Asset(internal_code="DISK-INVALID", disk_type="SATA").full_clean()

    def test_non_positive_storage_capacity_is_rejected(self):
        for value in (Decimal("0"), Decimal("-1")):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                Asset(
                    internal_code=f"STORAGE-{value}", storage_capacity_gb=value
                ).full_clean()

    def test_asset_form_exposes_technical_specifications(self):
        form = AssetForm()
        self.assertTrue(
            {"ram_gb", "disk_type", "storage_capacity_gb"}.issubset(form.fields)
        )

    def test_asset_admin_groups_technical_specifications(self):
        model_admin = admin.site._registry[Asset]
        technical_fields = next(
            options["fields"]
            for title, options in model_admin.fieldsets
            if title == "Especificaciones técnicas"
        )
        self.assertTrue(
            {"ram_gb", "disk_type", "storage_capacity_gb"}.issubset(
                technical_fields
            )
        )

    def test_effective_values_fall_back_to_monitoring(self):
        asset = Asset.objects.create(internal_code="TECH-FALLBACK")
        DeviceHeartbeat.objects.create(
            asset=asset,
            computer_name="TECH-FALLBACK",
            ram_total_gb=Decimal("8"),
            disk_total_gb=Decimal("256"),
        )

        self.assertEqual(asset.effective_ram_gb, Decimal("8"))
        self.assertEqual(asset.effective_storage_capacity_gb, Decimal("256"))

    def test_manual_values_are_not_overwritten_by_monitoring(self):
        asset = Asset.objects.create(
            internal_code="TECH-MANUAL",
            ram_gb=Decimal("16"),
            storage_capacity_gb=Decimal("512"),
        )
        DeviceHeartbeat.objects.create(
            asset=asset,
            computer_name="TECH-MANUAL",
            ram_total_gb=Decimal("8"),
            disk_total_gb=Decimal("256"),
        )

        self.assertEqual(asset.effective_ram_gb, Decimal("16"))
        self.assertEqual(asset.effective_storage_capacity_gb, Decimal("512"))
        asset.refresh_from_db()
        self.assertEqual(asset.ram_gb, Decimal("16"))
        self.assertEqual(asset.storage_capacity_gb, Decimal("512"))


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
            "condition": Asset.Condition.NEW,
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

    def test_monitor_detail_links_to_its_desktop(self):
        monitor = Asset.objects.create(
            internal_code="ACT-DETAIL-MONITOR",
            asset_type=Asset.AssetType.MONITOR,
            parent_asset=self.asset,
        )
        self.client.force_login(self.admin_user)

        response = self.client.get(
            reverse("inventory:asset_detail", kwargs={"pk": monitor.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Equipo principal")
        self.assertContains(
            response,
            reverse("inventory:asset_detail", kwargs={"pk": self.asset.pk}),
        )
        self.assertContains(response, self.asset.internal_code)

    def test_desktop_detail_links_to_associated_monitors(self):
        monitor = Asset.objects.create(
            internal_code="ACT-DETAIL-CHILD-MONITOR",
            asset_type=Asset.AssetType.MONITOR,
            parent_asset=self.asset,
        )
        self.client.force_login(self.admin_user)

        response = self.client.get(
            reverse("inventory:asset_detail", kwargs={"pk": self.asset.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Componentes asociados")
        self.assertContains(
            response,
            reverse("inventory:asset_detail", kwargs={"pk": monitor.pk}),
        )
        self.assertContains(response, monitor.internal_code)

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
        other_user_asset = Asset.objects.create(
            internal_code="ACT-OTHER-USER-001",
            asset_type=Asset.AssetType.LAPTOP,
            assigned_user=self.admin_user,
        )
        self.client.force_login(self.client_user)

        response = self.client.get(reverse("inventory:my_asset_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.client_asset.internal_code)
        self.assertNotContains(response, self.asset.internal_code)
        self.assertNotContains(response, self.retired_client_asset.internal_code)
        self.assertNotContains(response, self.returned_client_asset.internal_code)
        self.assertNotContains(response, other_user_asset.internal_code)
        self.assertEqual(list(response.context["assets"]), [self.client_asset])

    def test_client_cannot_open_global_inventory_list(self):
        self.client.force_login(self.client_user)

        response = self.client.get(reverse("inventory:asset_list"))

        self.assertEqual(response.status_code, 403)

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

    def test_inventory_shows_used_custody_card_only_to_managers(self):
        auditor = User.objects.create_user(
            username="auditor_inventario_usados",
            email="auditor_inventario_usados@example.com",
            password="test-password-123",
            role="AUDITOR",
        )

        for user in (self.admin_user, self.supervisor_user):
            with self.subTest(role=user.role):
                self.client.force_login(user)
                response = self.client.get(reverse("inventory:asset_list"))
                self.assertContains(response, "Custodia Usados")

        self.client.force_login(auditor)
        response = self.client.get(reverse("inventory:asset_list"))
        self.assertNotContains(response, "Custodia Usados")


class UsedAssetCustodyTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="admin_custodia_usados",
            email="admin_custodia_usados@example.com",
            password="test-password-123",
            role="ADMIN",
        )
        self.supervisor_user = User.objects.create_user(
            username="supervisor_custodia_usados",
            email="supervisor_custodia_usados@example.com",
            password="test-password-123",
            role="SUPERVISOR",
        )
        self.client_user = User.objects.create_user(
            username="cliente_custodia_usados",
            email="cliente_custodia_usados@example.com",
            password="test-password-123",
            role="CLIENT",
        )

    def create_recovered_asset(self, internal_code, **overrides):
        return Asset.objects.create(
            internal_code=internal_code,
            condition=Asset.Condition.RECOVERED,
            **overrides,
        )

    def create_movement(self, asset, movement_type, status):
        return AssetCustodyMovement.objects.create(
            asset=asset,
            movement_type=movement_type,
            status=status,
            delivery_responsible=self.admin_user,
            created_by=self.admin_user,
        )

    def get_asset_situation(self, asset):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("inventory:used_asset_list"))
        self.assertEqual(response.status_code, 200)
        matching_asset = next(
            item
            for item in response.context["assets"]
            if item.pk == asset.pk
        )
        return matching_asset.used_custody_situation_label

    def test_condition_defaults_to_new_and_recovered_is_saved(self):
        new_asset = Asset.objects.create(internal_code="USED-CONDITION-NEW")
        recovered_asset = self.create_recovered_asset("USED-CONDITION-RECOVERED")

        self.assertEqual(new_asset.condition, Asset.Condition.NEW)
        recovered_asset.refresh_from_db()
        self.assertEqual(recovered_asset.condition, Asset.Condition.RECOVERED)

    def test_admin_can_access_used_asset_list(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("inventory:used_asset_list"))
        self.assertEqual(response.status_code, 200)

    def test_supervisor_can_access_used_asset_list(self):
        self.client.force_login(self.supervisor_user)
        response = self.client.get(reverse("inventory:used_asset_list"))
        self.assertEqual(response.status_code, 200)

    def test_client_cannot_access_used_asset_list(self):
        self.client.force_login(self.client_user)
        response = self.client.get(reverse("inventory:used_asset_list"))
        self.assertEqual(response.status_code, 403)

    def test_list_contains_only_recovered_assets(self):
        recovered_asset = self.create_recovered_asset("USED-ONLY-RECOVERED")
        new_asset = Asset.objects.create(internal_code="USED-ONLY-NEW")
        self.client.force_login(self.admin_user)

        response = self.client.get(reverse("inventory:used_asset_list"))

        self.assertContains(response, recovered_asset.internal_code)
        self.assertNotContains(response, new_asset.internal_code)

    def test_observation_asset_is_in_review(self):
        asset = self.create_recovered_asset(
            "USED-REVIEW",
            operational_status=Asset.OperationalStatus.OBSERVATION,
        )
        self.assertEqual(self.get_asset_situation(asset), "En revisión")

    def test_maintenance_asset_is_in_repair(self):
        asset = self.create_recovered_asset(
            "USED-REPAIR",
            operational_status=Asset.OperationalStatus.MAINTENANCE,
        )
        self.assertEqual(self.get_asset_situation(asset), "En reparación")

    def test_operational_unassigned_asset_is_ready_for_delivery(self):
        asset = self.create_recovered_asset(
            "USED-READY",
            operational_status=Asset.OperationalStatus.OPERATIONAL,
        )
        self.assertEqual(self.get_asset_situation(asset), "Listo para entrega")

    def test_out_of_service_asset_is_classified(self):
        asset = self.create_recovered_asset(
            "USED-OUT-OF-SERVICE",
            operational_status=Asset.OperationalStatus.OUT_OF_SERVICE,
        )
        self.assertEqual(self.get_asset_situation(asset), "Fuera de servicio")

    def test_active_delivery_is_in_delivery_process(self):
        asset = self.create_recovered_asset("USED-DELIVERY")
        self.create_movement(
            asset,
            AssetCustodyMovement.MovementType.DELIVERY,
            AssetCustodyMovement.MovementStatus.PENDING_SIGNATURE,
        )
        self.assertEqual(
            self.get_asset_situation(asset),
            "En proceso de entrega",
        )

    def test_active_delivery_has_priority_over_delivered_history(self):
        asset = self.create_recovered_asset("USED-DELIVERY-PRIORITY")
        self.create_movement(
            asset,
            AssetCustodyMovement.MovementType.DELIVERY,
            AssetCustodyMovement.MovementStatus.DELIVERED,
        )
        self.create_movement(
            asset,
            AssetCustodyMovement.MovementType.DELIVERY,
            AssetCustodyMovement.MovementStatus.IN_DELIVERY_PROCESS,
        )
        self.assertEqual(
            self.get_asset_situation(asset),
            "En proceso de entrega",
        )

    def test_assigned_recovered_asset_is_classified_as_delivered(self):
        asset = self.create_recovered_asset(
            "USED-DELIVERED-ASSIGNED",
            assigned_user=self.admin_user,
        )

        self.assertEqual(self.get_asset_situation(asset), "Entregado")

    def test_old_delivered_movement_does_not_override_repair_status(self):
        asset = self.create_recovered_asset(
            "USED-REPAIR-OLD-DELIVERY",
            operational_status=Asset.OperationalStatus.MAINTENANCE,
        )
        self.create_movement(
            asset,
            AssetCustodyMovement.MovementType.DELIVERY,
            AssetCustodyMovement.MovementStatus.DELIVERED,
        )

        self.assertEqual(self.get_asset_situation(asset), "En reparación")

    def test_search_and_situation_filter(self):
        review_asset = self.create_recovered_asset(
            "USED-SEARCH-REVIEW",
            operational_status=Asset.OperationalStatus.OBSERVATION,
        )
        self.create_recovered_asset("USED-SEARCH-READY")
        self.client.force_login(self.admin_user)

        response = self.client.get(
            reverse("inventory:used_asset_list"),
            {"q": "SEARCH", "estado": "review"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [asset.internal_code for asset in response.context["assets"]],
            [review_asset.internal_code],
        )
        self.assertContains(response, review_asset.internal_code)


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


class InventoryNavigationTests(TestCase):
    def create_user(self, name, role):
        user = User.objects.create_user(
            username=name,
            email=f"{name}@example.test",
            password="test-password-123",
            role=role,
        )
        user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="deliveries",
                codename="view_assetcustodymovement",
            )
        )
        return user

    def test_inventory_links_stock_and_custody_according_to_permissions(self):
        stock_url = reverse("inventory:stock_product_list")
        custody_url = reverse("deliveries:custody_movement_list")
        for role in (User.Role.ADMIN, User.Role.SUPERVISOR):
            with self.subTest(role=role):
                self.client.force_login(self.create_user(f"inventory-nav-{role.lower()}", role))
                response = self.client.get(reverse("inventory:asset_list"))
                self.assertContains(response, f'href="{stock_url}"')
                self.assertContains(response, f'href="{custody_url}"')

        for role in (User.Role.AUDITOR, User.Role.TECHNICIAN):
            with self.subTest(role=role):
                self.client.force_login(self.create_user(f"inventory-nav-{role.lower()}", role))
                response = self.client.get(reverse("inventory:asset_list"))
                self.assertNotContains(response, f'href="{stock_url}"')
                self.assertContains(response, f'href="{custody_url}"')

    def test_stock_panel_exposes_all_existing_operations(self):
        admin = self.create_user("stock-navigation-admin", User.Role.ADMIN)
        self.client.force_login(admin)
        response = self.client.get(reverse("inventory:stock_product_list"))
        for name in (
            "stock_product_list", "stock_category_list", "stock_entry",
            "documented_stock_entry_list", "stock_exit", "stock_transfer",
            "stock_movement_list", "stock_delivery_list", "ticket_stock_usage_list",
        ):
            self.assertContains(response, f'href="{reverse(f"inventory:{name}")}"')

    def test_relocated_destinations_still_respond(self):
        admin = self.create_user("relocated-navigation-admin", User.Role.ADMIN)
        self.client.force_login(admin)
        for destination in (
            reverse("reports:index"), reverse("notifications:notification_list"),
            reverse("monitoring:dashboard"), reverse("inventory:my_asset_list"),
            reverse("deliveries:custody_movement_list"),
        ):
            with self.subTest(destination=destination):
                self.assertEqual(self.client.get(destination).status_code, 200)


class AssetQrTests(TestCase):
    def setUp(self):
        self.asset = Asset.objects.create(
            internal_code="QR-ACT-001",
            patrimonial_code="PAT-QR-900",
            asset_type=Asset.AssetType.LAPTOP,
            brand="Lenovo",
            model="ThinkPad",
            serial_number="SERIAL-QR-001",
        )
        self.admin = self.create_user("qr-admin", User.Role.ADMIN)
        self.client_user = self.create_user("qr-client", User.Role.CLIENT)

    def create_user(self, name, role):
        return User.objects.create_user(
            username=name,
            email=f"{name}@example.test",
            password="test-password-123",
            role=role,
        )

    def test_authorized_roles_can_open_qr_center(self):
        for role in (User.Role.ADMIN, User.Role.SUPERVISOR, User.Role.AUDITOR, User.Role.TECHNICIAN):
            with self.subTest(role=role):
                self.client.force_login(self.create_user(f"qr-authorized-{role.lower()}", role))
                self.assertEqual(self.client.get(reverse("inventory:asset_qr_center")).status_code, 200)

    def test_qr_center_searches_existing_asset_fields(self):
        self.client.force_login(self.admin)
        for search in ("QR-ACT", "PAT-QR", "SERIAL-QR", "Lenovo", "ThinkPad"):
            with self.subTest(search=search):
                response = self.client.get(reverse("inventory:asset_qr_center"), {"q": search})
                self.assertContains(response, self.asset.internal_code)

    def test_qr_image_is_png_and_encodes_absolute_asset_detail_url(self):
        self.client.force_login(self.admin)
        expected_url = "http://testserver" + reverse("inventory:asset_detail", args=[self.asset.pk])
        with patch("apps.inventory.views.qrcode.QRCode") as qr_class:
            qr_image = qr_class.return_value.make_image.return_value
            qr_image.save.side_effect = lambda output, format: output.write(b"\x89PNG\r\n\x1a\n")
            response = self.client.get(reverse("inventory:asset_qr_image", args=[self.asset.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertTrue(response.content.startswith(b"\x89PNG"))
        qr_class.return_value.add_data.assert_called_once_with(expected_url)

    @override_settings(ALLOWED_HOSTS=["qr-example.trycloudflare.com"])
    def test_qr_uses_public_host_and_scheme_forwarded_by_tunnel(self):
        self.client.force_login(self.admin)
        expected_url = (
            "https://qr-example.trycloudflare.com"
            + reverse("inventory:asset_detail", args=[self.asset.pk])
        )
        with patch("apps.inventory.views.qrcode.QRCode") as qr_class:
            qr_image = qr_class.return_value.make_image.return_value
            qr_image.save.side_effect = (
                lambda output, format: output.write(b"\x89PNG\r\n\x1a\n")
            )
            response = self.client.get(
                reverse("inventory:asset_qr_image", args=[self.asset.pk]),
                HTTP_HOST="127.0.0.1:8000",
                HTTP_X_FORWARDED_HOST="qr-example.trycloudflare.com",
                HTTP_X_FORWARDED_PROTO="https",
            )

        self.assertEqual(response.status_code, 200)
        qr_class.return_value.add_data.assert_called_once_with(expected_url)

    def test_label_uses_asset_detail_url_and_is_linked_from_detail(self):
        self.client.force_login(self.admin)
        label_url = reverse("inventory:asset_qr_label", args=[self.asset.pk])
        response = self.client.get(label_url)
        self.assertEqual(response.context["asset_url"], "http://testserver" + reverse("inventory:asset_detail", args=[self.asset.pk]))
        self.assertContains(response, reverse("inventory:asset_qr_image", args=[self.asset.pk]))
        self.assertContains(self.client.get(reverse("inventory:asset_detail", args=[self.asset.pk])), f'href="{label_url}"')

    def test_client_and_anonymous_cannot_access_qr_resources(self):
        urls = (
            reverse("inventory:asset_qr_center"),
            reverse("inventory:asset_qr_image", args=[self.asset.pk]),
            reverse("inventory:asset_qr_label", args=[self.asset.pk]),
        )
        for url in urls:
            with self.subTest(url=url, user="client"):
                self.client.force_login(self.client_user)
                self.assertEqual(self.client.get(url).status_code, 403)
            with self.subTest(url=url, user="anonymous"):
                self.client.logout()
                self.assertEqual(self.client.get(url).status_code, 302)

    def test_qr_views_are_read_only(self):
        self.client.force_login(self.admin)
        for url in (
            reverse("inventory:asset_qr_center"),
            reverse("inventory:asset_qr_image", args=[self.asset.pk]),
            reverse("inventory:asset_qr_label", args=[self.asset.pk]),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url).status_code, 405)


class ToolLoanItemAdminValidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="tool-loan-admin",
            email="tool-loan-admin@example.test",
            password="test-password-123",
            role=User.Role.ADMIN,
        )
        self.branch = Branch.objects.create(
            code="TOOLS-HQ",
            name="Sede herramientas",
        )
        self.tool = Tool.objects.create(
            name="Tester",
            branch=self.branch,
        )
        self.formset_class = inlineformset_factory(
            ToolLoan,
            ToolLoanItem,
            form=ToolLoanItemAdminForm,
            formset=ToolLoanItemInlineFormSet,
            fields=("tool",),
            extra=0,
            can_delete=True,
        )

    def create_loan(self, status=ToolLoan.Status.ACTIVE):
        loaned_at = timezone.now()
        return ToolLoan.objects.create(
            borrower=self.user,
            delivered_by=self.user,
            loaned_at=loaned_at,
            expected_return_at=loaned_at + timedelta(days=1),
            purpose="Prueba de herramientas",
            status=status,
        )

    def build_unsaved_loan(self, status=ToolLoan.Status.ACTIVE):
        loaned_at = timezone.now()
        loan = ToolLoan(
            borrower=self.user,
            delivered_by=self.user,
            loaned_at=loaned_at,
            expected_return_at=loaned_at + timedelta(days=1),
            purpose="Prueba de herramientas",
            status=status,
        )
        loan.pk = None
        return loan

    def build_formset(self, loan, tools):
        prefix = "items"
        data = {
            f"{prefix}-TOTAL_FORMS": str(len(tools)),
            f"{prefix}-INITIAL_FORMS": "0",
            f"{prefix}-MIN_NUM_FORMS": "0",
            f"{prefix}-MAX_NUM_FORMS": "1000",
        }
        for index, tool in enumerate(tools):
            data[f"{prefix}-{index}-tool"] = str(tool.pk)
        return self.formset_class(data=data, instance=loan, prefix=prefix)

    def test_allows_available_tool(self):
        loan = self.create_loan()
        formset = self.build_formset(loan, [self.tool])

        self.assertTrue(formset.is_valid(), formset.errors)
        formset.save()
        self.assertTrue(loan.items.filter(tool=self.tool).exists())

    def test_rejects_repeated_tool_in_same_loan(self):
        loan = self.build_unsaved_loan()
        formset = self.build_formset(loan, [self.tool, self.tool])

        self.assertFalse(formset.is_valid())
        self.assertIn("tool", formset.forms[1].errors)
        self.assertIn(self.tool.code, formset.forms[1].errors["tool"][0])

    def test_rejects_tool_from_another_active_loan(self):
        active_loan = self.create_loan()
        ToolLoanItem.objects.create(loan=active_loan, tool=self.tool)
        new_loan = self.build_unsaved_loan()
        formset = self.build_formset(new_loan, [self.tool])

        self.assertIsNone(new_loan.pk)
        self.assertFalse(formset.is_valid())
        message = formset.forms[0].errors["tool"][0]
        self.assertIn(self.tool.code, message)
        self.assertIn(active_loan.number, message)

    def test_allows_tool_from_returned_loan(self):
        returned_loan = self.create_loan(status=ToolLoan.Status.RETURNED)
        ToolLoanItem.objects.create(loan=returned_loan, tool=self.tool)
        new_loan = self.build_unsaved_loan()
        formset = self.build_formset(new_loan, [self.tool])

        self.assertTrue(formset.is_valid(), formset.errors)

    def test_formset_returns_field_error_instead_of_raising(self):
        active_loan = self.create_loan()
        ToolLoanItem.objects.create(loan=active_loan, tool=self.tool)
        formset = self.build_formset(self.build_unsaved_loan(), [self.tool])

        try:
            is_valid = formset.is_valid()
        except ValidationError as error:  # pragma: no cover - regresión explícita
            self.fail(f"El formset propagó ValidationError: {error}")

        self.assertFalse(is_valid)
        self.assertIn("tool", formset.forms[0].errors)


class ToolLoanServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="tool-service-user",
            email="tool-service@example.test",
            password="test-password-123",
            role=User.Role.ADMIN,
        )
        self.branch = Branch.objects.create(
            code="TOOL-SERVICE",
            name="Sede servicio de herramientas",
        )

    def create_tool(self, name, **kwargs):
        return Tool.objects.create(name=name, branch=self.branch, **kwargs)

    def create_loan(self, tools):
        loaned_at = timezone.now()
        loan = ToolLoan.objects.create(
            borrower=self.user,
            delivered_by=self.user,
            loaned_at=loaned_at,
            expected_return_at=loaned_at + timedelta(days=1),
            purpose="Préstamo de servicio",
        )
        for tool in tools:
            ToolLoanItem.objects.create(loan=loan, tool=tool)
        return loan

    def test_register_loan_marks_one_available_tool_as_loaned(self):
        tool = self.create_tool("Tester")
        loan = self.create_loan([tool])

        register_tool_loan(loan=loan)

        tool.refresh_from_db()
        loan.refresh_from_db()
        self.assertEqual(tool.status, Tool.Status.LOANED)
        self.assertEqual(loan.status, ToolLoan.Status.ACTIVE)

    def test_register_loan_requires_at_least_one_tool(self):
        loan = self.create_loan([])

        with self.assertRaises(ValidationError):
            register_tool_loan(loan=loan)

    def test_register_loan_marks_all_tools_as_loaned(self):
        tools = [self.create_tool("Tester"), self.create_tool("Taladro")]
        loan = self.create_loan(tools)

        register_tool_loan(loan=loan)

        self.assertFalse(
            Tool.objects.filter(pk__in=[tool.pk for tool in tools])
            .exclude(status=Tool.Status.LOANED)
            .exists()
        )

    def test_invalid_tool_leaves_every_tool_unchanged(self):
        available = self.create_tool("Tester")
        inactive = self.create_tool("Taladro", is_active=False)
        loan = self.create_loan([available])
        ToolLoanItem.objects.bulk_create(
            [ToolLoanItem(loan=loan, tool=inactive)]
        )

        with self.assertRaises(ValidationError):
            register_tool_loan(loan=loan)

        available.refresh_from_db()
        inactive.refresh_from_db()
        self.assertEqual(available.status, Tool.Status.AVAILABLE)
        self.assertEqual(inactive.status, Tool.Status.AVAILABLE)

    def test_loaned_tool_cannot_be_registered_again(self):
        tool = self.create_tool("Tester")
        first_loan = self.create_loan([tool])
        register_tool_loan(loan=first_loan)
        second_loan = self.create_loan([])
        ToolLoanItem.objects.bulk_create(
            [ToolLoanItem(loan=second_loan, tool=tool)]
        )

        with self.assertRaises(ValidationError):
            register_tool_loan(loan=second_loan)

    def test_tool_admin_cannot_mark_active_loan_tool_as_available(self):
        tool = self.create_tool("Tester")
        loan = self.create_loan([tool])
        register_tool_loan(loan=loan)
        tool.refresh_from_db()
        form = ToolAdminForm(
            data={
                "name": tool.name,
                "category": tool.category,
                "brand": tool.brand,
                "model": tool.model,
                "serial_number": tool.serial_number,
                "branch": str(tool.branch_id),
                "organizational_location": "",
                "status": Tool.Status.AVAILABLE,
                "description": "",
                "observations": "",
                "is_active": "on",
            },
            instance=tool,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("status", form.errors)

    def test_return_updates_loan_tools_and_return_data(self):
        tools = [self.create_tool("Tester"), self.create_tool("Taladro")]
        loan = self.create_loan(tools)
        register_tool_loan(loan=loan)

        returned = register_tool_return(
            loan=loan,
            received_by=self.user,
            return_observations="Sin novedades",
        )

        self.assertEqual(returned.status, ToolLoan.Status.RETURNED)
        self.assertIsNotNone(returned.returned_at)
        self.assertEqual(returned.received_by, self.user)
        self.assertFalse(
            Tool.objects.filter(pk__in=[tool.pk for tool in tools])
            .exclude(status=Tool.Status.AVAILABLE)
            .exists()
        )

    def test_cannot_return_same_loan_twice(self):
        tool = self.create_tool("Tester")
        loan = self.create_loan([tool])
        register_tool_loan(loan=loan)
        register_tool_return(loan=loan, received_by=self.user)

        with self.assertRaises(ValidationError):
            register_tool_return(loan=loan, received_by=self.user)

    def test_register_loan_rolls_back_if_status_update_fails(self):
        tools = [self.create_tool("Tester"), self.create_tool("Taladro")]
        loan = self.create_loan(tools)
        original_update = Tool.objects.filter(pk=tools[0].pk).update
        call_count = 0

        def failing_status_update(tool, status, *, updated_at):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("fallo simulado")
            original_update(status=status, updated_at=updated_at)

        with patch(
            "apps.inventory.services.tool_loans._set_tool_status",
            side_effect=failing_status_update,
        ), self.assertRaises(RuntimeError):
            register_tool_loan(loan=loan)

        self.assertFalse(
            Tool.objects.filter(pk__in=[tool.pk for tool in tools])
            .exclude(status=Tool.Status.AVAILABLE)
            .exists()
        )


class ToolPartialReturnTests(TestCase):
    setUp = ToolLoanServiceTests.setUp
    create_tool = ToolLoanServiceTests.create_tool
    create_loan = ToolLoanServiceTests.create_loan

    def prepare(self):
        tools = [self.create_tool(name) for name in ("A", "B", "C")]
        loan = self.create_loan(tools)
        register_tool_loan(loan=loan)
        return loan, tools, list(loan.items.order_by("tool__name"))

    def test_partial_then_final_return_and_history(self):
        loan, tools, items = self.prepare()
        first = register_tool_partial_return(
            loan=loan, item_ids=[items[0].pk], received_by=self.user,
            return_observations="Primera entrega",
        )
        self.assertEqual(first.status, ToolLoan.Status.ACTIVE)
        self.assertIsNone(first.returned_at)
        self.assertIsNone(first.received_by)
        for tool, expected in zip(tools, [Tool.Status.AVAILABLE, Tool.Status.LOANED, Tool.Status.LOANED]):
            tool.refresh_from_db()
            self.assertEqual(tool.status, expected)
        items[0].refresh_from_db()
        first_date = items[0].returned_at
        self.assertIsNotNone(first_date)
        final = register_tool_partial_return(
            loan=loan, item_ids=[item.pk for item in items[1:]], received_by=self.user,
            return_observations="Ultima entrega",
        )
        self.assertEqual(final.status, ToolLoan.Status.RETURNED)
        self.assertIsNotNone(final.returned_at)
        self.assertEqual(final.received_by, self.user)
        self.assertFalse(Tool.objects.exclude(status=Tool.Status.AVAILABLE).exists())
        items[0].refresh_from_db()
        self.assertEqual(items[0].returned_at, first_date)
        self.assertEqual(items[0].return_observations, "Primera entrega")
        self.assertEqual(items[0].received_by, self.user)

    def test_duplicate_foreign_and_empty_selection_rejected(self):
        loan, tools, items = self.prepare()
        register_tool_partial_return(loan=loan, item_ids=[items[0].pk], received_by=self.user)
        foreign = self.create_loan([self.create_tool("Other")]).items.get()
        for selection in ([items[0].pk, items[1].pk], [foreign.pk], []):
            with self.subTest(selection=selection), self.assertRaises(ValidationError):
                register_tool_partial_return(loan=loan, item_ids=selection, received_by=self.user)
        self.assertEqual(loan.items.filter(returned_at__isnull=True).count(), 2)

    def test_rollback_after_tool_update(self):
        from .services.tool_loans import _set_tool_status
        loan, tools, items = self.prepare()
        def fail_after_write(tool, status, **kwargs):
            _set_tool_status(tool, status, **kwargs)
            raise RuntimeError("simulated failure")
        with patch("apps.inventory.services.tool_loans._set_tool_status", side_effect=fail_after_write):
            with self.assertRaises(RuntimeError):
                register_tool_partial_return(loan=loan, item_ids=[items[0].pk], received_by=self.user)
        loan.refresh_from_db()
        self.assertEqual(loan.status, ToolLoan.Status.ACTIVE)
        self.assertIsNone(loan.returned_at)
        self.assertEqual(loan.items.filter(returned_at__isnull=True).count(), 3)
        self.assertEqual(Tool.objects.filter(status=Tool.Status.LOANED).count(), 3)

    def test_migration_copies_legacy_returns_without_changing_active_items(self):
        from importlib import import_module
        from django.apps import apps
        from django.db import connection
        from types import SimpleNamespace
        loan, tools, items = self.prepare()
        legacy = self.create_loan([self.create_tool("Legacy")])
        when = timezone.now()
        ToolLoan.objects.filter(pk=legacy.pk).update(
            status=ToolLoan.Status.RETURNED, returned_at=when,
            received_by=self.user, return_observations="Legacy history",
        )
        migration = import_module("apps.inventory.migrations.0017_toolloanitem_received_by_and_more")
        migration.copy_existing_returns(apps, SimpleNamespace(connection=connection))
        item = legacy.items.get()
        self.assertEqual(item.returned_at, when)
        self.assertEqual(item.received_by, self.user)
        self.assertEqual(item.return_observations, "Legacy history")
        self.assertEqual(loan.items.filter(returned_at__isnull=True).count(), 3)

    def test_returned_tool_can_be_reloaned_before_original_closes(self):
        from .forms import ToolLoanQuickForm
        loan, tools, items = self.prepare()
        register_tool_partial_return(loan=loan, item_ids=[items[0].pk], received_by=self.user)
        tools[0].refresh_from_db()
        self.assertIsNone(tools[0].current_loan)
        self.assertIn(tools[0], ToolLoanQuickForm(user=self.user).fields["tools"].queryset)
        second = self.create_loan([tools[0]])
        register_tool_loan(loan=second)
        register_tool_return(loan=loan, received_by=self.user)
        tools[0].refresh_from_db()
        self.assertEqual(tools[0].status, Tool.Status.LOANED)
        self.assertEqual(tools[0].current_loan, second)


class ToolLoanAdminServiceIntegrationTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="tool-admin-service",
            email="tool-admin-service@example.test",
            password="test-password-123",
        )
        self.borrower = User.objects.create_user(
            username="tool-borrower",
            email="tool-borrower@example.test",
            password="test-password-123",
        )
        self.branch = Branch.objects.create(
            code="TOOL-ADMIN-SERVICE",
            name="Sede Admin herramientas",
        )
        self.tool = Tool.objects.create(name="Tester Admin", branch=self.branch)
        self.client.force_login(self.admin_user)

    def loan_form_data(self, *, status, received_by="", returned_at=None):
        loaned_at = timezone.now().replace(microsecond=0)
        expected_at = loaned_at + timedelta(days=1)
        data = {
            "borrower": str(self.borrower.pk),
            "delivered_by": str(self.admin_user.pk),
            "loaned_at_0": loaned_at.date().isoformat(),
            "loaned_at_1": loaned_at.time().isoformat(),
            "expected_return_at_0": expected_at.date().isoformat(),
            "expected_return_at_1": expected_at.time().isoformat(),
            "purpose": "Préstamo desde Admin",
            "observations": "",
            "returned_at_0": "",
            "returned_at_1": "",
            "received_by": received_by,
            "return_observations": "Devuelta desde Admin" if received_by else "",
            "status": status,
            "items-TOTAL_FORMS": "1",
            "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0",
            "items-MAX_NUM_FORMS": "1000",
            "items-0-tool": str(self.tool.pk),
        }
        if returned_at:
            data["returned_at_0"] = returned_at.date().isoformat()
            data["returned_at_1"] = returned_at.time().isoformat()
        return data

    def test_admin_creates_loan_and_marks_tool_as_loaned(self):
        response = self.client.post(
            reverse("admin:inventory_toolloan_add"),
            self.loan_form_data(status=ToolLoan.Status.ACTIVE),
        )

        self.assertEqual(response.status_code, 302, response.context and response.context["errors"])
        self.tool.refresh_from_db()
        self.assertEqual(self.tool.status, Tool.Status.LOANED)

    def test_admin_returns_loan_and_marks_tool_as_available(self):
        loaned_at = timezone.now()
        loan = ToolLoan.objects.create(
            borrower=self.borrower,
            delivered_by=self.admin_user,
            loaned_at=loaned_at,
            expected_return_at=loaned_at + timedelta(days=1),
            purpose="Préstamo para devolución Admin",
        )
        ToolLoanItem.objects.create(loan=loan, tool=self.tool)
        register_tool_loan(loan=loan)
        returned_at = timezone.now()
        data = self.loan_form_data(
            status=ToolLoan.Status.RETURNED,
            received_by=str(self.admin_user.pk),
            returned_at=returned_at,
        )
        data.update({
            "items-INITIAL_FORMS": "1",
            "items-0-id": str(loan.items.get().pk),
        })

        response = self.client.post(
            reverse("admin:inventory_toolloan_change", args=[loan.pk]),
            data,
        )

        self.assertEqual(response.status_code, 302, response.context and response.context["errors"])
        loan.refresh_from_db()
        self.tool.refresh_from_db()
        self.assertEqual(loan.status, ToolLoan.Status.RETURNED)
        self.assertEqual(self.tool.status, Tool.Status.AVAILABLE)


class ToolLoanPublicViewsTests(TestCase):
    def setUp(self):
        self.admin_user = self.create_user("tools-public-admin", User.Role.ADMIN)
        self.supervisor = self.create_user("tools-public-supervisor", User.Role.SUPERVISOR)
        self.technician = self.create_user("tools-public-tech", User.Role.TECHNICIAN)
        self.client_user = self.create_user("tools-public-client", User.Role.CLIENT)
        self.branch = Branch.objects.create(code="TOOLS-PUBLIC", name="Sede pública")
        self.other_branch = Branch.objects.create(code="TOOLS-OTHER", name="Otra sede")
        self.tool = Tool.objects.create(
            name="Tester digital",
            category="Medición",
            brand="Fluke",
            model="117",
            branch=self.branch,
        )
        self.other_tool = Tool.objects.create(
            name="Taladro",
            category="Eléctrica",
            brand="Bosch",
            model="GSB",
            branch=self.other_branch,
        )

    def create_user(self, username, role):
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.test",
            password="test-password-123",
            role=role,
        )

    def loan_data(self, tools):
        loaned_at = timezone.localtime().replace(second=0, microsecond=0)
        return {
            "borrower": str(self.technician.pk),
            "delivered_by": str(self.admin_user.pk),
            "loaned_at": loaned_at.strftime("%Y-%m-%dT%H:%M"),
            "expected_return_at": (loaned_at + timedelta(days=1)).strftime(
                "%Y-%m-%dT%H:%M"
            ),
            "purpose": "Trabajo en sede",
            "observations": "",
            "tools": [str(tool.pk) for tool in tools],
        }

    def create_active_loan(self, borrower, tools, expected_return_at=None):
        loaned_at = timezone.now()
        if expected_return_at and expected_return_at <= loaned_at:
            loaned_at = expected_return_at - timedelta(days=1)
        loan = ToolLoan.objects.create(
            borrower=borrower,
            delivered_by=self.admin_user,
            loaned_at=loaned_at,
            expected_return_at=(
                expected_return_at or loaned_at + timedelta(days=1)
            ),
            purpose="Trabajo de campo",
        )
        ToolLoanItem.objects.bulk_create(
            ToolLoanItem(loan=loan, tool=tool) for tool in tools
        )
        register_tool_loan(loan=loan)
        return loan

    def test_access_by_role(self):
        quick_url = reverse("inventory:tool_loan_quick_create")
        list_url = reverse("inventory:tool_loan_active_list")
        for user in (self.admin_user, self.supervisor, self.technician):
            with self.subTest(role=user.role):
                self.client.force_login(user)
                self.assertEqual(self.client.get(quick_url).status_code, 200)
                self.assertEqual(self.client.get(list_url).status_code, 200)

        self.client.force_login(self.client_user)
        self.assertEqual(self.client.get(quick_url).status_code, 403)
        self.client.force_login(self.technician)
        self.assertEqual(
            self.client.post(quick_url, self.loan_data([self.tool])).status_code,
            403,
        )

    def test_create_loan_with_one_tool(self):
        self.client.force_login(self.admin_user)
        response = self.client.post(
            reverse("inventory:tool_loan_quick_create"),
            self.loan_data([self.tool]),
        )

        loan = ToolLoan.objects.get()
        self.assertRedirects(
            response,
            reverse("inventory:tool_loan_detail", args=[loan.pk]),
        )
        self.assertEqual(loan.items.count(), 1)
        self.tool.refresh_from_db()
        self.assertEqual(self.tool.status, Tool.Status.LOANED)

    def test_create_loan_with_multiple_tools(self):
        self.client.force_login(self.supervisor)
        response = self.client.post(
            reverse("inventory:tool_loan_quick_create"),
            self.loan_data([self.tool, self.other_tool]),
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(ToolLoan.objects.get().items.count(), 2)
        self.assertEqual(
            Tool.objects.filter(status=Tool.Status.LOANED).count(),
            2,
        )

    def test_rejects_submission_without_tools(self):
        self.client.force_login(self.admin_user)
        data = self.loan_data([])
        response = self.client.post(
            reverse("inventory:tool_loan_quick_create"), data
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Seleccione al menos una herramienta")
        self.assertFalse(ToolLoan.objects.exists())

    def test_rejects_tool_that_is_no_longer_available(self):
        self.create_active_loan(self.technician, [self.tool])
        self.client.force_login(self.admin_user)
        response = self.client.post(
            reverse("inventory:tool_loan_quick_create"),
            self.loan_data([self.tool]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ya no está disponible")
        self.assertEqual(ToolLoan.objects.count(), 1)

    def test_available_tool_search(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(
            reverse("inventory:tool_loan_quick_create"), {"q": "Fluke 117"}
        )

        self.assertContains(response, self.tool.code)
        self.assertNotContains(response, self.other_tool.code)

    def test_available_tool_filters_by_category_and_branch(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(
            reverse("inventory:tool_loan_quick_create"),
            {"category": "Medición", "branch": str(self.branch.pk)},
        )

        self.assertContains(response, self.tool.code)
        self.assertNotContains(response, self.other_tool.code)

    def test_active_list_and_technician_scope(self):
        own = self.create_active_loan(self.technician, [self.tool])
        other = self.create_active_loan(self.supervisor, [self.other_tool])
        self.client.force_login(self.technician)
        response = self.client.get(reverse("inventory:tool_loan_active_list"))

        self.assertContains(response, own.number)
        self.assertNotContains(response, other.number)

    def test_active_list_filters_and_indicators(self):
        overdue = self.create_active_loan(
            self.technician,
            [self.tool],
            expected_return_at=timezone.now() - timedelta(days=1, hours=1),
        )
        due_today = self.create_active_loan(
            self.supervisor,
            [self.other_tool],
            expected_return_at=timezone.now() + timedelta(hours=1),
        )
        self.client.force_login(self.admin_user)
        response = self.client.get(
            reverse("inventory:tool_loan_active_list"),
            {"scope": "overdue", "tool": self.tool.code},
        )

        self.assertContains(response, overdue.number)
        self.assertNotContains(response, due_today.number)
        self.assertEqual(response.context["indicators"]["borrowed_tools"], 2)
        self.assertEqual(response.context["indicators"]["active_loans"], 2)
        self.assertEqual(response.context["indicators"]["overdue"], 1)
        self.assertEqual(response.context["indicators"]["due_today"], 1)


class ToolPartialReturnViewTests(TestCase):
    setUp = ToolLoanPublicViewsTests.setUp
    create_user = ToolLoanPublicViewsTests.create_user
    create_active_loan = ToolLoanPublicViewsTests.create_active_loan

    def test_manager_roles_and_pending_display(self):
        loan = self.create_active_loan(self.technician, [self.tool, self.other_tool])
        url = reverse("inventory:tool_loan_detail", args=[loan.pk])
        items = list(loan.items.all())
        for user, item in zip([self.admin_user, self.supervisor], items):
            self.client.force_login(user)
            response = self.client.post(url, {"items": [str(item.pk)], "received_by": user.pk, "return_observations": "Recibida"})
            self.assertRedirects(response, url)
            response = self.client.get(url)
            self.assertContains(response, "Devuelta")
            self.assertContains(response, "Recibida")
            self.assertNotContains(response, f'value="{item.pk}"')
            if user == self.admin_user:
                self.assertContains(response, "Pendiente")
                self.assertContains(response, f'value="{items[1].pk}"')
        loan.refresh_from_db()
        self.assertEqual(loan.status, ToolLoan.Status.RETURNED)
        self.assertNotContains(response, "Registrar devoluci\u00f3n")

    def test_technician_read_only_own_loan_and_client_denied(self):
        loan = self.create_active_loan(self.technician, [self.tool])
        url = reverse("inventory:tool_loan_detail", args=[loan.pk])
        self.client.force_login(self.technician)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="tool-return-form"')
        self.assertEqual(self.client.post(url, {"items": [loan.items.get().pk], "received_by": self.admin_user.pk}).status_code, 403)
        other = self.create_active_loan(self.admin_user, [self.other_tool])
        self.assertEqual(self.client.get(reverse("inventory:tool_loan_detail", args=[other.pk])).status_code, 403)
        self.client.force_login(self.client_user)
        self.assertEqual(self.client.post(url, {}).status_code, 403)
        loan.refresh_from_db()
        self.assertEqual(loan.status, ToolLoan.Status.ACTIVE)

    def test_invalid_and_repeated_post_do_not_return_other_items(self):
        loan = self.create_active_loan(self.technician, [self.tool, self.other_tool])
        url = reverse("inventory:tool_loan_detail", args=[loan.pk])
        self.client.force_login(self.admin_user)
        self.assertEqual(self.client.post(url, {}).status_code, 200)
        data = {"items": [str(loan.items.first().pk)], "received_by": self.admin_user.pk}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(self.client.post(url, data).status_code, 200)
        self.assertEqual(loan.items.filter(returned_at__isnull=True).count(), 1)


class ToolCatalogViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_user(username="catalog-admin", email="catalog-admin@example.test", role=User.Role.ADMIN)
        cls.supervisor = User.objects.create_user(username="catalog-supervisor", email="catalog-supervisor@example.test", role=User.Role.SUPERVISOR)
        cls.technician = User.objects.create_user(username="catalog-tech", email="catalog-tech@example.test", role=User.Role.TECHNICIAN)
        cls.other_user = User.objects.create_user(username="catalog-other", email="catalog-other@example.test", role=User.Role.TECHNICIAN)
        cls.client_user = User.objects.create_user(username="catalog-client", email="catalog-client@example.test", role=User.Role.CLIENT)
        cls.auditor = User.objects.create_user(username="catalog-auditor", email="catalog-auditor@example.test", role=User.Role.AUDITOR)
        cls.branch = Branch.objects.create(code="CAT-A", name="Catalog A")
        cls.other_branch = Branch.objects.create(code="CAT-B", name="Catalog B")
        cls.location = OrganizationalLocation.objects.create(branch=cls.branch, code="CAT-LOC", name="Taller")
        cls.available = Tool.objects.create(name="Tester digital", category="Medicion", brand="Fluke", model="117", serial_number="SER-991", branch=cls.branch, organizational_location=cls.location)
        cls.own = Tool.objects.create(name="Pinza propia", branch=cls.branch)
        cls.other = Tool.objects.create(name="Taladro ajeno", branch=cls.other_branch)
        cls.returned = Tool.objects.create(name="Cutter devuelto", branch=cls.other_branch)
        cls.repair = Tool.objects.create(name="En taller", status=Tool.Status.REPAIR, branch=cls.branch)
        cls.orphan = Tool.objects.create(name="Sin cabecera", status=Tool.Status.LOANED, branch=cls.branch)
        cls.retired = Tool.objects.create(name="Retirada", status=Tool.Status.RETIRED, is_active=False, branch=cls.branch)
        now = timezone.now()
        def loan(borrower, tools, expected):
            record = ToolLoan.objects.create(borrower=borrower, delivered_by=cls.admin_user,
                loaned_at=now-timedelta(days=3), expected_return_at=expected, purpose="Catalog test")
            ToolLoanItem.objects.bulk_create([ToolLoanItem(loan=record, tool=tool) for tool in tools])
            register_tool_loan(loan=record)
            return record
        cls.own_loan = loan(cls.technician, [cls.own], now+timedelta(days=1))
        cls.other_loan = loan(cls.other_user, [cls.other, cls.returned], now-timedelta(days=1))
        register_tool_partial_return(loan=cls.other_loan,
            item_ids=[cls.other_loan.items.get(tool=cls.returned).pk], received_by=cls.admin_user)
        cls.url = reverse("inventory:tool_list")

    def rows(self, response):
        return {tool.pk: tool for tool in response.context["tools"]}

    def test_admin_and_supervisor_see_all_and_navigation(self):
        for user in (self.admin_user, self.supervisor):
            with self.subTest(role=user.role):
                self.client.force_login(user)
                response = self.client.get(self.url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(set(self.rows(response)), set(Tool.objects.values_list("pk", flat=True)))
                self.assertContains(response, 'href="/inventario/herramientas/" aria-current="page"')
                self.assertContains(response, '+ Préstamo rápido', count=1)
                self.assertNotContains(response, 'Próximamente')

    def test_technician_scope_and_private_loan_information(self):
        self.client.force_login(self.technician)
        response = self.client.get(self.url)
        self.assertEqual(set(self.rows(response)), {self.available.pk, self.own.pk, self.returned.pk})
        self.assertContains(response, self.own_loan.borrower_name)
        self.assertNotContains(response, self.other_loan.borrower_name)
        self.assertNotContains(response, str(self.other_loan.pk))
        self.assertNotContains(response, self.other.code)
        self.assertEqual(response.context["indicators"], {"total": 3, "available": 2, "loaned": 1, "overdue": 0, "repair": 0})
        self.assertNotContains(response, '+ Préstamo rápido')

    def test_unauthorized_roles_and_anonymous(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        for user in (self.client_user, self.auditor):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_indicators_current_loan_and_partial_return(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(self.url)
        self.assertEqual(response.context["indicators"], {"total": 6, "available": 2, "loaned": 3, "overdue": 1, "repair": 1})
        rows = self.rows(response)
        self.assertEqual(rows[self.own.pk].display_loan.pk, self.own_loan.pk)
        self.assertEqual(rows[self.own.pk].display_loan.borrower, self.technician)
        self.assertEqual(rows[self.own.pk].display_loan.expected_return_at, self.own_loan.expected_return_at)
        self.assertEqual(rows[self.other.pk].display_loan.pk, self.other_loan.pk)
        self.assertTrue(rows[self.other.pk].has_overdue_loan)
        self.assertContains(response, 'Vencida</span>')
        self.assertContains(response, reverse("inventory:tool_loan_detail", args=[self.other_loan.pk]))
        for tool in (self.available, self.returned, self.orphan):
            self.assertIsNone(rows[tool.pk].display_loan)
            self.assertFalse(rows[tool.pk].has_overdue_loan)
        self.assertEqual(rows[self.orphan.pk].status, Tool.Status.LOANED)
        self.orphan.refresh_from_db()
        self.assertEqual(self.orphan.status, Tool.Status.LOANED)

    def test_status_category_branch_and_combined_filters(self):
        self.client.force_login(self.admin_user)
        cases = [
            ({"status": "AVAILABLE"}, {self.available.pk, self.returned.pk}),
            ({"status": "LOANED"}, {self.own.pk, self.other.pk, self.orphan.pk}),
            ({"status": "OVERDUE"}, {self.other.pk}),
            ({"status": "REPAIR"}, {self.repair.pk}),
            ({"status": "RETIRED"}, {self.retired.pk}),
            ({"status": "OUT_OF_SERVICE"}, set()),
            ({"status": "LOST"}, set()),
            ({"category": "Medicion"}, {self.available.pk}),
            ({"branch": str(self.other_branch.pk)}, {self.other.pk, self.returned.pk}),
            ({"branch": "invalid"}, set()),
            ({"q": "Fluke 117", "status": "AVAILABLE", "category": "Medicion", "branch": str(self.branch.pk)}, {self.available.pk}),
        ]
        for filters, expected in cases:
            with self.subTest(filters=filters):
                response = self.client.get(self.url, filters)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(set(self.rows(response)), expected)
                self.assertEqual(response.context["indicators"]["total"], 6)

    def test_search_fields_and_multiple_terms(self):
        self.client.force_login(self.admin_user)
        for query in (self.available.code, "Tester", "Medicion", "Fluke 117", "SER-991", "digital Fluke 117"):
            with self.subTest(query=query):
                self.assertEqual(set(self.rows(self.client.get(self.url, {"q": query}))), {self.available.pk})
        self.assertEqual(set(self.rows(self.client.get(self.url, {"q": "Fluke unknown"}))), set())

    def test_technician_filters_cannot_expose_other_loans(self):
        self.client.force_login(self.technician)
        for filters in ({"status": "OVERDUE"}, {"q": self.other.code}, {"status": "LOANED", "branch": str(self.other_branch.pk)}):
            self.assertEqual(set(self.rows(self.client.get(self.url, filters))), set())
        # Even an inconsistent AVAILABLE tool must not expose someone else's loan.
        Tool.objects.filter(pk=self.other.pk).update(status=Tool.Status.AVAILABLE)
        response = self.client.get(self.url)
        self.assertIsNone(self.rows(response)[self.other.pk].display_loan)
        self.assertNotContains(response, self.other_loan.borrower_name)
        self.assertNotContains(response, str(self.other_loan.pk))

    def test_query_count_does_not_grow_per_tool(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        self.client.force_login(self.admin_user)
        with CaptureQueriesContext(connection) as first:
            self.client.get(self.url)
        extra = []
        for index in range(15):
            extra.append(Tool.objects.create(name=f"Extra {index}", branch=self.branch, organizational_location=self.location))
        loan = ToolLoan.objects.create(borrower=self.technician, delivered_by=self.admin_user,
            expected_return_at=timezone.now()+timedelta(days=1), purpose="Query test")
        ToolLoanItem.objects.bulk_create([ToolLoanItem(loan=loan, tool=tool) for tool in extra])
        register_tool_loan(loan=loan)
        with CaptureQueriesContext(connection) as second:
            response = self.client.get(self.url)
        self.assertEqual(len(self.rows(response)), 22)
        self.assertEqual(len(second), len(first))

    def test_pagination_preserves_filters(self):
        self.client.force_login(self.admin_user)
        Tool.objects.bulk_create([Tool(code=f"CAT-PAGE-{index:03}", name="Pagination", branch=self.branch) for index in range(55)])
        response = self.client.get(self.url, {"q": "Pagination", "status": "AVAILABLE"})
        self.assertEqual(len(self.rows(response)), 50)
        self.assertContains(response, 'q=Pagination&amp;status=AVAILABLE&amp;page=2')
        response = self.client.get(self.url, {"q": "Pagination", "status": "AVAILABLE", "page": 2})
        self.assertEqual(len(self.rows(response)), 5)
