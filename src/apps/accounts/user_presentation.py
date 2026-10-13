"""Read-only presentation of local accounts with safely matched directory data."""
from collections import defaultdict

from apps.directory.identity_services import (
    get_institutional_directory, get_user_photo_url,
)
from apps.directory.services import DirectoryDatabaseError


def enrich_user_list(users):
    # One consolidated source load, never one RRHH/AD lookup per account.
    try:
        identities = get_institutional_directory()
    except DirectoryDatabaseError:
        identities = []
    by_id, by_email = defaultdict(list), defaultdict(list)
    for identity in identities:
        if identity.get("id_personal") is not None:
            by_id[str(identity["id_personal"])].append(identity)
        email = str(identity.get("email") or "").strip().casefold()
        if email:
            by_email[email].append(identity)
    for user in users:
        email = (user.email or "").strip().casefold()
        matches = by_id.get(str(user.id_personal), []) if user.id_personal is not None else []
        if not matches:
            matches = by_email.get(email, [])
        identity = matches[0] if len(matches) == 1 else {}
        if identity and (
            (identity.get("email") and email and identity["email"].strip().casefold() != email)
            or (user.id_personal is not None and identity.get("id_personal") is not None
                and str(user.id_personal) != str(identity["id_personal"]))
        ):
            identity = {}
        for field in ("phone", "employee_number", "position"):
            setattr(user, "display_" + field, getattr(user, field) or identity.get(field) or "")
        unit = identity.get("organizational_unit") or {}
        user.display_unit = user.organizational_unit or (unit.get("name", "") if isinstance(unit, dict) else "")
        user.display_location = user.department or identity.get("location") or ""
        user.institutional_source = identity.get("source_label") or identity.get("source") or ""
        user.institutional_photo_url = get_user_photo_url(user, identity=identity)
    return users
