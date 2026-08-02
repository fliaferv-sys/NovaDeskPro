from django.db.models import Count, Q
from django.utils import timezone
from datetime import timedelta

from .models import Ticket


def get_user_position_in_queue(user):
    """
    Calcula la posición del usuario en la cola de tickets activos.
    
    Retorna:
        dict: {
            'position': int (posición en cola, 1 = primero),
            'total_ahead': int (total de tickets antes del usuario),
            'estimated_time': str (tiempo estimado de espera)
        }
    """
    # Tickets activos (no cerrados ni resueltos)
    active_tickets = Ticket.objects.filter(
        ~Q(status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED])
    )
    
    # Ordenar por prioridad y fecha (críticos primero)
    priority_order = {
        Ticket.Priority.CRITICAL: 1,
        Ticket.Priority.HIGH: 2,
        Ticket.Priority.MEDIUM: 3,
        Ticket.Priority.LOW: 4,
    }
    
    # Obtener todos los tickets activos ordenados
    ordered_tickets = list(active_tickets.order_by(
        'priority',  # Primero por prioridad (CRITICAL es el primero)
        '-created_at'  # Luego por fecha (más antiguo primero)
    ))
    
    # Encontrar la posición del usuario
    position = 1
    user_ticket = None
    
    for idx, ticket in enumerate(ordered_tickets, 1):
        if ticket.requester == user:
            position = idx
            user_ticket = ticket
            break
    
    total_ahead = position - 1
    
    # Calcular tiempo estimado (simulado)
    # Asumimos 15 minutos por ticket como promedio
    estimated_minutes = total_ahead * 15
    if estimated_minutes > 60:
        hours = estimated_minutes // 60
        minutes = estimated_minutes % 60
        estimated_time = f"{hours}h {minutes}min"
    else:
        estimated_time = f"{estimated_minutes} minutos"
    
    return {
        'position': position if user_ticket else None,
        'total_ahead': total_ahead if user_ticket else 0,
        'estimated_time': estimated_time if user_ticket else "Sin espera",
        'has_active_ticket': user_ticket is not None,
        'active_ticket': user_ticket,
    }


def get_user_dashboard_stats(user):
    """
    Obtiene estadísticas rápidas para el dashboard del usuario.
    
    Retorna:
        dict: {
            'total_tickets': int,
            'open_tickets': int,
            'in_progress_tickets': int,
            'resolved_tickets': int,
            'closed_tickets': int,
            'pending_tickets': int,
        }
    """
    user_tickets = Ticket.objects.filter(requester=user)
    
    return {
        'total_tickets': user_tickets.count(),
        'open_tickets': user_tickets.filter(status=Ticket.Status.OPEN).count(),
        'in_progress_tickets': user_tickets.filter(status=Ticket.Status.IN_PROGRESS).count(),
        'waiting_tickets': user_tickets.filter(status=Ticket.Status.WAITING).count(),
        'resolved_tickets': user_tickets.filter(status=Ticket.Status.RESOLVED).count(),
        'closed_tickets': user_tickets.filter(status=Ticket.Status.CLOSED).count(),
        'pending_tickets': user_tickets.filter(
            ~Q(status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED])
        ).count(),
    }


def get_user_active_ticket(user):
    """
    Obtiene el ticket activo más reciente del usuario.
    
    Retorna:
        Ticket or None: El ticket activo más reciente
    """
    return Ticket.objects.filter(
        requester=user,
    ).exclude(
        status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED]
    ).order_by('-created_at').first()


def get_user_recent_tickets(user, limit=5):
    """
    Obtiene los últimos tickets del usuario.
    
    Retorna:
        QuerySet: Los últimos N tickets del usuario
    """
    return Ticket.objects.filter(
        requester=user
    ).order_by('-created_at')[:limit]


def get_user_ticket_history(user, status_filter=None):
    """
    Obtiene el historial de tickets del usuario con filtro opcional.
    
    Args:
        user: Usuario
        status_filter: Estado para filtrar (opcional)
    
    Retorna:
        QuerySet: Tickets filtrados
    """
    tickets = Ticket.objects.filter(requester=user)
    
    if status_filter:
        tickets = tickets.filter(status=status_filter)
    
    return tickets.order_by('-created_at')


def get_queue_stats():
    """
    Obtiene estadísticas generales de la cola.
    
    Retorna:
        dict: {
            'total_active': int,
            'critical_count': int,
            'high_count': int,
            'medium_count': int,
            'low_count': int,
            'avg_wait_time': str,
        }
    """
    active_tickets = Ticket.objects.filter(
        ~Q(status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED])
    )
    
    # Calcular tiempo promedio de espera (simulado)
    # En un sistema real, se calcularía desde la base de datos
    avg_wait = 15  # minutos
    
    return {
        'total_active': active_tickets.count(),
        'critical_count': active_tickets.filter(priority=Ticket.Priority.CRITICAL).count(),
        'high_count': active_tickets.filter(priority=Ticket.Priority.HIGH).count(),
        'medium_count': active_tickets.filter(priority=Ticket.Priority.MEDIUM).count(),
        'low_count': active_tickets.filter(priority=Ticket.Priority.LOW).count(),
        'avg_wait_time': f"{avg_wait} minutos",
    }


def get_tickets_by_priority(user):
    """
    Obtiene la cantidad de tickets por prioridad para un usuario.
    
    Retorna:
        dict: { 'CRITICAL': 0, 'HIGH': 0, 'MEDIUM': 0, 'LOW': 0 }
    """
    tickets = Ticket.objects.filter(requester=user)
    
    return {
        'CRITICAL': tickets.filter(priority=Ticket.Priority.CRITICAL).count(),
        'HIGH': tickets.filter(priority=Ticket.Priority.HIGH).count(),
        'MEDIUM': tickets.filter(priority=Ticket.Priority.MEDIUM).count(),
        'LOW': tickets.filter(priority=Ticket.Priority.LOW).count(),
    }