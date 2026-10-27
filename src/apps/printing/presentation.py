"""Read-only printer monitoring presentation; never probe, persist or infer moves."""
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from .connectivity import effective_status, valid_ip


def valid_recorded_date(value, now):
    # Naive/future timestamps cannot establish a reliable elapsed time.
    if isinstance(value, datetime) and timezone.is_aware(value) and value <= now:
        return value
    return None


def elapsed_label(value, now):
    if value is None:
        return "Sin datos"
    minutes = int((now - value).total_seconds() // 60)
    if minutes < 1:
        return "Hace menos de un minuto"
    days, remaining = divmod(minutes, 1440)
    hours, minutes = divmod(remaining, 60)
    parts = []
    for count, singular, plural in ((days, "día", "días"), (hours, "hora", "horas"), (minutes, "minuto", "minutos")):
        if count:
            parts.append(f"{count} {singular if count == 1 else plural}")
    return "Hace " + ", ".join(parts[:2])


def with_monitoring_display(device, *, now=None):
    now = now or timezone.now()
    checked = valid_recorded_date(device.last_checked_at, now)
    online = valid_recorded_date(device.last_online_at, now)
    if online and checked and online > checked:
        online = None
    status = "UNKNOWN"
    if not device.is_active:
        note = "Equipo archivado: datos de monitoreo históricos."
    elif not device.supports_network:
        note = "Monitoreo de red no habilitado para este equipo."
    elif not valid_ip(device.ip_address):
        note = "Sin IP válida para monitoreo."
    elif checked is None:
        note = "Sin comprobación válida."
    elif now - checked > timedelta(seconds=settings.PRINTING_MONITOR_MAX_AGE_SECONDS):
        note = "Monitoreo desactualizado: no permite determinar la conexión actual."
    else:
        status = effective_status(device, now=now)
        note = "Comprobación reciente." if status != "UNKNOWN" else "Sin evidencia vigente suficiente para determinar la conexión."
    device.monitoring_display = {
        "status": status,
        "label": {"ONLINE": "En línea", "OFFLINE": "Fuera de línea", "UNKNOWN": "Sin estado vigente"}[status],
        "note": note,
        "checked_at": checked,
        "online_at": online,
        "elapsed": elapsed_label(online, now),
        "updated_at": valid_recorded_date(device.updated_at, now),
        "status_changed_at": valid_recorded_date(device.last_status_change_at, now),
        "target_changed": bool(device.monitored_ip and device.monitored_ip != device.ip_address),
    }
    return device
