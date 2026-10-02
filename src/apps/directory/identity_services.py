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
    search_directory_employees,
)


class InstitutionalIdentityError(Exception):
    pass


SOURCE_RRHH = "RRHH"
SOURCE_ACTIVE_DIRECTORY = "ACTIVE_DIRECTORY"
SOURCE_LOCAL = "LOCAL"


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
    }


def _normalize_ad_user(user):
    is_active = bool(user.get("is_active", False))
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
        "employment_type": "",
        "status": "Activo" if is_active else "Inactivo",
        "username": user.get("username") or "",
        "is_active": is_active,
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
    }


def resolve_institutional_identity(*, id_personal=None, email=None, local_user=None):
    try:
        if id_personal is not None:
            try:
                employee = get_directory_employee_by_id_personal(id_personal)
            except DirectoryDatabaseError:
                employee = None
            if employee:
                return _normalize_rrhh_employee(employee)

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
                    return _normalize_rrhh_employee(employee)

            try:
                ad_user = get_ad_user_by_email(normalized_email)
            except ActiveDirectoryError:
                ad_user = None
            if ad_user:
                return _normalize_ad_user(ad_user)

        if local_user is not None:
            return _normalize_local_user(local_user)

        if normalized_email:
            local_user = User.objects.filter(
                email__iexact=normalized_email,
            ).first()
            if local_user:
                return _normalize_local_user(local_user)

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
