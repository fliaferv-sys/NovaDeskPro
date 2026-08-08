from django.db.models import Count, Q, F
from django.utils import timezone

from apps.accounts.models import User
from apps.tickets.models import Ticket


ACTIVE_TICKET_STATUSES = [
    Ticket.Status.OPEN,
    Ticket.Status.IN_PROGRESS,
    Ticket.Status.WAITING,
]


def auto_assign_ticket(ticket):
    """
    Asigna automáticamente el ticket al técnico elegible
    con menor carga activa dentro del mismo departamento.

    Criterios:
    1. Menor cantidad de tickets activos.
    2. Técnico que lleva más tiempo sin recibir
       una asignación automática.
    3. ID como último criterio estable.

    Si no existe técnico elegible, el ticket queda sin asignar.
    """

    if not ticket.department_id:
        return None

    technicians = (
        User.objects
        .filter(
            role=User.Role.TECHNICIAN,
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
            department=ticket.department,
        )
        .annotate(
            active_ticket_count=Count(
                "assigned_tickets",
                filter=Q(
                    assigned_tickets__status__in=ACTIVE_TICKET_STATUSES
                ),
            )
        )
        .order_by(
            "active_ticket_count",
            F("last_auto_assignment_at").asc(nulls_first=True),
            "id",
        )
    )

    technician = technicians.first()

    if technician is None:
        return None

    ticket.assigned_to = technician
    ticket.save(update_fields=["assigned_to"])

    technician.last_auto_assignment_at = timezone.now()
    technician.save(
        update_fields=["last_auto_assignment_at"]
    )

    return technician
