import csv
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.db.models import Q

from apps.accounts.models import User
from apps.directory.ad_services import (
    ActiveDirectoryError,
    get_ad_user_by_email,
    search_ad_users,
)
from apps.directory.services import (
    DirectoryDatabaseError,
    get_directory_employee_by_id_personal,
    get_directory_employees,
    search_directory_employees,
)
from apps.institution.models import InstitutionalIdentityAssignment


class InstitutionalIdentityError(Exception):
    pass


SOURCE_RRHH = "RRHH"
SOURCE_ACTIVE_DIRECTORY = "ACTIVE_DIRECTORY"
SOURCE_LOCAL = "LOCAL"


DIRECTORY_DEFAULT_LIMIT = 5000

LINK_PERMANENT = "PERMANENT"
LINK_CONTRACTED = "CONTRACTED"
LINK_OUTSOURCED = "OUTSOURCED"
LINK_OTHER = "OTHER"

_VINCULO_FIRST_WORD = {
    "permanente": LINK_PERMANENT,
    "contratado": LINK_CONTRACTED,
    "tercerizado": LINK_OUTSOURCED,
}


def _normalize_vinculo_token(value):
    """Normaliza un vÃ­nculo de RR.HH. para comparar sin depender de
    mayÃºsculas, minÃºsculas ni espacios sobrantes."""
    if value is None:
        return ""
    return " ".join(str(value).split()).casefold()


def classify_rrhh_vinculo(vinculo):
    """Clasifica el vÃ­nculo de RR.HH. en las cuatro categorÃ­as de los KPI.

    La comparaciÃ³n es robusta: ignora mayÃºsculas/minÃºsculas, colapsa espacios
    y toma la primera palabra, de modo que variantes como ``"PERMANENTE "``,
    ``"Permanente  (Ley 15)"`` o ``"Contratado"`` se clasifican igual.
    Cualquier otro vÃ­nculo (comisionado, pasante, etc.) cae en "OTROS".
    """
    normalized = _normalize_vinculo_token(vinculo)
    if not normalized:
        return LINK_OTHER

    first_word = normalized.split(" ")[0]
    return _VINCULO_FIRST_WORD.get(first_word, LINK_OTHER)


def build_institutional_kpis(identities):
    """Calcula los KPI institucionales sobre el listado completo de RR.HH."""
    counts = {
        LINK_PERMANENT: 0,
        LINK_CONTRACTED: 0,
        LINK_OUTSOURCED: 0,
        LINK_OTHER: 0,
    }

    for identity in identities or ():
        counts[classify_rrhh_vinculo(identity.get("employment_type"))] += 1

    return {
        "total": len(identities or ()),
        "permanent": counts[LINK_PERMANENT],
        "contracted": counts[LINK_CONTRACTED],
        "outsourced": counts[LINK_OUTSOURCED],
        "other": counts[LINK_OTHER],
    }


def get_institutional_directory(limit=DIRECTORY_DEFAULT_LIMIT):
    """Devuelve el directorio completo de funcionarios de RR.HH. en orden
    alfabÃ©tico (el que entrega SQL).

    Se usa exclusivamente para la vista completa: no mezcla Active Directory
    ni cuentas locales. El enriquecimiento de dependencia se sigue resolviendo
    persona por persona con ``_enrich_with_organizational_unit``, conservando el
    comportamiento actual y el orden recibido de la base.
    """
    rows = get_directory_employees(limit=limit)

    directory = []
    for row in rows:
        identity = _normalize_rrhh_employee(row)
        enriched = _enrich_with_organizational_unit(identity)
        if enriched is not None:
            directory.append(enriched)

    return directory


def _enrich_with_organizational_unit(identity):
    if identity is None:
        return None

    enriched_identity = identity.copy()
    assignment_query = InstitutionalIdentityAssignment.objects.filter(
        is_active=True,
    ).select_related("organizational_unit")
    assignment = None

    id_personal = enriched_identity.get("id_personal")
    if id_personal is not None:
        assignment = assignment_query.filter(id_personal=id_personal).first()

    email = enriched_identity.get("email")
    normalized_email = email.strip().lower() if email else ""
    if assignment is None and normalized_email:
        assignment = assignment_query.filter(email=normalized_email).first()

    username = enriched_identity.get("username")
    normalized_username = username.strip().lower() if username else ""
    if assignment is None and normalized_username:
        assignment = assignment_query.filter(username=normalized_username).first()

    if assignment is None:
        enriched_identity["organizational_unit"] = None
        enriched_identity["organizational_path"] = []
        return enriched_identity

    unit = assignment.organizational_unit
    enriched_identity["organizational_unit"] = {
        "code": unit.code,
        "name": unit.name,
        "type": unit.unit_type,
        "type_display": unit.get_unit_type_display(),
    }

    organizational_path = []
    current_unit = unit
    while current_unit is not None:
        organizational_path.append(
            {
                "code": current_unit.code,
                "name": current_unit.name,
                "type": current_unit.unit_type,
                "type_display": current_unit.get_unit_type_display(),
            }
        )
        current_unit = current_unit.parent
    organizational_path.reverse()
    enriched_identity["organizational_path"] = organizational_path

    return enriched_identity


def _build_employee_photo_url(employee_number):
    employee_number = str(employee_number or "").strip()
    if not employee_number:
        return ""

    media_dir = Path(settings.MEDIA_ROOT) / "funcionarios"

    for extension in (".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"):
        file_name = f"{employee_number}F{extension}"
        if (media_dir / file_name).exists():
            return f"{settings.MEDIA_URL}funcionarios/{file_name}"

    return ""


@lru_cache(maxsize=1)
def _load_tercerizados():
    csv_path = Path(__file__).resolve().parent / "data" / "tercerizados.csv"

    if not csv_path.exists():
        return {}

    terceros = {}

    try:
        with csv_path.open(
            mode="r",
            encoding="utf-8-sig",
            newline="",
        ) as file:
            reader = csv.DictReader(file)

            for row in reader:
                email = str(row.get("CorreoAD") or "").strip().casefold()
                username = str(row.get("UsuarioAD") or "").strip().casefold()

                data = {
                    "ci": str(row.get("CI") or "").strip(),
                    "photo_file": str(row.get("ArchivoFoto") or "").strip(),
                }

                if email:
                    terceros[f"email:{email}"] = data

                if username:
                    terceros[f"username:{username}"] = data

    except (OSError, csv.Error):
        return {}

    return terceros


def _get_tercerizado(user):
    terceros = _load_tercerizados()

    email = str(user.get("email") or "").strip().casefold()
    username = str(user.get("username") or "").strip().casefold()

    if email:
        tercero = terceros.get(f"email:{email}")
        if tercero:
            return tercero

    if username:
        tercero = terceros.get(f"username:{username}")
        if tercero:
            return tercero

    return None


def _build_tercerizado_photo_url(tercero):
    if not tercero:
        return ""

    file_name = str(tercero.get("photo_file") or "").strip()

    if not file_name:
        return ""

    # Solo aceptar el nombre de archivo, nunca una ruta externa.
    if Path(file_name).name != file_name:
        return ""

    photo_path = Path(settings.MEDIA_ROOT) / "funcionarios" / file_name

    if not photo_path.exists():
        return ""

    return f"{settings.MEDIA_URL}funcionarios/{file_name}"

def _normalize_rrhh_employee(employee):
    return {
        "source": SOURCE_RRHH,
        "id_personal": employee.get("IdPersonal"),
        "employee_number": employee.get("LegajoNro") or "",
        "name": employee.get("NombresApellidos") or "",
        "first_name": "",
        "last_name": "",
        "email": employee.get("Mail") or "",
        "phone": employee.get("Telefono") or "",
        "location": employee.get("Ubicacion") or "",
        "position": employee.get("Cargo") or "",
        "employment_type": employee.get("Vinculo") or "",
        "status": employee.get("Estado") or "",
        "username": "",
        "is_active": employee.get("Estado") == "Activo",
        "photo_url": _build_employee_photo_url(employee.get("LegajoNro") or ""),
    }


def _normalize_ad_user(user):
    is_active = bool(user.get("is_active", False))
    tercero = _get_tercerizado(user)

    return {
        "source": SOURCE_ACTIVE_DIRECTORY,
        "id_personal": None,
        "employee_number": "",
        "name": user.get("name") or "",
        "first_name": user.get("first_name") or "",
        "last_name": user.get("last_name") or "",
        "email": user.get("email") or "",
        "phone": "",
        "location": "",
        "position": "",
        "employment_type": "Tercerizado" if tercero else "",
        "status": "Activo" if is_active else "Inactivo",
        "username": user.get("username") or "",
        "is_active": is_active,
        "photo_url": _build_tercerizado_photo_url(tercero),
    }

def _normalize_local_user(user):
    employment_type_display = getattr(
        user,
        "get_employment_type_display",
        None,
    )
    employment_type = (
        employment_type_display()
        if callable(employment_type_display)
        else ""
    )
    department = getattr(user, "department", None)

    return {
        "source": SOURCE_LOCAL,
        "id_personal": user.id_personal,
        "employee_number": user.employee_number or "",
        "name": user.get_full_name().strip() or user.email or "",
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "email": user.email or "",
        "phone": user.phone or "",
        "location": str(department) if department else "",
        "position": user.position or "",
        "employment_type": employment_type or "",
        "status": "Activo" if user.is_active else "Inactivo",
        "username": user.username or "",
        "is_active": user.is_active,
        "photo_url": _build_employee_photo_url(user.employee_number or ""),
    }


def resolve_institutional_identity(*, id_personal=None, email=None, local_user=None):
    try:
        if id_personal is not None:
            try:
                employee = get_directory_employee_by_id_personal(id_personal)
            except DirectoryDatabaseError:
                employee = None
            if employee:
                return _enrich_with_organizational_unit(
                    _normalize_rrhh_employee(employee)
                )

        normalized_email = email.strip() if isinstance(email, str) else ""
        if normalized_email:
            try:
                employees = search_directory_employees(
                    normalized_email,
                    limit=20,
                )
            except DirectoryDatabaseError:
                employees = []

            normalized_email_key = normalized_email.casefold()
            for employee in employees or []:
                employee_email = employee.get("Mail") or ""
                if (
                    isinstance(employee_email, str)
                    and employee_email.strip().casefold() == normalized_email_key
                ):
                    return _enrich_with_organizational_unit(
                        _normalize_rrhh_employee(employee)
                    )

            try:
                ad_user = get_ad_user_by_email(normalized_email)
            except ActiveDirectoryError:
                ad_user = None
            if ad_user:
                return _enrich_with_organizational_unit(
                    _normalize_ad_user(ad_user)
                )

        if local_user is not None:
            return _enrich_with_organizational_unit(
                _normalize_local_user(local_user)
            )

        if normalized_email:
            local_user = User.objects.filter(
                email__iexact=normalized_email,
            ).first()
            if local_user:
                return _enrich_with_organizational_unit(
                    _normalize_local_user(local_user)
                )

        return None
    except Exception as exc:
        raise InstitutionalIdentityError(
            "No fue posible resolver la identidad institucional."
        ) from exc


def resolve_identity_for_user(user):
    if user is None:
        raise ValueError("user no puede ser None.")

    return resolve_institutional_identity(
        id_personal=user.id_personal,
        email=user.email,
        local_user=user,
    )


def search_institutional_identities(query="", limit=20):
    if not isinstance(query, str):
        raise ValueError("query debe ser una cadena.")
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= 100
    ):
        raise ValueError("limit debe ser un entero entre 1 y 100.")

    query = query.strip()
    if len(query) < 2:
        return []

    try:
        identities = []
        seen = set()

        def add_identity(identity):
            email = identity.get("email")
            if isinstance(email, str) and email.strip():
                key = f"email:{email.strip().casefold()}"
            elif identity.get("id_personal") is not None:
                key = f"id_personal:{identity['id_personal']}"
            elif identity.get("username"):
                key = f"username:{identity['username'].casefold()}"
            else:
                key = ":".join(
                    (
                        str(identity.get("source") or ""),
                        str(identity.get("name") or ""),
                        str(identity.get("employee_number") or ""),
                    )
                )

            if key not in seen:
                seen.add(key)
                identities.append(identity)

        try:
            rrhh_employees = search_directory_employees(query, limit=limit)
        except DirectoryDatabaseError:
            rrhh_employees = []
        for employee in rrhh_employees or []:
            add_identity(_normalize_rrhh_employee(employee))

        try:
            ad_users = search_ad_users(query, limit=limit)
        except ActiveDirectoryError:
            ad_users = []
        for ad_user in ad_users or []:
            add_identity(_normalize_ad_user(ad_user))

        local_filter = (
            Q(email__icontains=query)
            | Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(employee_number__icontains=query)
        )
        if query.isdecimal():
            local_filter |= Q(id_personal=int(query))

        local_users = User.objects.filter(local_filter).distinct()[:limit]
        for local_user in local_users:
            add_identity(_normalize_local_user(local_user))

        return identities[:limit]
    except Exception as exc:
        raise InstitutionalIdentityError(
            "No fue posible buscar identidades institucionales."
        ) from exc





