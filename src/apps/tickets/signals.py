from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.utils import timezone
from datetime import timedelta

from apps.notifications.models import Notification
from .models import Ticket


@receiver(pre_save, sender=Ticket)
def check_sla_status(sender, instance, **kwargs):
    """
    Verifica el estado del SLA antes de guardar el ticket.
    """
    if instance.due_date:
        now = timezone.now()
        
        # Si ya está vencido
        if instance.due_date < now:
            instance.sla_status = "EXPIRED"
        # Si está por vencer (menos de 4 horas)
        elif instance.due_date < now + timedelta(hours=4):
            instance.sla_status = "WARNING"
        else:
            instance.sla_status = "OK"


@receiver(post_save, sender=Ticket)
def create_sla_notification(sender, instance, created, **kwargs):
    """
    Crea una notificación cuando el SLA cambia a WARNING o EXPIRED.
    """
    # Solo notificar si el ticket tiene due_date y sla_status
    if not instance.due_date or not instance.sla_status:
        return

    # Solo notificar si está WARNING o EXPIRED
    if instance.sla_status not in ["WARNING", "EXPIRED"]:
        return

    # Determinar destinatario (técnico asignado o solicitante)
    recipient = instance.assigned_to or instance.requester

    if not recipient:
        return

    # Verificar si ya existe una notificación similar (evitar duplicados)
    existing = Notification.objects.filter(
        recipient=recipient,
        object_type="Ticket",
        object_id=str(instance.pk),
        is_active=True,
    ).first()

    # Si ya existe una notificación activa, no crear otra
    if existing:
        return

    # Crear la notificación según el estado
    if instance.sla_status == "WARNING":
        title = f"⚠️ Ticket por vencer: {instance.ticket_number}"
        level = Notification.LEVEL_WARNING
        message = (
            f"El ticket {instance.ticket_number} - '{instance.title}' "
            f"está por vencer. Fecha límite: {instance.due_date.strftime('%d/%m/%Y %H:%M')}."
        )
    else:  # EXPIRED
        title = f"🔴 Ticket VENCIDO: {instance.ticket_number}"
        level = Notification.LEVEL_DANGER
        message = (
            f"El ticket {instance.ticket_number} - '{instance.title}' "
            f"ha VENCIDO. Fecha límite: {instance.due_date.strftime('%d/%m/%Y %H:%M')}."
        )

    # Crear la notificación
    Notification.objects.create(
        recipient=recipient,
        notification_type=Notification.TYPE_GENERAL,
        level=level,
        title=title,
        message=message,
        link=f"/tickets/{instance.pk}/",
        object_type="Ticket",
        object_id=str(instance.pk),
        unique_key=f"sla_{instance.pk}_{instance.sla_status}",
    )