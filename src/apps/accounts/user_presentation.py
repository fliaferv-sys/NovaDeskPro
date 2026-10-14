"""Read-only presentation of local accounts with safely matched directory data."""
from collections import defaultdict

from apps.directory.identity_services import (
    get_institutional_directory, get_user_photo_url,
)
from apps.directory.services import DirectoryDatabaseError
from django.conf import settings
from .institutional_sync import phone_key, text_key


def enrich_user_list(users):
    # One consolidated source load, never one RRHH/AD lookup per account.
    try:
        identities = get_institutional_directory()
    except DirectoryDatabaseError:
        identities = []
    by_id, by_email, by_employee = defaultdict(list), defaultdict(list), defaultdict(list)
    for identity in identities:
        if identity.get("id_personal") is not None:
            by_id[str(identity["id_personal"])].append(identity)
        email = str(identity.get("email") or "").strip().casefold()
        if email:
            by_email[email].append(identity)
        if identity.get("employee_number"):
            by_employee[str(identity["employee_number"]).strip()].append(identity)
    for user in users:
        email = (user.email or "").strip().casefold()
        matches = by_id.get(str(user.id_personal), []) if user.id_personal is not None else []
        if not matches and user.employee_number:
            matches = by_employee.get(str(user.employee_number).strip(), [])
        account_safe = (email.endswith("@" + settings.DIRECTORY_AD_DOMAIN.casefold())
                        and user.username.strip().casefold() == email.split("@", 1)[0])
        if not matches and account_safe and user.id_personal is None and not user.employee_number:
            matches = by_email.get(email, [])
        identity = matches[0] if len(matches) == 1 else {}
        if identity and (
            identity.get("is_active") is not True
            or (identity.get("username") and identity["username"].strip().casefold() != user.username.strip().casefold())
            or (user.employee_number and identity.get("employee_number") and text_key(user.employee_number) != text_key(identity["employee_number"]))
            or (user.phone and identity.get("phone") and phone_key(user.phone) != phone_key(identity["phone"]))
            or
            (identity.get("email") and email and identity["email"].strip().casefold() != email)
            or (user.id_personal is not None and identity.get("id_personal") is not None
                and str(user.id_personal) != str(identity["id_personal"]))
        ):
            identity = {}
        for field in ("phone", "employee_number", "position"):
            setattr(user, "display_" + field, getattr(user, field) or identity.get(field) or "")
        unit = identity.get("organizational_unit") or {}
        user.display_unit = user.organizational_unit or (unit.get("name", "") if isinstance(unit, dict) else "")
        user.display_department = user.department or ""
        user.display_location = str(identity.get("location") or "").strip()
        user.display_branch = user.branch or ""
        user.display_name = user.get_full_name().strip() or identity.get("name") or user.username
        user.display_employment_type = identity.get("employment_type") or user.get_employment_type_display()
        user.institutional_source = identity.get("source_label") or identity.get("source") or ""
        user.institutional_photo_url = get_user_photo_url(user, identity=identity)
    return users
