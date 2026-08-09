from django.db.models import Count, F, Q
from django.utils import timezone

from apps.accounts.models import (
    TechnicianWorkday,
    User,
)
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

    technicians = (
        User.objects
        .filter(
            role=User.Role.TECHNICIAN,
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
            availability_status=User.AvailabilityStatus.AVAILABLE,
            department=ticket.department,

            # Debe tener una jornada activa.
            technician_workdays__status=TechnicianWorkday.Status.ACTIVE,
            technician_workdays__ended_at__isnull=True,
        )
        .annotate(
            active_ticket_count=Count(
                "assigned_tickets",
                filter=Q(
                    assigned_tickets__status__in=ACTIVE_TICKET_STATUSES
                ),
                distinct=True,
            )
        )
        .filter(
            active_ticket_count__lt=MAX_ACTIVE_TICKETS_PER_TECHNICIAN
        )
        .order_by(
            "active_ticket_count",
            F("last_auto_assignment_at").asc(nulls_first=True),
            "id",
        )
        .distinct()
    )

    if technician is not None:
        technicians = technicians.filter(pk=technician.pk)

    technician = technicians.first()

    if technician is None:
        return None

    ticket.assigned_to = technician
    ticket.save(
        update_fields=["assigned_to"]
    )

    technician.last_auto_assignment_at = timezone.now()
    technician.save(
        update_fields=["last_auto_assignment_at"]
    )

    return technician


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
