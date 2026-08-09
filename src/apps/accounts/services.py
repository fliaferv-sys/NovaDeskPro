from datetime import datetime, time, timedelta

from django.utils import timezone

from .models import (
    Department,
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

    El técnico puede finalizar cualquier jornada
    manualmente antes de la hora programada.

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