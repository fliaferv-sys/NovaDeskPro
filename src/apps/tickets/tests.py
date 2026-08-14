from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TechnicianWorkday, User, WorkShift
from apps.accounts.services import (
    close_expired_workdays,
    finish_technician_workday,
)
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
from .services import (
    assign_pending_tickets_for_department,
    auto_assign_ticket,
    lock_ticket_from_auto_rebalancing,
    rebalance_unworked_auto_assigned_tickets,
    release_safe_tickets_for_inactive_technician,
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

    def test_ticket_list_filters_states_and_keeps_global_counters(self):
        tickets_by_status = {Ticket.Status.OPEN: self.ticket}
        for status in [
            Ticket.Status.IN_PROGRESS,
            Ticket.Status.WAITING,
            Ticket.Status.RESOLVED,
            Ticket.Status.CLOSED,
        ]:
            tickets_by_status[status] = Ticket.objects.create(
                title=f"Ticket {status}",
                description="Prueba de filtro.",
                requester=self.owner,
                department=self.systems_department,
                status=status,
            )

        self.client.force_login(self.owner)
        list_url = reverse("tickets:ticket_list")

        active_response = self.client.get(list_url)
        self.assertEqual(active_response.context["selected_view"], "active")
        self.assertQuerySetEqual(
            active_response.context["tickets"],
            [
                tickets_by_status[Ticket.Status.WAITING],
                tickets_by_status[Ticket.Status.IN_PROGRESS],
                tickets_by_status[Ticket.Status.OPEN],
            ],
        )
        self.assertNotContains(active_response, "Ticket RESOLVED")
        self.assertNotContains(active_response, "Ticket CLOSED")

        resolved_response = self.client.get(list_url, {"view": "resolved"})
        self.assertQuerySetEqual(
            resolved_response.context["tickets"],
            [
                tickets_by_status[Ticket.Status.CLOSED],
                tickets_by_status[Ticket.Status.RESOLVED],
            ],
        )

        all_response = self.client.get(list_url, {"view": "all"})
        self.assertEqual(all_response.context["tickets"].count(), 5)

        open_response = self.client.get(
            list_url,
            {"view": "all", "status": Ticket.Status.OPEN},
        )
        self.assertQuerySetEqual(
            open_response.context["tickets"],
            [tickets_by_status[Ticket.Status.OPEN]],
        )
        self.assertEqual(
            open_response.context["selected_status"],
            Ticket.Status.OPEN,
        )

        for response in [active_response, resolved_response, all_response]:
            self.assertEqual(response.context["total_tickets"], 5)
            self.assertEqual(response.context["pending_tickets"], 3)
            self.assertEqual(response.context["resolved_tickets"], 2)

        detail_url = reverse(
            "tickets:ticket_detail",
            args=[self.ticket.pk],
        )
        self.assertContains(
            active_response,
            f'data-url="{detail_url}"',
            html=False,
        )

    def test_all_filter_does_not_expand_department_scope(self):
        support_ticket = Ticket.objects.create(
            title="Ticket de soporte ajeno",
            description="No pertenece a Sistemas.",
            requester=self.owner,
            department=self.support_department,
            status=Ticket.Status.RESOLVED,
        )
        systems_ticket = Ticket.objects.create(
            title="Ticket resuelto de Sistemas",
            description="Pertenece al departamento.",
            requester=self.owner,
            department=self.systems_department,
            status=Ticket.Status.RESOLVED,
        )
        self.client.force_login(self.manager)

        response = self.client.get(
            reverse("tickets:ticket_list"),
            {"view": "all"},
        )

        self.assertContains(response, systems_ticket.title)
        self.assertNotContains(response, support_ticket.title)

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

    def test_unassigned_ticket_is_not_auto_assigned_when_replying(self):
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
        self.assertIsNone(self.ticket.assigned_to)
        self.assertEqual(self.ticket.status, Ticket.Status.OPEN)
        self.assertFalse(
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

    def test_manual_assignment_keeps_open_ticket_open(self):
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
        self.assertEqual(self.ticket.status, Ticket.Status.OPEN)
        self.assertEqual(
            self.ticket.assignment_origin,
            Ticket.AssignmentOrigin.MANUAL,
        )

    def test_model_allows_open_ticket_with_assigned_technician(self):
        self.ticket.assigned_to = self.technician
        self.ticket.status = Ticket.Status.OPEN
        self.ticket.save()

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.OPEN)

    def test_assigned_technician_first_reply_moves_ticket_to_in_progress(self):
        self.ticket.assigned_to = self.technician
        self.ticket.assignment_origin = Ticket.AssignmentOrigin.AUTO
        self.ticket.save(update_fields=["assigned_to", "assignment_origin"])
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
        self.assertIsNotNone(self.ticket.auto_rebalance_locked_at)
        self.assertTrue(
            self.ticket.comments.filter(
                is_system=True,
                comment_type="STATUS",
            ).exists()
        )
        self.assertTrue(
            ActivityLog.objects.filter(
                object_id=str(self.ticket.pk),
                action=ActivityLog.ACTION_STATUS,
            ).exists()
        )

    def test_auto_assignment_keeps_ticket_open_and_respects_one_ticket_cap(self):
        now = timezone.now()
        shift = WorkShift.objects.create(
            name="Turno de prueba",
            start_time=(now - timedelta(hours=1)).time(),
            end_time=(now + timedelta(hours=7)).time(),
        )
        TechnicianWorkday.objects.create(
            technician=self.technician,
            date=timezone.localdate(),
            shift=shift,
            started_at=now,
            scheduled_end_at=now + timedelta(hours=7),
        )

        active_ticket = Ticket.objects.create(
            title="Ticket activo",
            description="Carga efectiva.",
            requester=self.owner,
            department=self.systems_department,
            assigned_to=self.technician,
        )

        self.assertIsNone(auto_assign_ticket(self.ticket))
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.assigned_to)
        self.assertEqual(self.ticket.status, Ticket.Status.OPEN)

        active_ticket.status = Ticket.Status.RESOLVED
        active_ticket.save(update_fields=["status"])

        self.assertEqual(auto_assign_ticket(self.ticket), self.technician)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assigned_to, self.technician)
        self.assertEqual(self.ticket.status, Ticket.Status.OPEN)
        self.assertEqual(
            self.ticket.assignment_origin,
            Ticket.AssignmentOrigin.AUTO,
        )

    def test_pending_queue_assigns_oldest_open_ticket_without_changing_status(self):
        now = timezone.now()
        shift = WorkShift.objects.create(
            name="Turno para cola",
            start_time=(now - timedelta(hours=1)).time(),
            end_time=(now + timedelta(hours=7)).time(),
        )
        TechnicianWorkday.objects.create(
            technician=self.technician,
            date=timezone.localdate(),
            shift=shift,
            started_at=now,
            scheduled_end_at=now + timedelta(hours=7),
        )
        newer_ticket = Ticket.objects.create(
            title="Ticket posterior",
            description="Debe quedar segundo.",
            requester=self.owner,
            department=self.systems_department,
        )

        assigned = assign_pending_tickets_for_department(
            self.systems_department,
            technician=self.technician,
        )

        self.ticket.refresh_from_db()
        newer_ticket.refresh_from_db()
        self.assertEqual(assigned[0][0], self.ticket)
        self.assertEqual(self.ticket.assigned_to, self.technician)
        self.assertEqual(self.ticket.status, Ticket.Status.OPEN)
        self.assertEqual(newer_ticket.status, Ticket.Status.OPEN)
        self.assertIsNone(newer_ticket.assigned_to)

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
        self.assertEqual(
            self.ticket.assignment_origin,
            Ticket.AssignmentOrigin.UNKNOWN,
        )
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


class TicketAutoRebalanceTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(
            code="REBALANCE",
            name="Rebalanceo",
        )
        self.other_department = Department.objects.create(
            code="OTHER-REBALANCE",
            name="Otro departamento",
        )
        self.requester = User.objects.create_user(
            username="rebalance-requester",
            password="test-password",
            role=User.Role.CLIENT,
        )
        self.technicians = [
            User.objects.create_user(
                username=f"rebalance-tech-{index}",
                email=f"rebalance-tech-{index}@example.com",
                password="test-password",
                role=User.Role.TECHNICIAN,
                department=self.department,
                approval_status=User.ApprovalStatus.APPROVED,
                availability_status=User.AvailabilityStatus.AVAILABLE,
            )
            for index in range(3)
        ]
        now = timezone.now()
        self.shift = WorkShift.objects.create(
            name="Turno de rebalanceo",
            start_time=(now - timedelta(hours=1)).time(),
            end_time=(now + timedelta(hours=7)).time(),
        )

    def start_workday(self, technician):
        now = timezone.now()
        return TechnicianWorkday.objects.create(
            technician=technician,
            date=timezone.localdate(),
            shift=self.shift,
            started_at=now,
            scheduled_end_at=now + timedelta(hours=7),
        )

    def create_auto_ticket(self, technician, index):
        return Ticket.objects.create(
            title=f"Ticket automático {index}",
            description="Pendiente de trabajo.",
            requester=self.requester,
            department=self.department,
            assigned_to=technician,
            assignment_origin=Ticket.AssignmentOrigin.AUTO,
        )

    def test_existing_and_unclassified_tickets_are_not_rebalanceable(self):
        ticket = Ticket.objects.create(
            title="Ticket sin procedencia",
            description="Debe quedar inmóvil.",
            requester=self.requester,
            department=self.department,
            assigned_to=self.technicians[0],
        )

        self.assertEqual(
            ticket.assignment_origin,
            Ticket.AssignmentOrigin.UNKNOWN,
        )

    def test_rebalances_three_unworked_tickets_as_technicians_arrive(self):
        donor, second, third = self.technicians
        self.start_workday(donor)
        tickets = [self.create_auto_ticket(donor, index) for index in range(3)]

        self.start_workday(second)
        first_moves = rebalance_unworked_auto_assigned_tickets(
            self.department
        )
        self.assertEqual(len(first_moves), 1)
        self.assertEqual(
            sorted(
                Ticket.objects.filter(
                    assigned_to=technician,
                    status__in=[
                        Ticket.Status.OPEN,
                        Ticket.Status.IN_PROGRESS,
                        Ticket.Status.WAITING,
                    ],
                ).count()
                for technician in [donor, second]
            ),
            [1, 2],
        )

        self.start_workday(third)
        second_moves = rebalance_unworked_auto_assigned_tickets(
            self.department
        )
        self.assertEqual(len(second_moves), 1)
        self.assertEqual(
            [
                Ticket.objects.filter(assigned_to=technician).count()
                for technician in [donor, second, third]
            ],
            [1, 1, 1],
        )
        for ticket in tickets:
            ticket.refresh_from_db()
            self.assertEqual(
                ticket.assignment_origin,
                Ticket.AssignmentOrigin.AUTO,
            )
        logs = ActivityLog.objects.filter(
            object_type="Ticket",
            action=ActivityLog.ACTION_ASSIGN,
            description__contains="redistribuido automáticamente",
        )
        self.assertEqual(logs.count(), 2)
        self.assertTrue(
            all(
                "rebalance-tech" in log.description
                for log in logs
            )
        )

    def test_locked_ticket_stays_with_original_technician(self):
        donor, second, third = self.technicians
        for technician in self.technicians:
            self.start_workday(technician)
        locked_ticket = self.create_auto_ticket(donor, 0)
        locked_ticket.auto_rebalance_locked_at = timezone.now()
        locked_ticket.save(update_fields=["auto_rebalance_locked_at"])
        self.create_auto_ticket(donor, 1)
        self.create_auto_ticket(donor, 2)

        rebalance_unworked_auto_assigned_tickets(self.department)

        locked_ticket.refresh_from_db()
        self.assertEqual(locked_ticket.assigned_to, donor)
        self.assertEqual(
            [
                Ticket.objects.filter(assigned_to=technician).count()
                for technician in [donor, second, third]
            ],
            [1, 1, 1],
        )

    def test_real_comment_prevents_moving_ticket_even_without_lock_field(self):
        donor, recipient, _ = self.technicians
        self.start_workday(donor)
        self.start_workday(recipient)
        protected = self.create_auto_ticket(donor, 0)
        TicketComment.objects.create(
            ticket=protected,
            author=donor,
            message="Trabajo realizado.",
            is_system=False,
        )
        manual = Ticket.objects.create(
            title="Asignación manual",
            description="No se mueve.",
            requester=self.requester,
            department=self.department,
            assigned_to=donor,
            assignment_origin=Ticket.AssignmentOrigin.MANUAL,
        )
        unknown = Ticket.objects.create(
            title="Asignación desconocida",
            description="No se mueve.",
            requester=self.requester,
            department=self.department,
            assigned_to=donor,
        )

        moved = rebalance_unworked_auto_assigned_tickets(self.department)

        self.assertEqual(moved, [])
        for ticket in [protected, manual, unknown]:
            ticket.refresh_from_db()
            self.assertEqual(ticket.assigned_to, donor)

    def test_lock_is_irreversible_across_future_auto_assignment(self):
        technician = self.technicians[0]
        self.start_workday(technician)
        ticket = self.create_auto_ticket(technician, 0)

        self.assertTrue(
            lock_ticket_from_auto_rebalancing(ticket, technician)
        )
        locked_at = ticket.auto_rebalance_locked_at
        ticket.assigned_to = None
        ticket.assignment_origin = Ticket.AssignmentOrigin.UNKNOWN
        ticket.save(update_fields=["assigned_to", "assignment_origin"])

        auto_assign_ticket(ticket, technician=technician)
        ticket.refresh_from_db()

        self.assertEqual(ticket.assignment_origin, Ticket.AssignmentOrigin.AUTO)
        self.assertEqual(ticket.auto_rebalance_locked_at, locked_at)

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
    def test_assigned_technician_attachment_locks_auto_rebalance(self):
        technician = self.technicians[0]
        ticket = self.create_auto_ticket(technician, 0)
        self.client.force_login(technician)

        response = self.client.post(
            reverse("tickets:ticket_detail", args=[ticket.pk]),
            {
                "form_type": "attachment",
                "file": SimpleUploadedFile(
                    "evidence.txt",
                    b"technical evidence",
                    content_type="text/plain",
                ),
            },
        )

        self.assertEqual(response.status_code, 302)
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.auto_rebalance_locked_at)

    def test_assigned_technician_status_change_locks_auto_rebalance(self):
        technician = self.technicians[0]
        ticket = self.create_auto_ticket(technician, 0)
        self.client.force_login(technician)

        response = self.client.post(
            reverse("tickets:ticket_detail", args=[ticket.pk]),
            {
                "form_type": "assign",
                "assigned_to": str(technician.pk),
                "status": Ticket.Status.WAITING,
            },
        )

        self.assertEqual(response.status_code, 302)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.WAITING)
        self.assertIsNotNone(ticket.auto_rebalance_locked_at)
        self.assertEqual(
            ticket.assignment_origin,
            Ticket.AssignmentOrigin.AUTO,
        )

    def test_changing_to_available_triggers_rebalance(self):
        donor, arriving, _ = self.technicians
        self.start_workday(donor)
        self.start_workday(arriving)
        arriving.availability_status = User.AvailabilityStatus.UNAVAILABLE
        arriving.save(update_fields=["availability_status"])
        for index in range(3):
            self.create_auto_ticket(donor, index)
        self.client.force_login(arriving)

        response = self.client.post(
            reverse("tickets:dashboard"),
            {
                "form_type": "availability",
                "availability_status": User.AvailabilityStatus.AVAILABLE,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            Ticket.objects.filter(assigned_to=arriving).count(),
            1,
        )

    def test_successful_workday_start_triggers_rebalance(self):
        donor, arriving, _ = self.technicians
        self.start_workday(donor)
        arriving.availability_status = User.AvailabilityStatus.UNAVAILABLE
        arriving.save(update_fields=["availability_status"])
        for index in range(3):
            self.create_auto_ticket(donor, index)
        self.client.force_login(arriving)

        response = self.client.post(
            reverse("tickets:dashboard"),
            {"form_type": "start_workday"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            Ticket.objects.filter(assigned_to=arriving).count(),
            1,
        )

    def test_only_open_and_in_progress_consume_capacity(self):
        technician = self.technicians[0]
        self.start_workday(technician)

        for status, occupies_capacity in [
            (Ticket.Status.OPEN, True),
            (Ticket.Status.IN_PROGRESS, True),
            (Ticket.Status.WAITING, False),
            (Ticket.Status.RESOLVED, False),
            (Ticket.Status.CLOSED, False),
        ]:
            with self.subTest(status=status):
                Ticket.objects.all().delete()
                Ticket.objects.create(
                    title=f"Carga {status}",
                    description="Prueba de capacidad.",
                    requester=self.requester,
                    department=self.department,
                    assigned_to=technician,
                    status=status,
                )
                pending = Ticket.objects.create(
                    title=f"Pendiente {status}",
                    description="Debe respetar el cupo.",
                    requester=self.requester,
                    department=self.department,
                )

                assigned = auto_assign_ticket(
                    pending,
                    technician=technician,
                )

                if occupies_capacity:
                    self.assertIsNone(assigned)
                else:
                    self.assertEqual(assigned, technician)

    def test_all_technicians_occupied_leaves_new_ticket_in_queue(self):
        for index, technician in enumerate(self.technicians):
            self.start_workday(technician)
            self.create_auto_ticket(technician, index)
        pending = Ticket.objects.create(
            title="Queda en cola",
            description="Todos tienen un ticket efectivo.",
            requester=self.requester,
            department=self.department,
        )

        self.assertIsNone(auto_assign_ticket(pending))
        pending.refresh_from_db()
        self.assertIsNone(pending.assigned_to)
        self.assertEqual(pending.status, Ticket.Status.OPEN)

    def test_manual_effective_ticket_blocks_auto_but_manual_can_exceed(self):
        technician = self.technicians[0]
        self.start_workday(technician)
        first = Ticket.objects.create(
            title="Manual uno",
            description="Ocupa capacidad automática.",
            requester=self.requester,
            department=self.department,
            assigned_to=technician,
            assignment_origin=Ticket.AssignmentOrigin.MANUAL,
        )
        pending = Ticket.objects.create(
            title="Pendiente automático",
            description="No debe asignarse.",
            requester=self.requester,
            department=self.department,
        )

        self.assertIsNone(auto_assign_ticket(pending, technician=technician))

        manager = User.objects.create_user(
            username="rebalance-manager",
            email="rebalance-manager@example.com",
            password="test-password",
            role=User.Role.SUPERVISOR,
            department=self.department,
        )
        self.client.force_login(manager)
        response = self.client.post(
            reverse("tickets:ticket_detail", args=[pending.pk]),
            {
                "form_type": "assign",
                "assigned_to": str(technician.pk),
                "status": Ticket.Status.OPEN,
            },
        )

        self.assertEqual(response.status_code, 302)
        pending.refresh_from_db()
        self.assertEqual(pending.assigned_to, technician)
        self.assertEqual(
            pending.assignment_origin,
            Ticket.AssignmentOrigin.MANUAL,
        )
        self.assertEqual(
            Ticket.objects.filter(
                assigned_to=technician,
                status__in=[Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS],
            ).count(),
            2,
        )
        self.assertEqual(first.assigned_to, technician)

    def test_expired_active_workday_is_not_eligible(self):
        technician = self.technicians[0]
        now = timezone.now()
        TechnicianWorkday.objects.create(
            technician=technician,
            date=timezone.localdate(),
            shift=self.shift,
            started_at=now - timedelta(hours=9),
            scheduled_end_at=now - timedelta(hours=1),
        )
        pending = Ticket.objects.create(
            title="Fuera de horario",
            description="No debe asignarse.",
            requester=self.requester,
            department=self.department,
        )

        self.assertIsNone(auto_assign_ticket(pending, technician=technician))

    def test_waiting_reactivation_is_deferred_when_capacity_is_occupied(self):
        technician = self.technicians[0]
        self.start_workday(technician)
        effective = self.create_auto_ticket(technician, 0)
        waiting = Ticket.objects.create(
            title="Debe reactivarse",
            description="Ya estaba siendo atendido.",
            requester=self.requester,
            department=self.department,
            assigned_to=technician,
            assignment_origin=Ticket.AssignmentOrigin.AUTO,
            status=Ticket.Status.WAITING,
        )
        manager = User.objects.create_user(
            username="waiting-manager",
            email="waiting-manager@example.com",
            password="test-password",
            role=User.Role.SUPERVISOR,
            department=self.department,
        )
        self.client.force_login(manager)

        response = self.client.post(
            reverse("tickets:ticket_detail", args=[waiting.pk]),
            {
                "form_type": "assign",
                "assigned_to": str(technician.pk),
                "status": Ticket.Status.IN_PROGRESS,
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        waiting.refresh_from_db()
        self.assertEqual(waiting.status, Ticket.Status.WAITING)
        self.assertIsNotNone(waiting.reactivation_requested_at)
        self.assertContains(response, "pendiente de reactivación")
        self.assertEqual(effective.assigned_to, technician)

    def test_waiting_reactivation_succeeds_and_clears_request_when_free(self):
        technician = self.technicians[0]
        self.start_workday(technician)
        waiting = Ticket.objects.create(
            title="Reactivación disponible",
            description="El técnico tiene capacidad.",
            requester=self.requester,
            department=self.department,
            assigned_to=technician,
            status=Ticket.Status.WAITING,
            reactivation_requested_at=timezone.now(),
        )
        manager = User.objects.create_user(
            username="free-waiting-manager",
            email="free-waiting-manager@example.com",
            password="test-password",
            role=User.Role.SUPERVISOR,
            department=self.department,
        )
        self.client.force_login(manager)

        response = self.client.post(
            reverse("tickets:ticket_detail", args=[waiting.pk]),
            {
                "form_type": "assign",
                "assigned_to": str(technician.pk),
                "status": Ticket.Status.OPEN,
            },
        )

        self.assertEqual(response.status_code, 302)
        waiting.refresh_from_db()
        self.assertEqual(waiting.status, Ticket.Status.OPEN)
        self.assertIsNone(waiting.reactivation_requested_at)

    def test_requested_waiting_has_priority_when_capacity_is_released(self):
        technician = self.technicians[0]
        self.start_workday(technician)
        effective = self.create_auto_ticket(technician, 0)
        requested_at = timezone.now() - timedelta(minutes=5)
        waiting = Ticket.objects.create(
            title="Esperando reactivación",
            description="Debe tener prioridad.",
            requester=self.requester,
            department=self.department,
            assigned_to=technician,
            assignment_origin=Ticket.AssignmentOrigin.AUTO,
            status=Ticket.Status.WAITING,
            reactivation_requested_at=requested_at,
        )
        later_waiting = Ticket.objects.create(
            title="Reactivación posterior",
            description="Debe conservar la segunda prioridad.",
            requester=self.requester,
            department=self.department,
            assigned_to=technician,
            status=Ticket.Status.WAITING,
            reactivation_requested_at=timezone.now(),
        )
        queued = Ticket.objects.create(
            title="Ticket nuevo en cola",
            description="Debe esperar al WAITING.",
            requester=self.requester,
            department=self.department,
        )
        manager = User.objects.create_user(
            username="priority-manager",
            email="priority-manager@example.com",
            password="test-password",
            role=User.Role.SUPERVISOR,
            department=self.department,
        )
        self.client.force_login(manager)

        response = self.client.post(
            reverse("tickets:ticket_detail", args=[effective.pk]),
            {
                "form_type": "assign",
                "assigned_to": str(technician.pk),
                "status": Ticket.Status.WAITING,
            },
        )

        self.assertEqual(response.status_code, 302)
        waiting.refresh_from_db()
        later_waiting.refresh_from_db()
        queued.refresh_from_db()
        effective.refresh_from_db()
        self.assertEqual(effective.status, Ticket.Status.WAITING)
        self.assertEqual(waiting.status, Ticket.Status.OPEN)
        self.assertIsNone(waiting.reactivation_requested_at)
        self.assertEqual(later_waiting.status, Ticket.Status.WAITING)
        self.assertIsNotNone(later_waiting.reactivation_requested_at)
        self.assertIsNone(queued.assigned_to)

    def test_waiting_without_request_is_not_reactivated_before_queue(self):
        technician = self.technicians[0]
        self.start_workday(technician)
        effective = self.create_auto_ticket(technician, 0)
        waiting = Ticket.objects.create(
            title="Espera sin solicitud",
            description="Debe seguir esperando.",
            requester=self.requester,
            department=self.department,
            assigned_to=technician,
            status=Ticket.Status.WAITING,
        )
        queued = Ticket.objects.create(
            title="Cola válida",
            description="Debe ocupar el cupo.",
            requester=self.requester,
            department=self.department,
        )
        manager = User.objects.create_user(
            username="queue-manager",
            email="queue-manager@example.com",
            password="test-password",
            role=User.Role.SUPERVISOR,
            department=self.department,
        )
        self.client.force_login(manager)

        self.client.post(
            reverse("tickets:ticket_detail", args=[effective.pk]),
            {
                "form_type": "assign",
                "assigned_to": str(technician.pk),
                "status": Ticket.Status.RESOLVED,
            },
        )

        waiting.refresh_from_db()
        queued.refresh_from_db()
        self.assertEqual(waiting.status, Ticket.Status.WAITING)
        self.assertEqual(queued.assigned_to, technician)

    def test_in_progress_to_waiting_releases_capacity_to_oldest_queue(self):
        technician = self.technicians[0]
        self.start_workday(technician)
        effective = self.create_auto_ticket(technician, 0)
        effective.status = Ticket.Status.IN_PROGRESS
        effective.save(update_fields=["status"])
        oldest = Ticket.objects.create(
            title="Más antiguo",
            description="Primero en cola.",
            requester=self.requester,
            department=self.department,
        )
        newer = Ticket.objects.create(
            title="Más nuevo",
            description="Segundo en cola.",
            requester=self.requester,
            department=self.department,
        )
        manager = User.objects.create_user(
            username="release-manager",
            email="release-manager@example.com",
            password="test-password",
            role=User.Role.SUPERVISOR,
            department=self.department,
        )
        self.client.force_login(manager)

        self.client.post(
            reverse("tickets:ticket_detail", args=[effective.pk]),
            {
                "form_type": "assign",
                "assigned_to": str(technician.pk),
                "status": Ticket.Status.WAITING,
            },
        )

        oldest.refresh_from_db()
        newer.refresh_from_db()
        self.assertEqual(oldest.assigned_to, technician)
        self.assertIsNone(newer.assigned_to)

    def test_non_eligible_technician_does_not_receive_after_release(self):
        technician = self.technicians[0]
        self.start_workday(technician)
        effective = self.create_auto_ticket(technician, 0)
        queued = Ticket.objects.create(
            title="Sigue en cola",
            description="El técnico está no disponible.",
            requester=self.requester,
            department=self.department,
        )
        technician.availability_status = User.AvailabilityStatus.UNAVAILABLE
        technician.save(update_fields=["availability_status"])
        manager = User.objects.create_user(
            username="unavailable-manager",
            email="unavailable-manager@example.com",
            password="test-password",
            role=User.Role.SUPERVISOR,
            department=self.department,
        )
        self.client.force_login(manager)

        self.client.post(
            reverse("tickets:ticket_detail", args=[effective.pk]),
            {
                "form_type": "assign",
                "assigned_to": str(technician.pk),
                "status": Ticket.Status.CLOSED,
            },
        )

        queued.refresh_from_db()
        self.assertIsNone(queued.assigned_to)

    def test_resolved_and_closed_release_capacity(self):
        technician = self.technicians[0]
        self.start_workday(technician)
        manager = User.objects.create_user(
            username="terminal-manager",
            email="terminal-manager@example.com",
            password="test-password",
            role=User.Role.SUPERVISOR,
            department=self.department,
        )
        self.client.force_login(manager)

        for status in [Ticket.Status.RESOLVED, Ticket.Status.CLOSED]:
            with self.subTest(status=status):
                Ticket.objects.all().delete()
                effective = self.create_auto_ticket(technician, status)
                queued = Ticket.objects.create(
                    title=f"Cola después de {status}",
                    description="Debe ocupar el cupo liberado.",
                    requester=self.requester,
                    department=self.department,
                )

                response = self.client.post(
                    reverse("tickets:ticket_detail", args=[effective.pk]),
                    {
                        "form_type": "assign",
                        "assigned_to": str(technician.pk),
                        "status": status,
                    },
                )

                self.assertEqual(response.status_code, 302)
                queued.refresh_from_db()
                self.assertEqual(queued.assigned_to, technician)

    def test_manual_and_automatic_workday_finish_release_safe_ticket(self):
        technician = self.technicians[0]

        for automatically in [False, True]:
            with self.subTest(automatically=automatically):
                Ticket.objects.all().delete()
                TechnicianWorkday.objects.all().delete()
                technician.availability_status = User.AvailabilityStatus.AVAILABLE
                technician.save(update_fields=["availability_status"])
                self.start_workday(technician)
                ticket = self.create_auto_ticket(technician, 1)

                finish_technician_workday(
                    technician,
                    automatically=automatically,
                )

                ticket.refresh_from_db()
                technician.refresh_from_db()
                self.assertIsNone(ticket.assigned_to)
                self.assertEqual(ticket.status, Ticket.Status.OPEN)
                self.assertEqual(
                    ticket.assignment_origin,
                    Ticket.AssignmentOrigin.UNKNOWN,
                )
                self.assertEqual(
                    technician.availability_status,
                    User.AvailabilityStatus.UNAVAILABLE,
                )

    def test_close_expired_workdays_releases_safe_ticket(self):
        technician = self.technicians[0]
        workday = self.start_workday(technician)
        workday.scheduled_end_at = timezone.now() - timedelta(minutes=1)
        workday.save(update_fields=["scheduled_end_at"])
        ticket = self.create_auto_ticket(technician, 1)

        self.assertEqual(close_expired_workdays(), 1)

        ticket.refresh_from_db()
        self.assertIsNone(ticket.assigned_to)
        self.assertEqual(ticket.status, Ticket.Status.OPEN)

    def test_unavailable_releases_safe_ticket_but_busy_does_not(self):
        technician = self.technicians[0]
        self.start_workday(technician)
        ticket = self.create_auto_ticket(technician, 1)
        self.client.force_login(technician)

        busy_response = self.client.post(
            reverse("tickets:dashboard"),
            {
                "form_type": "availability",
                "availability_status": User.AvailabilityStatus.BUSY,
            },
        )
        self.assertEqual(busy_response.status_code, 302)
        ticket.refresh_from_db()
        self.assertEqual(ticket.assigned_to, technician)

        unavailable_response = self.client.post(
            reverse("tickets:dashboard"),
            {
                "form_type": "availability",
                "availability_status": User.AvailabilityStatus.UNAVAILABLE,
            },
        )
        self.assertEqual(unavailable_response.status_code, 302)
        ticket.refresh_from_db()
        self.assertIsNone(ticket.assigned_to)

    def test_inactive_policy_keeps_all_protected_assignment_types(self):
        technician = self.technicians[0]
        protected = [
            Ticket.objects.create(
                title="En progreso",
                description="No mover.",
                requester=self.requester,
                department=self.department,
                assigned_to=technician,
                assignment_origin=Ticket.AssignmentOrigin.AUTO,
                status=Ticket.Status.IN_PROGRESS,
            ),
            Ticket.objects.create(
                title="En espera",
                description="No mover.",
                requester=self.requester,
                department=self.department,
                assigned_to=technician,
                assignment_origin=Ticket.AssignmentOrigin.AUTO,
                status=Ticket.Status.WAITING,
            ),
            Ticket.objects.create(
                title="Automático bloqueado",
                description="No mover.",
                requester=self.requester,
                department=self.department,
                assigned_to=technician,
                assignment_origin=Ticket.AssignmentOrigin.AUTO,
                auto_rebalance_locked_at=timezone.now(),
            ),
            Ticket.objects.create(
                title="Manual",
                description="No mover.",
                requester=self.requester,
                department=self.department,
                assigned_to=technician,
                assignment_origin=Ticket.AssignmentOrigin.MANUAL,
            ),
            Ticket.objects.create(
                title="Desconocido",
                description="No mover.",
                requester=self.requester,
                department=self.department,
                assigned_to=technician,
                assignment_origin=Ticket.AssignmentOrigin.UNKNOWN,
            ),
        ]
        worked = Ticket.objects.create(
            title="Automático trabajado",
            description="No mover aunque el bloqueo falte.",
            requester=self.requester,
            department=self.department,
            assigned_to=technician,
            assignment_origin=Ticket.AssignmentOrigin.AUTO,
        )
        TicketComment.objects.create(
            ticket=worked,
            author=technician,
            message="Intervención técnica real.",
            is_system=False,
        )
        protected.append(worked)
        technician.availability_status = User.AvailabilityStatus.UNAVAILABLE
        technician.save(update_fields=["availability_status"])

        release_safe_tickets_for_inactive_technician(
            technician,
            reason="prueba de política segura",
        )

        for ticket in protected:
            ticket.refresh_from_db()
            self.assertEqual(ticket.assigned_to, technician)

    def test_release_reassigns_safely_logs_and_preserves_reactivation_date(self):
        previous, recipient, _ = self.technicians
        self.start_workday(previous)
        self.start_workday(recipient)
        requested_at = timezone.now() - timedelta(minutes=10)
        ticket = self.create_auto_ticket(previous, 1)
        ticket.reactivation_requested_at = requested_at
        ticket.save(update_fields=["reactivation_requested_at"])
        previous.availability_status = User.AvailabilityStatus.UNAVAILABLE
        previous.save(update_fields=["availability_status"])

        released = release_safe_tickets_for_inactive_technician(
            previous,
            reason="el técnico dejó de estar operativo",
        )

        ticket.refresh_from_db()
        self.assertEqual(len(released), 1)
        self.assertEqual(ticket.assigned_to, recipient)
        self.assertEqual(ticket.assignment_origin, Ticket.AssignmentOrigin.AUTO)
        self.assertEqual(ticket.reactivation_requested_at, requested_at)
        self.assertEqual(
            Ticket.objects.filter(
                assigned_to=recipient,
                status__in=[Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS],
            ).count(),
            1,
        )
        logs = ActivityLog.objects.filter(
            object_type="Ticket",
            object_id=str(ticket.pk),
            action=ActivityLog.ACTION_ASSIGN,
        )
        self.assertTrue(logs.filter(description__contains="fue liberado").exists())
        self.assertTrue(logs.filter(description__contains="fue reasignado").exists())


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
