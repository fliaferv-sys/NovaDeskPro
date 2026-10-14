"""Read-only presentation of local accounts with safely matched directory data."""
from apps.directory.identity_services import (
    resolve_identities_for_users, get_user_photo_url, SOURCE_LOCAL,
)


def enrich_user_list(users):
    users = list(users)
    identities = resolve_identities_for_users(users)
    for user in users:
        identity = identities.get(user.pk) or {}
        if identity.get("source") == SOURCE_LOCAL:
            identity = {}
        for field in ("phone", "employee_number", "position"):
            setattr(user, "display_" + field, getattr(user, field) or identity.get(field) or "")
        unit = identity.get("organizational_unit") or {}
        user.display_unit = user.organizational_unit or (unit.get("name", "") if isinstance(unit, dict) else "")
        user.display_department = user.department or ""
        location = str(identity.get("location") or "")
        user.display_location = location if location.strip() else ""
        user.display_branch = user.branch or ""
        user.display_name = user.get_full_name().strip() or identity.get("name") or user.username
        user.display_employment_type = identity.get("employment_type") or user.get_employment_type_display()
        user.institutional_source = identity.get("source_label") or identity.get("source") or ""
        user.institutional_photo_url = get_user_photo_url(user, identity=identity)
    return users
