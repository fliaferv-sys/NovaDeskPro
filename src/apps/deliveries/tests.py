import uuid
from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.messages import get_messages
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Branch, User
from apps.inventory.models import Asset, AcquisitionBatch, AcquisitionBatchDocument

from .models import (
    AssetCustodyMovement,
    DeliveryBatch,
    DeliveryBatchDocument,
    DeliveryDocument,
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

    def test_state_change_rejects_get(self):
        response = self.client.get(
            reverse(
                "deliveries:marcar_preparado",
                args=[self.unknown_movement_id],
            )
        )
        self.assertEqual(response.status_code, 405)

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

    def test_creating_grouped_delivery_creates_traceable_movements(self):
        response = self.client.post(
            reverse("deliveries:delivery_batch_create"),
            {
                "assets": [str(self.asset.pk)],
                "recipient": str(self.recipient.pk),
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
        self.assertEqual(movement.department, "Administración")
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
