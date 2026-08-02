from apps.notifications.models import Notification


def notifications_context(request):
    """Agrega el conteo de notificaciones no leídas al contexto global."""
    
    context = {}
    
    if request.user.is_authenticated:
        unread_count = Notification.objects.filter(
            recipient=request.user,
            is_read=False,
            is_active=True,
        ).count()
        
        context['navbar_unread_notifications'] = unread_count
    else:
        context['navbar_unread_notifications'] = 0
    
    return context