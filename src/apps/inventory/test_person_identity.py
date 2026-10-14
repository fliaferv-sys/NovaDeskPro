from unittest.mock import patch

from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Branch, User
from apps.accounts.tests import TEST_STORAGES
from apps.core.models import Department
from apps.directory.identity_policies import authorize_identity_context, issue_identity_reference
from apps.directory.person_references import person_snapshot
from apps.integrations.technical_context import local_assets
from .forms import AssetForm, StockDeliveryForm, ToolLoanQuickForm
from .models import Asset, AcquisitionBatch, OrganizationalLocation, StockBalance, StockDelivery, StockDeliveryLine, StockMovement, StockProduct, StockCategory, Tool, ToolLoan
from .services.stock import complete_stock_delivery, prepare_stock_delivery


@override_settings(STORAGES=TEST_STORAGES)
class InventoryPersonIdentityTests(TestCase):
    def setUp(self):
        self.actor = User.objects.create_superuser(username="person-admin", email="person-admin@example.test", password="test-password")
        self.local = User.objects.create_user(username="persona", email="persona@petropar.gov.py", first_name="Persona", last_name="Local")
        self.identity = dict(source="RRHH", rrhh_id=73, local_user_id=None, full_name="Persona Institucional",
                             email="persona@petropar.gov.py", username="persona", is_active=True,
                             _locator={"source": "RRHH", "id": 73})
        self.request = RequestFactory().post("/inventario/")
        self.request.user = self.actor
        self.branch = Branch.objects.create(code="TEST-PERSON", name="Sede del activo")
        self.location = OrganizationalLocation.objects.create(code="TEST-PERSON-LOC", name="Depósito", branch=self.branch)
        self.batch = AcquisitionBatch.objects.create(code="PERSON-BATCH", description="Lote", date="2026-10-14")
        self.department = Department.objects.create(code="TEST-PERSON-SUPPORT", name="Soporte operativo")

    def reference(self, kind, identity=None, obj=None, admin_context=False):
        context = "inventory." + ("admin." if admin_context else "") + kind + (".change" if obj else ".add")
        policy = authorize_identity_context(self.request, context, str(obj.pk) if obj else "")
        return issue_identity_reference(self.request, policy, identity or self.identity)

    def asset_data(self, **changes):
        data = dict(acquisition_batch=str(self.batch.pk), patrimonial_code="PERSON-PATRIMONY", brand="Marca", model="Modelo", serial_number="PERSON-SERIAL", connection_status="UNKNOWN", internal_code="PERSON-ASSET", asset_type="DESKTOP", condition="NEW", operational_status="OPERATIONAL",
                    branch=str(self.branch.pk), assigned_user="", institutional_identity_ref=self.reference("asset"))
        data.update(changes)
        return data

    def test_asset_selection_without_account_and_no_account_creation(self):
        count = User.objects.count()
        with patch("apps.directory.identity_policies.resolve_common_identity", return_value=self.identity):
            form = AssetForm(self.asset_data(), request=self.request)
            self.assertTrue(form.is_valid(), form.errors)
            asset = form.save()
        self.assertIsNone(asset.assigned_user_id)
        self.assertEqual(asset.custodian_display_name, "Persona Institucional")
        self.assertEqual(asset.branch, self.branch)
        self.assertEqual(User.objects.count(), count)
        matches = local_assets("PERSON-SERIAL", self.actor, {"PERSON-SERIAL": [asset]})
        self.assertEqual(matches[0]["responsible"]["full_name"], "Persona Institucional")
        self.assertFalse(matches[0]["can_select"])

    def test_local_link_coexists_with_institutional_reference(self):
        identity = {**self.identity, "local_user_id": str(self.local.pk)}
        with patch("apps.directory.identity_policies.resolve_common_identity", return_value=identity):
            form = AssetForm(self.asset_data(institutional_identity_ref=self.reference("asset", identity)), request=self.request)
            self.assertTrue(form.is_valid(), form.errors)
            asset = form.save()
        self.assertEqual(asset.assigned_user, self.local)
        self.assertEqual(asset.custodian_identity["local_user_id"], str(self.local.pk))

    def test_reference_cannot_be_reused_for_another_module_actor_or_object(self):
        for reference in (self.reference("loan"), "invalid-reference"):
            form = AssetForm(self.asset_data(institutional_identity_ref=reference), request=self.request)
            self.assertFalse(form.is_valid())
        other_request = RequestFactory().post("/"); other_request.user = self.local
        form = AssetForm(self.asset_data(), request=other_request)
        with self.assertRaises(PermissionDenied):
            form.is_valid()

    def test_inactive_identity_is_rejected(self):
        with patch("apps.directory.identity_policies.resolve_common_identity", return_value={**self.identity, "is_active": False}):
            form = AssetForm(self.asset_data(), request=self.request)
            self.assertFalse(form.is_valid())

    def test_edit_get_preserves_reference_and_fk_without_resolving_selection(self):
        asset = Asset.objects.create(internal_code="HISTORY", assigned_user=self.local, custodian_identity=person_snapshot(self.identity))
        before = Asset.objects.values().get(pk=asset.pk)
        self.client.force_login(self.actor)
        with patch("apps.directory.identity_policies.resolve_common_identity") as resolve:
            response = self.client.get(reverse("inventory:asset_update", args=[asset.pk]))
        self.assertEqual(response.status_code, 200)
        resolve.assert_not_called()
        self.assertEqual(before, Asset.objects.values().get(pk=asset.pk))

    def test_admin_has_explicit_selector_and_signed_selection(self):
        model_admin = admin.site._registry[Asset]
        reference = self.reference("asset", admin_context=True)
        with patch("apps.directory.identity_policies.resolve_common_identity", return_value=self.identity):
            form = model_admin.get_form(self.request)(data=self.asset_data(institutional_identity_ref=reference))
            self.assertTrue(form.is_valid(), form.errors)
            asset = form.save()
        self.assertEqual(asset.custodian_identity["locator"], self.identity["_locator"])

    def test_delivery_without_account_preserves_recipient_in_stock_history(self):
        data = dict(recipient="", department=str(self.department.pk), branch=str(self.branch.pk),
                    delivery_responsible=str(self.actor.pk), delivery_date="2026-10-14",
                    institutional_identity_ref=self.reference("delivery"))
        with patch("apps.directory.identity_policies.resolve_common_identity", return_value=self.identity):
            form = StockDeliveryForm(data, request=self.request)
            self.assertTrue(form.is_valid(), form.errors)
            delivery = form.save(commit=False); delivery.created_by = self.actor; delivery.save()
        product = StockProduct.objects.create(name="Producto", reference_code="PERSON-PRODUCT", category=StockCategory.objects.create(name="Categoría", code="PERSON-CATEGORY"))
        StockBalance.objects.create(product=product, branch=self.branch, organizational_location=self.location, quantity=3)
        StockDeliveryLine.objects.create(delivery=delivery, product=product, source_branch=self.branch, source_location=self.location, quantity=1)
        prepare_stock_delivery(delivery=delivery)
        complete_stock_delivery(delivery=delivery, completed_by=self.actor)
        delivery.refresh_from_db()
        self.assertIsNone(delivery.recipient_id)
        self.assertEqual(delivery.recipient_name, "Persona Institucional")
        movement = StockMovement.objects.get()
        self.assertEqual(movement.recipient_identity, delivery.recipient_identity)
        self.assertEqual(movement.performed_by, self.actor)
        self.assertEqual(delivery.department, self.department)

    def test_tool_borrower_without_account_and_actor_remains_local(self):
        tool = Tool.objects.create(code="PERSON-TOOL", name="Herramienta", branch=self.branch)
        data = dict(borrower="", delivered_by=str(self.actor.pk), loaned_at="2026-10-14T10:00",
                    expected_return_at="2026-10-15T10:00", purpose="Trabajo", tools=[str(tool.pk)],
                    institutional_identity_ref=self.reference("loan"))
        with patch("apps.directory.identity_policies.resolve_common_identity", return_value=self.identity):
            form = ToolLoanQuickForm(data, request=self.request, user=self.actor)
            self.assertTrue(form.is_valid(), form.errors)
        loan = ToolLoan.objects.create(borrower=form.cleaned_data["borrower"], borrower_identity=form.cleaned_data["borrower_identity"],
                                      delivered_by=self.actor, purpose="Trabajo", expected_return_at=timezone.now()+timezone.timedelta(days=1))
        self.assertIsNone(loan.borrower_id)
        self.assertEqual(loan.borrower_name, "Persona Institucional")
        self.assertEqual(loan.delivered_by, self.actor)

    def test_missing_person_does_not_create_loan_or_delivery(self):
        with self.assertRaises(ValidationError):
            ToolLoan.objects.create(delivered_by=self.actor, purpose="Trabajo", expected_return_at=timezone.now()+timezone.timedelta(days=1))
        with self.assertRaises(ValidationError):
            StockDelivery.objects.create(created_by=self.actor, delivery_responsible=self.actor, department=self.department, branch=self.branch)

    def test_existing_user_foreign_keys_and_names_remain_usable(self):
        loan = ToolLoan.objects.create(borrower=self.local, delivered_by=self.actor, purpose="Trabajo", expected_return_at=timezone.now()+timezone.timedelta(days=1))
        delivery = StockDelivery.objects.create(recipient=self.local, created_by=self.actor, delivery_responsible=self.actor,
                                               department=self.department, branch=self.branch)
        self.assertEqual(loan.borrower_id, self.local.pk)
        self.assertEqual(delivery.recipient_id, self.local.pk)
        self.assertEqual(loan.borrower_identity, {})
        self.assertEqual(delivery.recipient_identity, {})
