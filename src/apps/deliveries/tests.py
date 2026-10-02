import uuid
from datetime import date
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import Permission
from django.contrib.messages import get_messages
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Branch, User
from apps.directory.identity_services import InstitutionalIdentityError
from apps.inventory.models import Asset, AcquisitionBatch, AcquisitionBatchDocument

from .forms import AssetCustodyMovementForm, DeliveryBatchForm
from .models import (
    AssetCustodyMovement,
    DeliveryBatch,
    DeliveryBatchDocument,
    DeliveryDocument,
)
from .views import update_asset_custody


def grant_delivery_permissions(user, *codenames):
    permissions = Permission.objects.filter(
        content_type__app_label="deliveries",
        codename__in=codenames,
    )
    user.user_permissions.add(*permissions)


def grant_all_delivery_permissions(user):
    permissions = Permission.objects.filter(content_type__app_label="deliveries")
    user.user_permissions.add(*permissions)


def rrhh_recipient_identity(**overrides):
    identity = {
        "source": "RRHH",
        "id_personal": 1234,
        "employee_number": "LEG-1234",
        "name": "Persona RRHH",
        "first_name": "",
        "last_name": "",
        "email": "persona.rrhh@example.test",
        "phone": "0981000000",
        "location": "Ubicación RRHH",
        "position": "Cargo RRHH",
        "employment_type": "Permanente",
        "status": "Activo",
        "username": "",
        "is_active": True,
    }
    identity.update(overrides)
    return identity


def ad_recipient_identity(**overrides):
    identity = {
        "source": "ACTIVE_DIRECTORY",
        "id_personal": None,
        "employee_number": "",
        "name": "Persona AD",
        "first_name": "Persona",
        "last_name": "AD",
        "email": "persona.ad@example.test",
        "phone": "",
        "location": "",
        "position": "",
        "employment_type": "",
        "status": "Activo",
        "username": "persona.ad",
        "is_active": True,
    }
    identity.update(overrides)
    return identity


class InstitutionalRecipientFormTestBase(TestCase):
    def setUp(self):
        suffix = uuid.uuid4().hex[:8]
        self.responsible = User.objects.create_user(
            username=f"institutional-responsible-{suffix}",
            email=f"responsible-{suffix}@example.test",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.director = User.objects.create_user(
            username=f"institutional-director-{suffix}",
            email=f"director-{suffix}@example.test",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.branch = Branch.objects.create(
            code=f"INST-{suffix}",
            name=f"Sede institucional {suffix}",
            branch_type=Branch.BranchType.HEADQUARTERS,
        )
        self.acquisition_batch = AcquisitionBatch.objects.create(
            code=f"INST-BATCH-{suffix}",
            date=date.today(),
            status=AcquisitionBatch.Status.VALIDATED,
            expected_quantity=1,
            received_by=self.responsible,
        )
        self.asset = Asset.objects.create(
            internal_code=f"INST-ASSET-{suffix}",
            brand="Marca de prueba",
            model="Modelo de prueba",
            patrimonial_code=f"PAT-{suffix}",
            serial_number=f"SER-{suffix}",
            acquisition_batch=self.acquisition_batch,
            branch=self.branch,
        )
        AcquisitionBatchDocument.objects.create(
            batch=self.acquisition_batch,
            document_type=AcquisitionBatchDocument.DocumentType.RECEIPT_REPORT,
            file=SimpleUploadedFile("receipt.pdf", b"%PDF-1.4 test receipt"),
            uploaded_by=self.responsible,
            verified=True,
        )

    def create_local_user(self, username, email, **fields):
        return User.objects.create_user(
            username=username,
            email=email,
            password="test-password",
            role=User.Role.CLIENT,
            **fields,
        )

    def delivery_batch_data(self, **recipient_fields):
        data = {
            "assets": [str(self.asset.pk)],
            "delivery_responsible": str(self.responsible.pk),
            "authorizing_director": str(self.director.pk),
            "destination_branch": str(self.branch.pk),
            "department": "Departamento de prueba",
            "location": "Ubicación de prueba",
            "delivery_date": "2026-10-02T10:00",
            "recipient_id_personal": "",
            "recipient_name": "Nombre falso",
            "recipient_email": "",
            "recipient_source": "LOCAL",
            "recipient": "",
            "recipient_employee_number": "FALSO",
            "recipient_position": "Cargo falso",
            "recipient_area": "",
            "recipient_unit": "",
            "recipient_section": "",
        }
        data.update(recipient_fields)
        return data

    def movement_data(self, movement_type, **recipient_fields):
        data = {
            "asset": str(self.asset.pk),
            "movement_type": movement_type,
            "status": AssetCustodyMovement.MovementStatus.IN_DELIVERY_PROCESS,
            "previous_custodian": "",
            "recipient_id_personal": "",
            "recipient_name": "Nombre falso",
            "recipient_email": "",
            "recipient_source": "LOCAL",
            "recipient": "",
            "recipient_employee_number": "FALSO",
            "recipient_position": "Cargo falso",
            "recipient_area": "",
            "recipient_unit": "",
            "recipient_section": "",
            "delivery_responsible": str(self.responsible.pk),
            "authorizing_director": str(self.director.pk),
            "department": "Departamento manual",
            "destination_branch": str(self.branch.pk),
            "location": "Ubicación manual",
            "movement_date": "2026-10-02T10:00",
        }
        data.update(recipient_fields)
        return data


class DeliveryBatchInstitutionalRecipientFormTests(
    InstitutionalRecipientFormTestBase
):
    @patch("apps.deliveries.forms.resolve_institutional_identity")
    def test_rrhh_recipient_snapshot_overwrites_posted_values(self, resolve):
        recipient = self.create_local_user(
            "batch-recipient-rrhh",
            "persona.rrhh@example.test",
            id_personal=1234,
        )
        resolve.return_value = rrhh_recipient_identity()
        form = DeliveryBatchForm(
            data=self.delivery_batch_data(
                recipient_id_personal="1234",
                recipient_email="persona.rrhh@example.test",
            )
        )

        self.assertTrue(form.is_valid(), form.errors)
        resolve.assert_called_once_with(
            id_personal=1234,
            email="persona.rrhh@example.test",
        )
        self.assertEqual(form.cleaned_data["recipient"], recipient)
        self.assertEqual(form.cleaned_data["recipient_name"], "Persona RRHH")
        self.assertEqual(
            form.cleaned_data["recipient_employee_number"],
            "LEG-1234",
        )
        self.assertEqual(form.cleaned_data["recipient_position"], "Cargo RRHH")
        self.assertEqual(form.cleaned_data["recipient_source"], "RRHH")
        self.assertEqual(
            form.cleaned_data["recipient_email"],
            "persona.rrhh@example.test",
        )
        self.assertEqual(form.cleaned_data["recipient_id_personal"], 1234)

    @patch("apps.deliveries.forms.resolve_institutional_identity")
    def test_ad_recipient_without_local_user_is_accepted(self, resolve):
        resolve.return_value = ad_recipient_identity()
        form = DeliveryBatchForm(
            data=self.delivery_batch_data(
                recipient_email="persona.ad@example.test",
            )
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data["recipient"])
        self.assertEqual(form.cleaned_data["recipient_name"], "Persona AD")
        self.assertEqual(form.cleaned_data["recipient_source"], "ACTIVE_DIRECTORY")
        self.assertEqual(
            form.cleaned_data["recipient_email"],
            "persona.ad@example.test",
        )
        self.assertIsNone(form.cleaned_data["recipient_id_personal"])
        self.assertEqual(form.cleaned_data["recipient_area"], "")
        self.assertEqual(form.cleaned_data["recipient_unit"], "")
        self.assertEqual(form.cleaned_data["recipient_section"], "")
        resolve.assert_called_once_with(
            id_personal=None,
            email="persona.ad@example.test",
        )

    @patch("apps.deliveries.forms.resolve_institutional_identity")
    def test_ad_recipient_links_local_user_by_email(self, resolve):
        recipient = self.create_local_user(
            "batch-recipient-email",
            "persona.ad@example.test",
        )
        resolve.return_value = ad_recipient_identity()
        form = DeliveryBatchForm(
            data=self.delivery_batch_data(
                recipient_email="persona.ad@example.test",
            )
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["recipient"], recipient)

    @patch("apps.deliveries.forms.resolve_institutional_identity")
    def test_missing_institutional_recipient_adds_field_error(self, resolve):
        form = DeliveryBatchForm(data=self.delivery_batch_data())

        self.assertFalse(form.is_valid())
        self.assertIn(
            "Debe seleccionar el funcionario receptor.",
            form.errors["institutional_recipient"],
        )
        resolve.assert_not_called()

    @patch("apps.deliveries.forms.resolve_institutional_identity", return_value=None)
    def test_unresolved_institutional_recipient_adds_field_error(self, resolve):
        form = DeliveryBatchForm(
            data=self.delivery_batch_data(
                recipient_email="missing@example.test",
            )
        )

        self.assertFalse(form.is_valid())
        self.assertIn(
            "No fue posible validar el receptor institucional seleccionado.",
            form.errors["institutional_recipient"],
        )
        resolve.assert_called_once()

    @patch("apps.deliveries.forms.resolve_institutional_identity")
    def test_directory_error_adds_friendly_field_error(self, resolve):
        resolve.side_effect = InstitutionalIdentityError("mock failure")
        form = DeliveryBatchForm(
            data=self.delivery_batch_data(
                recipient_email="person@example.test",
            )
        )

        self.assertFalse(form.is_valid())
        self.assertIn(
            "No fue posible consultar el Directorio Institucional. "
            "Intente nuevamente.",
            form.errors["institutional_recipient"],
        )

    @patch("apps.deliveries.forms.resolve_institutional_identity")
    @patch("apps.deliveries.forms.resolve_identity_for_user")
    def test_delivery_responsible_rrhh_identity_overwrites_manual_values(
        self,
        resolve_responsible,
        resolve_recipient,
    ):
        resolve_responsible.return_value = rrhh_recipient_identity(
            id_personal=5678,
            employee_number="1173",
            name="Ariel Ferreira",
            email="aferreira@petropar.gov.py",
            position="Jefe Interino",
        )
        resolve_recipient.return_value = rrhh_recipient_identity()
        form = DeliveryBatchForm(
            data=self.delivery_batch_data(
                recipient_id_personal="1234",
                recipient_email="persona.rrhh@example.test",
                origin_employee_number="FALSO",
                origin_position="Cargo falso",
            )
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["origin_employee_number"], "1173")
        self.assertEqual(form.cleaned_data["origin_position"], "Jefe Interino")
        resolve_responsible.assert_called_once_with(self.responsible)
        resolve_recipient.assert_called_once_with(
            id_personal=1234,
            email="persona.rrhh@example.test",
        )

    @patch("apps.deliveries.forms.resolve_institutional_identity")
    @patch("apps.deliveries.forms.resolve_identity_for_user")
    def test_ad_responsible_without_title_or_employee_number_keeps_manual_values(
        self,
        resolve_responsible,
        resolve_recipient,
    ):
        resolve_responsible.return_value = ad_recipient_identity()
        resolve_recipient.return_value = rrhh_recipient_identity()
        form = DeliveryBatchForm(
            data=self.delivery_batch_data(
                recipient_id_personal="1234",
                recipient_email="persona.rrhh@example.test",
                origin_employee_number="MANUAL-001",
                origin_position="Cargo manual",
            )
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["origin_employee_number"],
            "MANUAL-001",
        )
        self.assertEqual(form.cleaned_data["origin_position"], "Cargo manual")
        resolve_responsible.assert_called_once_with(self.responsible)

    @patch("apps.deliveries.forms.resolve_institutional_identity")
    @patch("apps.deliveries.forms.resolve_identity_for_user")
    def test_delivery_responsible_directory_error_keeps_manual_values(
        self,
        resolve_responsible,
        resolve_recipient,
    ):
        resolve_responsible.side_effect = InstitutionalIdentityError("mock failure")
        resolve_recipient.return_value = rrhh_recipient_identity()
        form = DeliveryBatchForm(
            data=self.delivery_batch_data(
                recipient_id_personal="1234",
                recipient_email="persona.rrhh@example.test",
                origin_employee_number="MANUAL-002",
                origin_position="Cargo manual de respaldo",
            )
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["origin_employee_number"],
            "MANUAL-002",
        )
        self.assertEqual(
            form.cleaned_data["origin_position"],
            "Cargo manual de respaldo",
        )
        resolve_responsible.assert_called_once_with(self.responsible)


class AssetCustodyMovementInstitutionalRecipientFormTests(
    InstitutionalRecipientFormTestBase
):
    @patch("apps.deliveries.forms.resolve_institutional_identity")
    def test_delivery_accepts_ad_identity_without_local_user(self, resolve):
        resolve.return_value = ad_recipient_identity()
        form = AssetCustodyMovementForm(
            data=self.movement_data(
                AssetCustodyMovement.MovementType.DELIVERY,
                recipient_email="persona.ad@example.test",
            )
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data["recipient"])
        self.assertEqual(form.cleaned_data["recipient_name"], "Persona AD")
        self.assertEqual(form.cleaned_data["recipient_source"], "ACTIVE_DIRECTORY")
        self.assertEqual(form.cleaned_data["recipient_email"], "persona.ad@example.test")
        self.assertIsNone(form.cleaned_data["recipient_id_personal"])
        self.assertEqual(form.cleaned_data["recipient_employee_number"], "")
        self.assertEqual(form.cleaned_data["recipient_position"], "")
        self.assertEqual(form.cleaned_data["recipient_area"], "")
        self.assertEqual(form.cleaned_data["recipient_unit"], "")
        self.assertEqual(form.cleaned_data["recipient_section"], "")
        resolve.assert_called_once_with(
            id_personal=None,
            email="persona.ad@example.test",
        )

    @patch("apps.deliveries.forms.resolve_institutional_identity")
    def test_delivery_without_institutional_recipient_adds_field_error(self, resolve):
        form = AssetCustodyMovementForm(
            data=self.movement_data(AssetCustodyMovement.MovementType.DELIVERY)
        )

        self.assertFalse(form.is_valid())
        self.assertIn(
            "Debe seleccionar el receptor institucional.",
            form.errors["institutional_recipient"],
        )
        resolve.assert_not_called()

    @patch("apps.deliveries.forms.resolve_institutional_identity")
    def test_reassignment_same_person_by_id_personal_is_rejected(self, resolve):
        previous_custodian = self.create_local_user(
            "movement-previous-id",
            "previous-id@example.test",
            id_personal=1234,
        )
        resolve.return_value = rrhh_recipient_identity(
            email="selected@example.test",
        )
        form = AssetCustodyMovementForm(
            data=self.movement_data(
                AssetCustodyMovement.MovementType.REASSIGNMENT,
                previous_custodian=str(previous_custodian.pk),
                recipient_id_personal="1234",
                recipient_email="selected@example.test",
            )
        )

        self.assertFalse(form.is_valid())
        self.assertIn(
            "En una reasignación, el custodio anterior y el nuevo receptor deben ser distintos.",
            form.errors["institutional_recipient"],
        )
        resolve.assert_called_once_with(
            id_personal=1234,
            email="selected@example.test",
        )

    @patch("apps.deliveries.forms.resolve_institutional_identity")
    def test_reassignment_same_person_by_email_is_rejected(self, resolve):
        previous_custodian = self.create_local_user(
            "movement-previous-email",
            "PERSONA.AD@EXAMPLE.TEST",
        )
        resolve.return_value = ad_recipient_identity()
        form = AssetCustodyMovementForm(
            data=self.movement_data(
                AssetCustodyMovement.MovementType.REASSIGNMENT,
                previous_custodian=str(previous_custodian.pk),
                recipient_email="persona.ad@example.test",
            )
        )

        self.assertFalse(form.is_valid())
        self.assertIn(
            "En una reasignación, el custodio anterior y el nuevo receptor deben ser distintos.",
            form.errors["institutional_recipient"],
        )
        resolve.assert_called_once_with(
            id_personal=None,
            email="persona.ad@example.test",
        )

    @patch("apps.deliveries.forms.resolve_institutional_identity")
    def test_reassignment_to_different_institutional_person_is_allowed(self, resolve):
        previous_custodian = self.create_local_user(
            "movement-previous-different",
            "previous-different@example.test",
            id_personal=4567,
        )
        resolve.return_value = ad_recipient_identity()
        form = AssetCustodyMovementForm(
            data=self.movement_data(
                AssetCustodyMovement.MovementType.REASSIGNMENT,
                previous_custodian=str(previous_custodian.pk),
                recipient_email="persona.ad@example.test",
            )
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertNotIn("institutional_recipient", form.errors)
        self.assertIsNone(form.cleaned_data["recipient"])


class AssetCustodyUpdateTests(TestCase):
    def setUp(self):
        self.custodian = User.objects.create_user(
            username="custody-update-custodian",
            email="custody-update-custodian@example.com",
            password="test-password",
            role=User.Role.CLIENT,
        )
        self.recipient = User.objects.create_user(
            username="custody-update-recipient",
            email="custody-update-recipient@example.com",
            password="test-password",
            role=User.Role.CLIENT,
        )
        self.asset = Asset.objects.create(
            internal_code="CUSTODY-UPDATE-ASSET",
            assigned_user=self.custodian,
            condition=Asset.Condition.NEW,
            operational_status=Asset.OperationalStatus.OPERATIONAL,
        )

    def test_delivered_return_moves_asset_to_used_custody(self):
        movement = AssetCustodyMovement.objects.create(
            asset=self.asset,
            movement_type=AssetCustodyMovement.MovementType.RETURN,
            status=AssetCustodyMovement.MovementStatus.DELIVERED,
            delivery_responsible=self.custodian,
            created_by=self.custodian,
        )

        update_asset_custody(movement)

        self.asset.refresh_from_db()
        self.assertIsNone(self.asset.assigned_user)
        self.assertEqual(self.asset.condition, Asset.Condition.RECOVERED)
        self.assertEqual(
            self.asset.operational_status,
            Asset.OperationalStatus.OBSERVATION,
        )

    def test_return_not_delivered_does_not_change_asset(self):
        movement = AssetCustodyMovement.objects.create(
            asset=self.asset,
            movement_type=AssetCustodyMovement.MovementType.RETURN,
            status=AssetCustodyMovement.MovementStatus.PENDING_SIGNATURE,
            delivery_responsible=self.custodian,
            created_by=self.custodian,
        )

        update_asset_custody(movement)

        self.asset.refresh_from_db()
        self.assertEqual(self.asset.assigned_user, self.custodian)
        self.assertEqual(self.asset.condition, Asset.Condition.NEW)
        self.assertEqual(
            self.asset.operational_status,
            Asset.OperationalStatus.OPERATIONAL,
        )

    def test_delivered_delivery_assigns_recipient_without_changing_condition(self):
        movement = AssetCustodyMovement.objects.create(
            asset=self.asset,
            movement_type=AssetCustodyMovement.MovementType.DELIVERY,
            status=AssetCustodyMovement.MovementStatus.DELIVERED,
            recipient=self.recipient,
            delivery_responsible=self.custodian,
            created_by=self.custodian,
        )

        update_asset_custody(movement)

        self.asset.refresh_from_db()
        self.assertEqual(self.asset.assigned_user, self.recipient)
        self.assertEqual(self.asset.condition, Asset.Condition.NEW)
        self.assertEqual(
            self.asset.operational_status,
            Asset.OperationalStatus.OPERATIONAL,
        )


class DeliveryAuthorizationTests(TestCase):
    def setUp(self):
        self.client_user = User.objects.create_user(
            username="delivery-client",
            email="delivery-client@example.com",
            password="test-password",
            role=User.Role.CLIENT,
        )
        self.client.force_login(self.client_user)
        self.unknown_movement_id = uuid.uuid4()

    def test_state_change_rejects_unauthorized_get(self):
        response = self.client.get(
            reverse(
                "deliveries:marcar_preparado",
                args=[self.unknown_movement_id],
            )
        )
        self.assertEqual(response.status_code, 403)

    def test_client_cannot_change_delivery_state(self):
        response = self.client.post(
            reverse(
                "deliveries:marcar_preparado",
                args=[self.unknown_movement_id],
            )
        )
        self.assertEqual(response.status_code, 403)


class DeliveryDocumentTests(TestCase):
    def setUp(self):
        self.storage_override = override_settings(
            STORAGES={
                "default": {
                    "BACKEND": (
                        "django.core.files.storage.InMemoryStorage"
                    ),
                },
                "staticfiles": {
                    "BACKEND": (
                        "django.contrib.staticfiles.storage.StaticFilesStorage"
                    ),
                },
            }
        )
        self.storage_override.enable()
        self.addCleanup(self.storage_override.disable)

        self.manager = User.objects.create_user(
            username="delivery-manager",
            email="delivery-manager@example.com",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        grant_all_delivery_permissions(self.manager)
        self.asset = Asset.objects.create(internal_code="TEST-ASSET-001")
        self.movement = AssetCustodyMovement.objects.create(
            asset=self.asset,
            status=AssetCustodyMovement.MovementStatus.PENDING_SIGNATURE,
            delivery_responsible=self.manager,
            created_by=self.manager,
        )
        self.client.force_login(self.manager)

    def test_detail_contains_document_form(self):
        response = self.client.get(
            reverse(
                "deliveries:custody_movement_detail",
                args=[self.movement.pk],
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="document_type"')
        self.assertContains(response, 'name="file"')

    def test_manager_can_upload_delivery_document(self):
        uploaded_file = SimpleUploadedFile(
            "delivery-form.pdf",
            b"%PDF-1.4 test document",
            content_type="application/pdf",
        )
        response = self.client.post(
            reverse(
                "deliveries:upload_delivery_document",
                args=[self.movement.pk],
            ),
            {
                "document_type": DeliveryDocument.DocumentType.DELIVERY_FORM,
                "file": uploaded_file,
                "observations": "Documento de prueba",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            DeliveryDocument.objects.filter(
                movement=self.movement,
                document_type=DeliveryDocument.DocumentType.DELIVERY_FORM,
            ).exists()
        )

    def test_prepared_movement_exposes_document_upload(self):
        self.movement.status = AssetCustodyMovement.MovementStatus.PREPARED
        self.movement.save(update_fields=["status"])

        response = self.client.get(
            reverse(
                "deliveries:custody_movement_detail",
                args=[self.movement.pk],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Adjuntar documento al equipo")
        self.assertTrue(response.context["can_upload_documents"])

    def test_delivery_with_missing_document_returns_to_detail_with_message(self):
        DeliveryDocument.objects.create(
            movement=self.movement,
            document_type=DeliveryDocument.DocumentType.DELIVERY_FORM,
            file=SimpleUploadedFile(
                "delivery-form.pdf",
                b"%PDF-1.4 test document",
                content_type="application/pdf",
            ),
            uploaded_by=self.manager,
        )

        response = self.client.post(
            reverse(
                "deliveries:mark_movement_delivered",
                args=[self.movement.pk],
            ),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        response_messages = [
            str(message)
            for message in get_messages(response.wsgi_request)
        ]
        self.assertTrue(
            any("Falta adjuntar" in message for message in response_messages)
        )
        self.assertTrue(
            any(
                "Hoja patrimonial firmada" in message
                for message in response_messages
            )
        )
        self.movement.refresh_from_db()
        self.assertEqual(
            self.movement.status,
            AssetCustodyMovement.MovementStatus.PENDING_SIGNATURE,
        )

    def test_delivered_filter_lists_completed_movements(self):
        self.movement.status = AssetCustodyMovement.MovementStatus.DELIVERED
        self.movement.save(update_fields=["status"])

        response = self.client.get(
            reverse("deliveries:custody_movement_list"),
            {"estado": "entregados"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.movement.movement_number)
        self.assertEqual(response.context["status_filter"], "entregados")


class GroupedDeliveryWorkflowTests(TestCase):
    def setUp(self):
        self.storage_override = override_settings(
            STORAGES={
                "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
                "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
            }
        )
        self.storage_override.enable()
        self.addCleanup(self.storage_override.disable)
        self.manager = User.objects.create_user(
            username="batch-manager",
            email="batch-manager@example.com",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        grant_all_delivery_permissions(self.manager)
        self.recipient = User.objects.create_user(
            username="batch-recipient",
            email="batch-recipient@example.com",
            password="test-password",
            role=User.Role.CLIENT,
        )
        self.branch = Branch.objects.create(
            code="HQ-TEST",
            name="Sede de prueba",
            branch_type=Branch.BranchType.HEADQUARTERS,
        )
        self.batch = AcquisitionBatch.objects.create(
            code="LOT-TEST-001",
            date=date.today(),
            status=AcquisitionBatch.Status.VALIDATED,
            expected_quantity=1,
            received_by=self.manager,
        )
        AcquisitionBatchDocument.objects.create(
            batch=self.batch,
            document_type=AcquisitionBatchDocument.DocumentType.RECEIPT_REPORT,
            file=SimpleUploadedFile("receipt.pdf", b"%PDF-1.4 receipt"),
            uploaded_by=self.manager,
            verified=True,
        )
        self.asset = Asset.objects.create(
            internal_code="BATCH-ASSET-001",
            brand="HP",
            model="ProDesk",
            patrimonial_code="PAT-001",
            serial_number="SERIAL-BATCH-001",
            acquisition_batch=self.batch,
        )
        self.client.force_login(self.manager)

    @patch("apps.deliveries.forms.resolve_institutional_identity")
    @patch(
        "apps.deliveries.forms.resolve_identity_for_user",
        return_value=None,
    )
    def test_creating_grouped_delivery_creates_traceable_movements(
        self,
        resolve_responsible,
        resolve_recipient,
    ):
        resolved_name = self.recipient.get_full_name() or self.recipient.username
        resolve_recipient.return_value = {
            "source": "LOCAL",
            "id_personal": getattr(self.recipient, "id_personal", None),
            "employee_number": "",
            "name": resolved_name,
            "first_name": self.recipient.first_name,
            "last_name": self.recipient.last_name,
            "email": self.recipient.email,
            "phone": "",
            "location": "",
            "position": "",
            "employment_type": "",
            "status": "Activo",
            "username": self.recipient.username,
            "is_active": True,
        }
        response = self.client.post(
            reverse("deliveries:delivery_batch_create"),
            {
                "assets": [str(self.asset.pk)],
                "recipient_email": self.recipient.email,
                "delivery_responsible": str(self.manager.pk),
                "authorizing_director": str(self.manager.pk),
                "department": "Administración",
                "destination_branch": str(self.branch.pk),
                "location": "Edificio Central",
                "delivery_date": "2026-08-01T10:00",
            },
        )
        self.assertEqual(response.status_code, 302)
        delivery_batch = DeliveryBatch.objects.get()
        movement = delivery_batch.movements.get()
        self.assertEqual(movement.asset, self.asset)
        self.assertEqual(movement.recipient, self.recipient)
        self.assertEqual(movement.recipient_name, resolved_name)
        self.assertEqual(movement.recipient_email, self.recipient.email)
        self.assertEqual(movement.recipient_source, "LOCAL")
        self.assertEqual(movement.department, "Administración")
        resolve_recipient.assert_called_once_with(
            id_personal=None,
            email=self.recipient.email,
        )
        resolve_responsible.assert_called_once_with(self.manager)
        detail_response = self.client.get(
            reverse("deliveries:delivery_batch_detail", args=[delivery_batch.pk])
        )
        self.assertEqual(detail_response.status_code, 200)

    def test_grouping_staged_movements_creates_draft_and_redirects_to_grouped(self):
        movement = AssetCustodyMovement.objects.create(
            asset=self.asset,
            delivery_responsible=self.manager,
            status=AssetCustodyMovement.MovementStatus.IN_DELIVERY_PROCESS,
            created_by=self.manager,
        )
        response = self.client.post(
            reverse("deliveries:group_selected_custody_movements"),
            {"selected_ids": [str(self.asset.pk)]},
        )
        self.assertRedirects(
            response,
            reverse("deliveries:custody_movement_list") + "?estado=agrupados",
            fetch_redirect_response=False,
        )
        movement.refresh_from_db()
        self.assertIsNotNone(movement.delivery_batch_id)
        self.assertEqual(movement.delivery_batch.status, DeliveryBatch.BatchStatus.DRAFT)

    def test_completing_grouped_delivery_updates_inventory_custodian(self):
        delivery_batch = DeliveryBatch.objects.create(
            status=DeliveryBatch.BatchStatus.PENDING_SIGNATURE,
            recipient=self.recipient,
            delivery_responsible=self.manager,
            department="Administración",
            destination_branch=self.branch,
            location="Edificio Central",
            created_by=self.manager,
        )
        AssetCustodyMovement.objects.create(
            delivery_batch=delivery_batch,
            asset=self.asset,
            recipient=self.recipient,
            delivery_responsible=self.manager,
            department="Administración",
            destination_branch=self.branch,
            location="Edificio Central",
            status=AssetCustodyMovement.MovementStatus.PENDING_SIGNATURE,
            created_by=self.manager,
        )
        for document_type in (
            DeliveryBatchDocument.DocumentType.INTERNAL_DELIVERY,
            DeliveryBatchDocument.DocumentType.PATRIMONIAL_MOVEMENT,
        ):
            DeliveryBatchDocument.objects.create(
                delivery_batch=delivery_batch,
                document_type=document_type,
                file=SimpleUploadedFile(f"{document_type}.pdf", b"%PDF-1.4 signed"),
                signatures_verified=True,
                uploaded_by=self.manager,
            )

        response = self.client.post(
            reverse("deliveries:delivery_batch_complete", args=[delivery_batch.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.asset.refresh_from_db()
        delivery_batch.refresh_from_db()
        self.assertEqual(self.asset.assigned_user, self.recipient)
        self.assertEqual(self.asset.department, "Administración")
        self.assertEqual(self.asset.branch, self.branch)
        self.assertEqual(delivery_batch.status, DeliveryBatch.BatchStatus.DELIVERED)

# Create your tests here.


class ConfigurableDeliveryPermissionTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code="PERM-HQ", name="Sede permisos")
        self.recipient = User.objects.create_user(
            username="custody-recipient",
            email="custody-recipient@example.com",
            password="test-password",
            role=User.Role.CLIENT,
        )
        self.owner = User.objects.create_user(
            username="custody-owner",
            email="custody-owner@example.com",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.asset = Asset.objects.create(internal_code="PERM-ASSET-001")
        self.movement = AssetCustodyMovement.objects.create(
            asset=self.asset,
            recipient=self.recipient,
            delivery_responsible=self.owner,
            destination_branch=self.branch,
            department="Tecnología",
            location="Mesa técnica",
            created_by=self.owner,
        )
        self.batch = DeliveryBatch.objects.create(
            recipient=self.recipient,
            delivery_responsible=self.owner,
            destination_branch=self.branch,
            department="Tecnología",
            location="Mesa técnica",
            created_by=self.owner,
        )

    def create_user(self, name, role):
        return User.objects.create_user(
            username=name,
            email=f"{name}@example.com",
            password="test-password",
            role=role,
        )

    def read_urls(self):
        return (
            reverse("deliveries:custody_movement_list"),
            reverse("deliveries:custody_movement_detail", args=[self.movement.pk]),
            reverse("deliveries:delivery_batch_list"),
            reverse("deliveries:delivery_batch_detail", args=[self.batch.pk]),
        )

    def test_client_without_permissions_cannot_access_global_custody(self):
        self.client.force_login(self.recipient)
        for url in self.read_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_authenticated_role_without_permissions_has_no_implicit_access(self):
        user = self.create_user("custody-no-perms", User.Role.ADMIN)
        self.client.force_login(user)
        for url in self.read_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_auditor_with_view_permissions_is_read_only(self):
        auditor = self.create_user("custody-auditor", User.Role.AUDITOR)
        grant_delivery_permissions(
            auditor,
            "view_assetcustodymovement",
            "view_deliverybatch",
            "view_deliverydocument",
            "view_deliverybatchdocument",
        )
        self.client.force_login(auditor)

        for url in self.read_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

        blocked_requests = (
            ("get", reverse("deliveries:custody_movement_create")),
            ("get", reverse("deliveries:custody_movement_update", args=[self.movement.pk])),
            ("post", reverse("deliveries:marcar_preparado", args=[self.movement.pk])),
            ("post", reverse("deliveries:revert_movement", args=[self.movement.pk])),
        )
        for method, url in blocked_requests:
            with self.subTest(method=method, url=url):
                self.assertEqual(getattr(self.client, method)(url).status_code, 403)

    def test_technician_with_operational_permissions_can_work_without_delete(self):
        technician = self.create_user("custody-technician", User.Role.TECHNICIAN)
        grant_delivery_permissions(
            technician,
            "view_assetcustodymovement",
            "add_assetcustodymovement",
            "change_assetcustodymovement",
            "view_deliverybatch",
            "add_deliverybatch",
            "change_deliverybatch",
            "view_deliverydocument",
            "add_deliverydocument",
            "change_deliverydocument",
            "view_deliverybatchdocument",
            "add_deliverybatchdocument",
            "change_deliverybatchdocument",
        )
        document = DeliveryDocument.objects.create(
            movement=self.movement,
            document_type=DeliveryDocument.DocumentType.OTHER,
            file="deliveries/audit_documents/note.pdf",
            uploaded_by=self.owner,
        )
        self.client.force_login(technician)

        self.assertEqual(self.client.get(reverse("deliveries:custody_movement_list")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("deliveries:custody_movement_detail", args=[self.movement.pk])).status_code,
            200,
        )
        self.assertEqual(self.client.get(reverse("deliveries:custody_movement_create")).status_code, 200)
        self.assertEqual(
            self.client.post(reverse("deliveries:marcar_preparado", args=[self.movement.pk])).status_code,
            302,
        )
        self.movement.refresh_from_db()
        self.assertEqual(self.movement.status, AssetCustodyMovement.MovementStatus.PREPARED)
        self.assertEqual(
            self.client.post(
                reverse("deliveries:delete_delivery_document", args=[self.movement.pk, document.pk])
            ).status_code,
            403,
        )
        self.assertTrue(DeliveryDocument.objects.filter(pk=document.pk).exists())

    def test_admin_and_supervisor_with_full_permissions_keep_operational_access(self):
        for role in (User.Role.ADMIN, User.Role.SUPERVISOR):
            with self.subTest(role=role):
                user = self.create_user(f"custody-full-{role.lower()}", role)
                grant_all_delivery_permissions(user)
                self.client.force_login(user)
                self.assertEqual(
                    self.client.get(reverse("deliveries:custody_movement_list")).status_code,
                    200,
                )
                self.assertEqual(
                    self.client.get(
                        reverse("deliveries:custody_movement_update", args=[self.movement.pk])
                    ).status_code,
                    200,
                )
