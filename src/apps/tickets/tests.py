from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.activity.models import ActivityLog
from apps.core.models import Department

from .models import (
    AccessIdentityDocument,
    AuthorizationDocument,
    GeneratedAuthorizationForm,
    SystemAccessRequest,
    Ticket,
    TicketComment,
)


class TicketAuthorizationTests(TestCase):
    def setUp(self):
        self.systems_department = Department.objects.create(
            code="SYSTEMS",
            name="Sistemas",
        )
        self.support_department = Department.objects.create(
            code="SUPPORT",
            name="Soporte DTI",
        )
        self.owner = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="test-password",
            role=User.Role.CLIENT,
        )
        self.other_client = User.objects.create_user(
            username="other",
            email="other@example.com",
            password="test-password",
            role=User.Role.CLIENT,
        )
        self.manager = User.objects.create_user(
            username="manager",
            email="manager@example.com",
            password="test-password",
            role=User.Role.SUPERVISOR,
            department=self.systems_department,
        )
        self.support_manager = User.objects.create_user(
            username="support-manager",
            email="support-manager@example.com",
            password="test-password",
            role=User.Role.ADMIN,
            department=self.support_department,
        )
        self.support_technician = User.objects.create_user(
            username="support-technician",
            email="support-technician@example.com",
            password="test-password",
            role=User.Role.TECHNICIAN,
            department=self.support_department,
        )
        self.technician = User.objects.create_user(
            username="technician",
            email="technician@example.com",
            password="test-password",
            role=User.Role.TECHNICIAN,
            department=self.systems_department,
        )
        self.ticket = Ticket.objects.create(
            title="Impresora sin conexion",
            description="No responde en red.",
            requester=self.owner,
            department=self.systems_department,
        )

    def test_other_client_cannot_view_ticket(self):
        self.client.force_login(self.other_client)
        response = self.client.get(
            reverse("tickets:ticket_detail", args=[self.ticket.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_other_client_cannot_update_ticket(self):
        self.client.force_login(self.other_client)
        response = self.client.get(
            reverse("tickets:ticket_update", args=[self.ticket.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_owner_cannot_delete_ticket(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("tickets:ticket_delete", args=[self.ticket.pk])
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Ticket.objects.filter(pk=self.ticket.pk).exists())

    def test_manager_can_delete_ticket(self):
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("tickets:ticket_delete", args=[self.ticket.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Ticket.objects.filter(pk=self.ticket.pk).exists())

    def test_support_manager_cannot_view_systems_ticket(self):
        self.client.force_login(self.support_manager)
        list_response = self.client.get(reverse("tickets:ticket_list"))
        self.assertEqual(list_response.status_code, 200)
        self.assertNotContains(list_response, self.ticket.title)

        detail_response = self.client.get(
            reverse("tickets:ticket_detail", args=[self.ticket.pk])
        )
        self.assertEqual(detail_response.status_code, 403)

    def test_support_manager_cannot_delete_systems_ticket(self):
        self.client.force_login(self.support_manager)
        response = self.client.post(
            reverse("tickets:ticket_delete", args=[self.ticket.pk])
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Ticket.objects.filter(pk=self.ticket.pk).exists())

    def test_activity_history_contains_conversation_message(self):
        TicketComment.objects.create(
            ticket=self.ticket,
            author=self.owner,
            message="Necesito asistencia con este inconveniente.",
        )
        ActivityLog.objects.create(
            user=self.owner,
            action=ActivityLog.ACTION_COMMENT,
            module="Tickets",
            description=(
                f"Se agrego un comentario al ticket {self.ticket.ticket_number}."
            ),
            object_type="Ticket",
            object_id=str(self.ticket.pk),
        )

        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("tickets:ticket_detail", args=[self.ticket.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Necesito asistencia con este inconveniente.",
        )
        self.assertNotContains(response, "Se agrego un comentario al ticket")

    def test_conversation_status_changes_when_message_is_added(self):
        self.client.force_login(self.owner)
        status_url = reverse(
            "tickets:ticket_conversation_status",
            args=[self.ticket.pk],
        )
        initial_revision = self.client.get(status_url).json()["revision"]

        TicketComment.objects.create(
            ticket=self.ticket,
            author=self.owner,
            message="Mensaje nuevo para sincronización.",
        )

        updated_response = self.client.get(status_url)
        self.assertEqual(updated_response.status_code, 200)
        self.assertNotEqual(
            updated_response.json()["revision"],
            initial_revision,
        )

    def test_other_client_cannot_check_conversation_status(self):
        self.client.force_login(self.other_client)
        response = self.client.get(
            reverse(
                "tickets:ticket_conversation_status",
                args=[self.ticket.pk],
            )
        )

        self.assertEqual(response.status_code, 403)

    def test_technician_is_auto_assigned_when_replying(self):
        self.client.force_login(self.technician)
        response = self.client.post(
            reverse("tickets:ticket_detail", args=[self.ticket.pk]),
            {
                "form_type": "comment",
                "message": "Estoy revisando el inconveniente.",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assigned_to, self.technician)
        self.assertEqual(self.ticket.status, Ticket.Status.IN_PROGRESS)
        self.assertTrue(
            TicketComment.objects.filter(
                ticket=self.ticket,
                author=self.technician,
                message="Estoy revisando el inconveniente.",
                is_system=False,
            ).exists()
        )

    def test_ajax_comment_returns_explicit_success_response(self):
        self.ticket.assigned_to = self.technician
        self.ticket.save()
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("tickets:ticket_detail", args=[self.ticket.pk]),
            {
                "form_type": "comment",
                "message": "Mensaje enviado mediante AJAX.",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertIn("revision", response.json())
        self.assertTrue(
            self.ticket.comments.filter(
                message="Mensaje enviado mediante AJAX.",
            ).exists()
        )

    @override_settings(
        STORAGES={
            "default": {
                "BACKEND": "django.core.files.storage.InMemoryStorage",
            },
            "staticfiles": {
                "BACKEND": (
                    "django.contrib.staticfiles.storage.StaticFilesStorage"
                ),
            },
        }
    )
    def test_comment_can_include_mobile_attachment(self):
        self.ticket.assigned_to = self.technician
        self.ticket.save()
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("tickets:ticket_detail", args=[self.ticket.pk]),
            {
                "form_type": "comment",
                "message": "",
                "attachment": SimpleUploadedFile(
                    "image.jpg",
                    b"\xff\xd8\xff\xe0test-image-content",
                    content_type="image/jpeg",
                ),
            },
        )

        self.assertEqual(response.status_code, 302)
        attachment = self.ticket.attachments.get()
        self.assertEqual(attachment.original_name, "image.jpg")
        self.assertEqual(attachment.uploaded_by, self.owner)
        self.assertTrue(
            self.ticket.comments.filter(
                is_system=False,
                message="Archivo adjunto.",
            ).exists()
        )
        self.assertTrue(
            self.ticket.comments.filter(
                comment_type="ATTACHMENT",
                message__contains="image.jpg",
            ).exists()
        )

    def test_client_cannot_reply_before_technician_assignment(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("tickets:ticket_detail", args=[self.ticket.pk]),
            {
                "form_type": "comment",
                "message": "Agrego mas informacion.",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            TicketComment.objects.filter(
                ticket=self.ticket,
                message="Agrego mas informacion.",
            ).exists()
        )

    def test_manual_assignment_moves_open_ticket_to_in_progress(self):
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("tickets:ticket_detail", args=[self.ticket.pk]),
            {
                "form_type": "assign",
                "assigned_to": str(self.technician.pk),
                "status": Ticket.Status.OPEN,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assigned_to, self.technician)
        self.assertEqual(self.ticket.status, Ticket.Status.IN_PROGRESS)

    def test_model_prevents_open_ticket_with_assigned_technician(self):
        self.ticket.assigned_to = self.technician
        self.ticket.status = Ticket.Status.OPEN
        self.ticket.save()

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.IN_PROGRESS)

    def test_manager_can_transfer_ticket_to_another_department(self):
        self.ticket.assigned_to = self.technician
        self.ticket.save()
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("tickets:ticket_detail", args=[self.ticket.pk]),
            {
                "form_type": "transfer",
                "destination_department": str(self.support_department.pk),
                "reason": "La incidencia corresponde a soporte de hardware.",
            },
        )

        self.assertRedirects(response, reverse("tickets:ticket_list"))
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.department, self.support_department)
        self.assertIsNone(self.ticket.assigned_to)
        self.assertEqual(self.ticket.status, Ticket.Status.OPEN)
        self.assertTrue(
            self.ticket.comments.filter(
                is_system=True,
                message__contains="La incidencia corresponde",
            ).exists()
        )
        self.assertTrue(
            ActivityLog.objects.filter(
                object_id=str(self.ticket.pk),
                description__contains="fue derivado",
            ).exists()
        )

    def test_assignment_only_offers_technicians_from_ticket_department(self):
        self.client.force_login(self.manager)
        response = self.client.get(
            reverse("tickets:ticket_detail", args=[self.ticket.pk])
        )

        choices = response.context["assign_form"].fields[
            "assigned_to"
        ].queryset
        self.assertIn(self.technician, choices)
        self.assertNotIn(self.support_technician, choices)


@override_settings(
    STORAGES={
        "default": {
            "BACKEND": "django.core.files.storage.InMemoryStorage",
        },
        "staticfiles": {
            "BACKEND": (
                "django.contrib.staticfiles.storage.StaticFilesStorage"
            ),
        },
    }
)
class UserCreationRequestWorkflowTests(TestCase):
    def setUp(self):
        self.systems_department = Department.objects.create(
            code="SYSTEMS",
            name="Sistemas",
        )
        self.support_department = Department.objects.create(
            code="SUPPORT",
            name="Soporte DTI",
        )
        self.requester = User.objects.create_user(
            username="requester",
            email="requester@example.com",
            password="test-password",
            role=User.Role.CLIENT,
        )
        self.ticket = Ticket.objects.create(
            title="Creacion de nuevo usuario",
            description="Solicitud formal de cuenta.",
            requester=self.requester,
        )
        self.access_request = SystemAccessRequest.objects.create(
            ticket=self.ticket,
            requested_system="SAP",
            operation=SystemAccessRequest.RequestOperation.USER_CREATION,
            affected_employee="Persona Solicitada",
            employee_number="1234",
            affected_document_number="4567890",
            requested_email="persona@example.com",
            employee_department="Sistemas",
            employee_position="Analista",
            justification="Ingreso a la institucion",
            authorizing_director="Director Autorizante",
            authorization_status=(
                SystemAccessRequest.AuthorizationStatus.PENDING_FORM
            ),
        )
        self.client.force_login(self.requester)

    def test_user_can_create_valid_account_request(self):
        response = self.client.post(
            reverse("tickets:ticket_create"),
            {
                "title": "Creacion de nuevo usuario",
                "description": "Alta de cuenta institucional",
                "priority": Ticket.Priority.MEDIUM,
                "category": Ticket.Category.SOFTWARE,
                "request_flow": "AUTHORIZATION",
                "request_kind": "USER_CREATION_DOCUMENTS",
                "authorization-file": SimpleUploadedFile(
                    "three-signed-forms.pdf",
                    b"%PDF signed forms",
                    content_type="application/pdf",
                ),
                "authorization-identity_file": SimpleUploadedFile(
                    "identity.pdf",
                    b"%PDF identity",
                    content_type="application/pdf",
                ),
            },
        )
        self.assertEqual(response.status_code, 302)
        created_request = SystemAccessRequest.objects.get(
            ticket__title="Creacion de nuevo usuario",
            ticket__description="Alta de cuenta institucional",
        )
        self.assertEqual(created_request.requested_email, self.requester.email)
        self.assertEqual(created_request.requested_system, "CORREO_WINDOWS")
        self.assertEqual(
            created_request.authorization_status,
            SystemAccessRequest.AuthorizationStatus.FORM_ATTACHED,
        )
        self.assertEqual(created_request.authorization_documents.count(), 1)
        self.assertEqual(created_request.identity_documents.count(), 1)

    def test_ticket_is_not_created_without_required_documents(self):
        ticket_count = Ticket.objects.count()
        response = self.client.post(
            reverse("tickets:ticket_create"),
            {
                "title": "Creacion incompleta",
                "description": "Faltan documentos",
                "priority": Ticket.Priority.MEDIUM,
                "category": Ticket.Category.SOFTWARE,
                "request_flow": "AUTHORIZATION",
                "request_kind": "USER_CREATION_DOCUMENTS",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Ticket.objects.count(), ticket_count)
        self.assertContains(response, "Debe adjuntar")

    def test_ticket_form_exposes_user_creation_shortcut(self):
        response = self.client.get(reverse("tickets:ticket_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Crear nuevo usuario corporativo")
        self.assertContains(
            response,
            "Formularios para creación de usuario para Correo y Windows",
        )
        self.assertContains(
            response,
            "https://intranet.petropar.gov.py/?page_id=3309",
        )

    def test_requester_can_generate_prefilled_pdf(self):
        response = self.client.post(
            reverse(
                "tickets:generate_authorization_form",
                args=[self.ticket.pk],
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            GeneratedAuthorizationForm.objects.filter(
                access_request=self.access_request
            ).count(),
            1,
        )

    def test_signed_form_and_identity_are_registered_together(self):
        response = self.client.post(
            reverse("tickets:ticket_detail", args=[self.ticket.pk]),
            {
                "form_type": "authorization_document",
                "file": SimpleUploadedFile(
                    "signed-form.pdf",
                    b"%PDF signed form",
                    content_type="application/pdf",
                ),
                "identity_file": SimpleUploadedFile(
                    "identity.pdf",
                    b"%PDF identity",
                    content_type="application/pdf",
                ),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            AuthorizationDocument.objects.filter(
                access_request=self.access_request,
                version=1,
            ).exists()
        )
        self.assertTrue(
            AccessIdentityDocument.objects.filter(
                access_request=self.access_request,
                version=1,
            ).exists()
        )
        self.access_request.refresh_from_db()
        self.assertEqual(
            self.access_request.authorization_status,
            SystemAccessRequest.AuthorizationStatus.FORM_ATTACHED,
        )

# Create your tests here.
