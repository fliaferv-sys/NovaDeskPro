from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from apps.accounts.models import (
    TechnicianWorkday,
    User,
)
from apps.activity.models import ActivityLog
from apps.tickets.models import Ticket


# ==========================================================
# CONFIGURACIÓN DE AUTOASIGNACIÓN
# ==========================================================

MAX_ACTIVE_TICKETS_PER_TECHNICIAN = 3

ACTIVE_TICKET_STATUSES = [
    Ticket.Status.OPEN,
    Ticket.Status.IN_PROGRESS,
    Ticket.Status.WAITING,
]


# ==========================================================
# AUTOASIGNAR UN TICKET
# ==========================================================

def _eligible_technicians(department):
    active_workday = TechnicianWorkday.objects.filter(
        technician_id=OuterRef("pk"),
        status=TechnicianWorkday.Status.ACTIVE,
        ended_at__isnull=True,
    )
    return (
        User.objects
        .filter(
            role=User.Role.TECHNICIAN,
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
            availability_status=User.AvailabilityStatus.AVAILABLE,
            department=department,
        )
        .filter(Exists(active_workday))
    )


def _active_ticket_count(technician):
    return Ticket.objects.filter(
        assigned_to=technician,
        status__in=ACTIVE_TICKET_STATUSES,
    ).count()


@transaction.atomic
def auto_assign_ticket(ticket, technician=None):
    """
    Asigna automáticamente el ticket al técnico elegible
    con menor carga activa dentro del mismo departamento.

    Requisitos del técnico:
    1. Rol TECHNICIAN.
    2. Usuario activo y aprobado.
    3. Estado Disponible.
    4. Jornada laboral activa.
    5. Menos de 3 tickets activos.

    Criterios de selección:
    1. Menor cantidad de tickets activos.
    2. Técnico que lleva más tiempo sin recibir
       una asignación automática.
    3. ID como último criterio estable.

    Si todos los técnicos llegaron a 3 tickets activos,
    el ticket queda abierto y sin asignar.
    """

    if not ticket.department_id:
        return None

    technicians = _eligible_technicians(ticket.department)

    if technician is not None:
        technicians = technicians.filter(pk=technician.pk)

    locked_technicians = list(technicians.select_for_update())
    candidates = []
    for candidate in locked_technicians:
        active_count = _active_ticket_count(candidate)
        if active_count < MAX_ACTIVE_TICKETS_PER_TECHNICIAN:
            candidates.append((active_count, candidate))

    candidates.sort(
        key=lambda item: (
            item[0],
            item[1].last_auto_assignment_at.timestamp()
            if item[1].last_auto_assignment_at
            else float("-inf"),
            str(item[1].pk),
        )
    )

    technician = candidates[0][1] if candidates else None

    if technician is None:
        return None

    ticket.assigned_to = technician
    ticket.assignment_origin = Ticket.AssignmentOrigin.AUTO
    ticket.save(
        update_fields=["assigned_to", "assignment_origin"]
    )

    technician.last_auto_assignment_at = timezone.now()
    technician.save(
        update_fields=["last_auto_assignment_at"]
    )

    return technician


def lock_ticket_from_auto_rebalancing(ticket, user):
    """Bloquea de forma irreversible un ticket trabajado por su técnico."""
    if (
        ticket.assigned_to_id != getattr(user, "pk", None)
        or ticket.assignment_origin != Ticket.AssignmentOrigin.AUTO
        or ticket.auto_rebalance_locked_at is not None
    ):
        return False

    locked_at = timezone.now()
    updated = Ticket.objects.filter(
        pk=ticket.pk,
        assigned_to=user,
        assignment_origin=Ticket.AssignmentOrigin.AUTO,
        auto_rebalance_locked_at__isnull=True,
    ).update(auto_rebalance_locked_at=locked_at)
    if updated:
        ticket.auto_rebalance_locked_at = locked_at
    return bool(updated)


def _has_real_technician_intervention(ticket, technician):
    return (
        ticket.comments.filter(
            author=technician,
            is_system=False,
        ).exists()
        or ticket.attachments.filter(uploaded_by=technician).exists()
    )


@transaction.atomic
def rebalance_unworked_auto_assigned_tickets(department):
    """Equilibra carga moviendo solo tickets automáticos sin trabajo."""
    if department is None:
        return []

    technicians = list(
        _eligible_technicians(department)
        .select_for_update()
    )
    if len(technicians) < 2:
        return []

    list(
        TechnicianWorkday.objects.select_for_update().filter(
            technician__in=technicians,
            status=TechnicianWorkday.Status.ACTIVE,
            ended_at__isnull=True,
        ).values_list("pk", flat=True)
    )

    loads = {
        technician.pk: _active_ticket_count(technician)
        for technician in technicians
    }
    technicians_by_id = {
        technician.pk: technician
        for technician in technicians
    }
    moved = []

    while max(loads.values()) - min(loads.values()) > 1:
        recipient_id = min(
            loads,
            key=lambda pk: (loads[pk], str(pk)),
        )
        recipient = technicians_by_id[recipient_id]
        donor_ids = sorted(
            (
                pk for pk in loads
                if loads[pk] - loads[recipient_id] > 1
            ),
            key=lambda pk: (-loads[pk], str(pk)),
        )

        ticket_to_move = None
        previous_technician = None
        for donor_id in donor_ids:
            donor = technicians_by_id[donor_id]
            candidates = (
                Ticket.objects
                .select_for_update()
                .filter(
                    department=department,
                    assigned_to=donor,
                    assignment_origin=Ticket.AssignmentOrigin.AUTO,
                    auto_rebalance_locked_at__isnull=True,
                    status=Ticket.Status.OPEN,
                )
                .order_by("-created_at", "-id")
            )
            for candidate in candidates:
                if not _has_real_technician_intervention(candidate, donor):
                    ticket_to_move = candidate
                    previous_technician = donor
                    break
            if ticket_to_move is not None:
                break

        if ticket_to_move is None:
            break

        recipient_is_eligible = _eligible_technicians(department).filter(
            pk=recipient.pk
        ).exists()
        recipient_load = _active_ticket_count(recipient)
        ticket_to_move.refresh_from_db()

        if (
            not recipient_is_eligible
            or recipient_load >= MAX_ACTIVE_TICKETS_PER_TECHNICIAN
            or ticket_to_move.assignment_origin != Ticket.AssignmentOrigin.AUTO
            or ticket_to_move.auto_rebalance_locked_at is not None
            or ticket_to_move.status != Ticket.Status.OPEN
            or ticket_to_move.assigned_to_id != previous_technician.pk
            or _has_real_technician_intervention(
                ticket_to_move,
                previous_technician,
            )
        ):
            break

        ticket_to_move.assigned_to = recipient
        ticket_to_move.save(update_fields=["assigned_to"])
        recipient.last_auto_assignment_at = timezone.now()
        recipient.save(update_fields=["last_auto_assignment_at"])

        ActivityLog.objects.create(
            user=None,
            action=ActivityLog.ACTION_ASSIGN,
            module="Tickets",
            description=(
                f"El ticket {ticket_to_move.ticket_number} fue redistribuido "
                "automáticamente de "
                f"{previous_technician.get_full_name() or previous_technician.email} "
                "a "
                f"{recipient.get_full_name() or recipient.email}."
            ),
            object_type="Ticket",
            object_id=str(ticket_to_move.pk),
        )
        loads[previous_technician.pk] -= 1
        loads[recipient.pk] = recipient_load + 1
        moved.append((ticket_to_move, previous_technician, recipient))

    return moved


# ==========================================================
# ASIGNAR TICKETS PENDIENTES CUANDO SE LIBERA UN CUPO
# ==========================================================

def assign_pending_tickets_for_department(department, technician=None):
    """
    Revisa los tickets abiertos y sin asignar del departamento.

    Siempre intenta asignar primero el ticket más antiguo.

    Continúa mientras exista:
    - un ticket pendiente;
    - y algún técnico con capacidad disponible.

    Cuando todos los técnicos llegan a 3 tickets activos,
    los tickets restantes continúan sin asignar.
    """

    if department is None:
        return []

    assigned_tickets = []

    while True:
        pending_ticket = (
            Ticket.objects
            .filter(
                department=department,
                assigned_to__isnull=True,
                status=Ticket.Status.OPEN,
            )
            .order_by(
                "created_at",
                "id",
            )
            .first()
        )

        if pending_ticket is None:
            break

        assigned_technician = auto_assign_ticket(
            pending_ticket,
            technician=technician,
        )

        if assigned_technician is None:
            # Todos los técnicos están sin jornada,
            # no disponibles o alcanzaron 3/3.
            break

        assigned_tickets.append(
            (
                pending_ticket,
                assigned_technician,
            )
        )

    return assigned_tickets
