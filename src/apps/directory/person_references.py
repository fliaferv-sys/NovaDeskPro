"""Shared person references for custody; accounts remain authorization principals."""
from django.core.exceptions import ValidationError

from .identity_selection import institutional_snapshot


def person_snapshot(identity):
    snapshot = institutional_snapshot(identity)
    if identity.get("local_user_id"):
        snapshot["local_user_id"] = identity["local_user_id"]
    return snapshot


def validate_person_reference(snapshot, user_id=None):
    if not snapshot:
        return
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("locator"), dict):
        raise ValidationError("Referencia institucional inválida.")
    locator = snapshot["locator"]
    source = locator.get("source")
    valid = (source == "RRHH" and str(locator.get("id") or "").isdecimal()) or (
        source == "ACTIVE_DIRECTORY" and bool(locator.get("email") and locator.get("username"))) or (
        source == "TERCERIZADOS" and bool(locator.get("key"))) or (
        source == "LOCAL" and bool(locator.get("id")))
    if not valid or not snapshot.get("name") or not snapshot.get("email"):
        raise ValidationError("Referencia institucional incompleta.")
    linked = snapshot.get("local_user_id") or (locator.get("id") if source == "LOCAL" else None)
    if user_id and linked and str(user_id) != str(linked):
        raise ValidationError("La persona institucional y la cuenta local no coinciden.")


def person_name(snapshot, user=None):
    return (snapshot or {}).get("name") or (user.get_full_name().strip() or user.username if user else "")


def enrich_person_records(records, snapshot_field, user_field):
    """One external directory load for a list; failures retain historical references."""
    from .identity_services import get_institutional_directory
    from apps.accounts.institutional_sync import phone_key, text_key
    records = list(records)
    if not records:
        return records
    try:
        identities = get_institutional_directory()
    except Exception:
        identities = []
    by_id, by_account = {}, {}
    for identity in identities:
        if identity.get("is_active") is not True:
            continue
        if identity.get("id_personal") is not None:
            by_id.setdefault(str(identity["id_personal"]), []).append(identity)
        key = (str(identity.get("email") or "").strip().casefold(),
               str(identity.get("username") or "").strip().casefold())
        by_account.setdefault(key, []).append(identity)
    for record in records:
        snapshot = getattr(record, snapshot_field) or {}
        user = getattr(record, user_field)
        locator = snapshot.get("locator") or {}
        identity_id = locator.get("id") if locator.get("source") == "RRHH" else (user.id_personal if user else None)
        if identity_id is not None:
            matches = by_id.get(str(identity_id), [])
        else:
            matches = by_account.get((str(snapshot.get("email") or (user.email if user else "")).strip().casefold(),
                                      str(snapshot.get("username") or (user.username if user else "")).strip().casefold()), [])
        identity = matches[0] if len(matches) == 1 else {}
        if user and snapshot and user.id_personal is not None and identity_id is not None and str(user.id_personal) != str(identity_id):
            user = None
            identity = {}
        expected_email = snapshot.get("email") or (user.email if user else "")
        if identity and expected_email and identity.get("email") and text_key(expected_email) != text_key(identity["email"]):
            identity = {}
        if identity and user and any(getattr(user, field) and identity.get(field) and normalize(getattr(user, field)) != normalize(identity[field])
                                    for field, normalize in (("employee_number", text_key), ("phone", phone_key))):
            identity = {}
        unit = identity.get("organizational_unit") or {}
        record.person_identity = identity
        record.person_unit = (str(user.organizational_unit) if user and user.organizational_unit_id else "") or unit.get("name") or ""
        record.person_branch = user.branch.name if user and user.branch_id else ""
    return records
