from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import (
    Department,
    TechnicianAvailabilityRequest,
    TechnicianWorkday,
    User,
    WorkShift,
)


# ==========================================================
# DEPARTAMENTO DEL USUARIO
# ==========================================================


def get_user_department(user):
    if not hasattr(user, "role"):
        return None

    role_code = user.role.upper()

    department, created = Department.objects.get_or_create(
        code=role_code,
        defaults={
            "name": role_code.capitalize(),
        },
    )

    return department


# ==========================================================
# DETECTAR TURNO SEGÚN HORA DE LLEGADA
# ==========================================================


def detect_work_shift(arrival_datetime=None):
    """
    Determina automáticamente el turno laboral activo
    cuya hora de entrada esté más próxima a la hora
    real de llegada del técnico.
    """

    if arrival_datetime is None:
        arrival_datetime = timezone.now()

    local_arrival = timezone.localtime(arrival_datetime)
    arrival_time = local_arrival.time()

    shifts = WorkShift.objects.filter(
        is_active=True,
    ).order_by("start_time")

    if not shifts.exists():
        return None

    def time_difference(shift):
        arrival_seconds = (
            arrival_time.hour * 3600
            + arrival_time.minute * 60
            + arrival_time.second
        )

        shift_seconds = (
            shift.start_time.hour * 3600
            + shift.start_time.minute * 60
            + shift.start_time.second
        )

        return abs(arrival_seconds - shift_seconds)

    return min(
        shifts,
        key=time_difference,
    )


# ==========================================================
# CALCULAR FIN PROGRAMADO DE JORNADA
# ==========================================================


def calculate_scheduled_end(shift, workday_date):
    """
    Construye la fecha y hora programada de salida
    según el turno seleccionado.
    """

    scheduled_end = datetime.combine(
        workday_date,
        shift.end_time,
    )

    scheduled_end = timezone.make_aware(
        scheduled_end,
        timezone.get_current_timezone(),
    )

    # Permite en el futuro turnos que crucen medianoche.
    if shift.end_time <= shift.start_time:
        scheduled_end += timedelta(days=1)

    return scheduled_end


# ==========================================================
# INICIAR JORNADA DEL TÉCNICO
# ==========================================================


def start_technician_workday(technician):
    """
    Inicia una jornada laboral para el técnico.

    Jornada normal:
    - Entre 06:00 y 07:29:
      turno 07:00 a 15:00.

    - Entre 07:30 y 09:00:
      turno 08:00 a 16:00.

    Jornada extraordinaria:
    - Fuera del rango 06:00 a 09:00.
    - Dura 8 horas desde el momento de inicio.

    Una salida antes de la hora programada requiere
    una solicitud aprobada.

    Si ya existe una jornada activa, no crea otra.
    """

    if technician.role != User.Role.TECHNICIAN:
        raise ValueError(
            "Solo los técnicos pueden iniciar una jornada."
        )

    now = timezone.now()
    local_now = timezone.localtime(now)

    today = local_now.date()
    current_time = local_now.time()

    # ======================================================
    # EVITAR DOS JORNADAS ACTIVAS AL MISMO TIEMPO
    # ======================================================

    active_workday = (
        TechnicianWorkday.objects
        .filter(
            technician=technician,
            status=TechnicianWorkday.Status.ACTIVE,
            ended_at__isnull=True,
        )
        .order_by("-started_at")
        .first()
    )

    if active_workday:
        return active_workday, False

    # ======================================================
    # DETERMINAR JORNADA NORMAL O EXTRAORDINARIA
    # ======================================================

    normal_start = time(6, 0)
    normal_end = time(9, 0)

    is_normal_schedule = (
        normal_start <= current_time <= normal_end
    )

    if is_normal_schedule:

        cutoff = time(7, 30)

        # --------------------------------------------------
        # TURNO 07:00 - 15:00
        # --------------------------------------------------

        if current_time < cutoff:
            shift = WorkShift.objects.filter(
                is_active=True,
                start_time=time(7, 0),
                end_time=time(15, 0),
            ).first()

        # --------------------------------------------------
        # TURNO 08:00 - 16:00
        # --------------------------------------------------

        else:
            shift = WorkShift.objects.filter(
                is_active=True,
                start_time=time(8, 0),
                end_time=time(16, 0),
            ).first()

        if shift is None:
            raise ValueError(
                "No se encontró el turno laboral correspondiente."
            )

        scheduled_end = calculate_scheduled_end(
            shift,
            today,
        )

    else:

        # ==================================================
        # HORARIO ESPECIAL / EXTRAORDINARIO
        # ==================================================

        shift, _ = WorkShift.objects.get_or_create(
            name="Horario especial",
            defaults={
                "start_time": time(0, 0),
                "end_time": time(0, 0),
                "is_active": False,
            },
        )

        # La jornada extraordinaria dura 8 horas
        # desde el momento real en que fue iniciada.
        scheduled_end = now + timedelta(hours=8)

    # ======================================================
    # CREAR JORNADA
    # ======================================================

    workday = TechnicianWorkday.objects.create(
        technician=technician,
        date=today,
        shift=shift,
        started_at=now,
        scheduled_end_at=scheduled_end,
        status=TechnicianWorkday.Status.ACTIVE,
    )

    # Al iniciar jornada pasa automáticamente a Disponible.
    technician.availability_status = (
        User.AvailabilityStatus.AVAILABLE
    )

    technician.save(
        update_fields=[
            "availability_status",
        ]
    )

    return workday, True


# ==========================================================
# FINALIZAR JORNADA DEL TÉCNICO
# ==========================================================


def finish_technician_workday(
    technician,
    automatically=False,
    authorized=False,
):
    """
    Finaliza la jornada activa del técnico.

    - registra la hora real de salida;
    - cambia la jornada a Finalizada;
    - indica si fue finalizada automáticamente;
    - cambia la disponibilidad a No disponible.
    """

    workday = (
        TechnicianWorkday.objects
        .filter(
            technician=technician,
            status=TechnicianWorkday.Status.ACTIVE,
            ended_at__isnull=True,
        )
        .order_by("-started_at")
        .select_related("shift")
        .first()
    )

    if workday is None:
        raise ValueError(
            "No existe una jornada activa para finalizar."
        )

    if (
        not automatically
        and not authorized
        and workday.scheduled_end_at > timezone.now()
    ):
        raise ValidationError(
            "La salida anticipada requiere una solicitud aprobada."
        )

    if automatically:
        ended_at = workday.scheduled_end_at
    else:
        ended_at = timezone.now()

    workday.ended_at = ended_at
    workday.status = TechnicianWorkday.Status.FINISHED
    workday.ended_automatically = automatically

    workday.save(
        update_fields=[
            "ended_at",
            "status",
            "ended_automatically",
            "updated_at",
        ]
    )

    technician.availability_status = (
        User.AvailabilityStatus.UNAVAILABLE
    )

    technician.save(
        update_fields=[
            "availability_status",
        ]
    )

    return workday


# ==========================================================
# FINALIZAR JORNADAS VENCIDAS AUTOMÁTICAMENTE
# ==========================================================


def close_expired_workdays():
    """
    Finaliza automáticamente todas las jornadas activas
    cuya hora programada de salida ya fue alcanzada.

    Ejemplos:

    Turno normal:
    - 07:00 - 15:00 -> finaliza a las 15:00.
    - 08:00 - 16:00 -> finaliza a las 16:00.

    Horario especial:
    - finaliza 8 horas después de haber iniciado.
    """

    now = timezone.now()

    expired_workdays = (
        TechnicianWorkday.objects
        .filter(
            status=TechnicianWorkday.Status.ACTIVE,
            ended_at__isnull=True,
            scheduled_end_at__lte=now,
        )
        .select_related(
            "technician",
            "shift",
        )
        .order_by("scheduled_end_at")
    )

    closed_count = 0

    for workday in expired_workdays:
        workday.ended_at = workday.scheduled_end_at
        workday.status = TechnicianWorkday.Status.FINISHED
        workday.ended_automatically = True

        workday.save(
            update_fields=[
                "ended_at",
                "status",
                "ended_automatically",
                "updated_at",
            ]
        )

        technician = workday.technician

        technician.availability_status = (
            User.AvailabilityStatus.UNAVAILABLE
        )

        technician.save(
            update_fields=[
                "availability_status",
            ]
        )

        closed_count += 1

    return closed_count


def get_active_technician_workday(technician):
    return (
        TechnicianWorkday.objects
        .filter(
            technician=technician,
            status=TechnicianWorkday.Status.ACTIVE,
            ended_at__isnull=True,
            scheduled_end_at__gt=timezone.now(),
        )
        .order_by("-started_at")
        .first()
    )


def _user_display_name(user):
    return user.get_full_name().strip() or user.email


def _request_action_display(availability_request):
    if (
        availability_request.request_type
        == TechnicianAvailabilityRequest.RequestType.EARLY_WORKDAY_END
    ):
        return "salida anticipada"
    return "quedar No disponible"


def _notify_availability_request_created(availability_request):
    from apps.notifications.models import Notification
    from apps.notifications.services import (
        create_or_update_notification,
        send_web_push_to_user,
    )

    recipients = User.objects.filter(
        role__in=[User.Role.ADMIN, User.Role.SUPERVISOR],
        is_active=True,
    )
    link = reverse("dashboard:technician_control")
    message = (
        f"{_user_display_name(availability_request.technician)} solicita "
        f"{_request_action_display(availability_request)}."
    )
    for recipient in recipients.iterator():
        unique_key = (
            f"technician-availability-request-{availability_request.pk}-"
            f"created-{recipient.pk}"
        )
        _, created = create_or_update_notification(
            recipient=recipient,
            notification_type=Notification.TYPE_GENERAL,
            level=Notification.LEVEL_WARNING,
            title="Solicitud de técnico pendiente",
            message=message,
            link=link,
            object_type="TechnicianAvailabilityRequest",
            object_id=availability_request.pk,
            unique_key=unique_key,
        )
        if created:
            transaction.on_commit(
                lambda recipient=recipient, unique_key=unique_key: (
                    send_web_push_to_user(
                        user=recipient,
                        title="Solicitud de técnico pendiente",
                        body=message,
                        url=link,
                        tag=unique_key,
                    )
                )
            )


def _notify_availability_request_resolved(availability_request):
    from apps.notifications.models import Notification
    from apps.notifications.services import (
        create_or_update_notification,
        send_web_push_to_user,
    )

    approved = (
        availability_request.status
        == TechnicianAvailabilityRequest.Status.APPROVED
    )
    resolution = "aprobada" if approved else "rechazada"
    title = f"Solicitud de técnico {resolution}"
    message = (
        f"Tu solicitud de {_request_action_display(availability_request)} "
        f"fue {resolution}."
    )
    recipient = availability_request.technician
    link = reverse("tickets:dashboard")
    unique_key = (
        f"technician-availability-request-{availability_request.pk}-"
        f"{availability_request.status.lower()}-{recipient.pk}"
    )
    _, created = create_or_update_notification(
        recipient=recipient,
        notification_type=Notification.TYPE_GENERAL,
        level=(
            Notification.LEVEL_SUCCESS
            if approved
            else Notification.LEVEL_INFO
        ),
        title=title,
        message=message,
        link=link,
        object_type="TechnicianAvailabilityRequest",
        object_id=availability_request.pk,
        unique_key=unique_key,
    )
    if created:
        transaction.on_commit(
            lambda: send_web_push_to_user(
                user=recipient,
                title=title,
                body=message,
                url=link,
                tag=unique_key,
            )
        )


@transaction.atomic
def create_technician_availability_request(technician, request_type, reason):
    reason = (reason or "").strip()
    if technician.role != User.Role.TECHNICIAN:
        raise ValidationError("Solo los técnicos pueden crear esta solicitud.")
    if request_type not in TechnicianAvailabilityRequest.RequestType.values:
        raise ValidationError("El tipo de solicitud no es válido.")
    if not reason:
        raise ValidationError("Debe indicar el motivo de la solicitud.")

    workday = get_active_technician_workday(technician)
    if workday is None:
        raise ValidationError("Debe tener una jornada activa para enviar la solicitud.")
    if TechnicianAvailabilityRequest.objects.filter(
        technician=technician,
        workday=workday,
        request_type=request_type,
        status=TechnicianAvailabilityRequest.Status.PENDING,
    ).exists():
        raise ValidationError("Ya existe una solicitud pendiente del mismo tipo.")

    availability_request = TechnicianAvailabilityRequest.objects.create(
        technician=technician,
        workday=workday,
        request_type=request_type,
        reason=reason,
    )
    _notify_availability_request_created(availability_request)
    return availability_request


@transaction.atomic
def resolve_technician_availability_request(
    availability_request,
    resolved_by,
    approve,
    resolution_note="",
):
    if resolved_by.role not in {User.Role.ADMIN, User.Role.SUPERVISOR}:
        raise ValidationError("No tiene autorización para resolver solicitudes.")

    availability_request = (
        TechnicianAvailabilityRequest.objects
        .select_for_update()
        .select_related("technician", "workday")
        .get(pk=availability_request.pk)
    )
    if availability_request.technician_id == resolved_by.pk:
        raise ValidationError("El técnico no puede resolver su propia solicitud.")
    if availability_request.status != TechnicianAvailabilityRequest.Status.PENDING:
        raise ValidationError("La solicitud ya fue resuelta.")

    if approve:
        if (
            not availability_request.workday.is_active_workday
            or availability_request.workday.scheduled_end_at <= timezone.now()
        ):
            raise ValidationError("La jornada relacionada ya no está activa.")
        if availability_request.request_type == TechnicianAvailabilityRequest.RequestType.UNAVAILABLE:
            technician = availability_request.technician
            technician.availability_status = User.AvailabilityStatus.UNAVAILABLE
            technician.save(update_fields=["availability_status"])
        else:
            finish_technician_workday(
                availability_request.technician,
                authorized=True,
            )
        availability_request.status = TechnicianAvailabilityRequest.Status.APPROVED
    else:
        availability_request.status = TechnicianAvailabilityRequest.Status.REJECTED

    availability_request.resolved_at = timezone.now()
    availability_request.resolved_by = resolved_by
    availability_request.resolution_note = (resolution_note or "").strip()
    availability_request.save(
        update_fields=[
            "status",
            "resolved_at",
            "resolved_by",
            "resolution_note",
            "updated_at",
        ]
    )
    _notify_availability_request_resolved(availability_request)
    return availability_request
