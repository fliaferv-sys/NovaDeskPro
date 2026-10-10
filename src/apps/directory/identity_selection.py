"""Shared eligibility and minimal institutional references, independent of modules."""
import re
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

SOURCES = {"RRHH", "ACTIVE_DIRECTORY", "TERCERIZADOS", "LOCAL"}
TECHNICAL_NAMES = {"admin", "administrator", "administrador", "soporte", "informatica", "helpdesk", "noreply", "impresora", "scanner", "mesadeayuda"}


def institutional_selection(identity):
    email = str(identity.get("email") or "").strip()
    try:
        validate_email(email)
    except ValidationError:
        return False, "La identidad no tiene correo institucional valido."
    if email.rsplit("@", 1)[-1].casefold() != settings.DIRECTORY_AD_DOMAIN.casefold():
        return False, "El correo no pertenece al dominio institucional permitido."
    if identity.get("source") not in SOURCES or not identity.get("_locator"):
        return False, "La identidad no pertenece a una fuente permitida."
    if identity.get("is_active") is False:
        return False, "La identidad institucional esta inactiva."
    username = str(identity.get("username") or email.split("@", 1)[0]).casefold()
    if (identity.get("is_person") is False or identity.get("is_technical") or identity.get("is_shared")
        or username in TECHNICAL_NAMES or email.split("@", 1)[0].casefold() in TECHNICAL_NAMES or re.match(r"^(?:(?:svc|service|shared|servicio|compartida)[_.-]|(?:impresora|printer|scanner)[0-9_.-])", username)):
        return False, "La identidad corresponde a una cuenta tecnica o compartida."
    if identity.get("source") == "ACTIVE_DIRECTORY" and not (identity.get("first_name") and identity.get("last_name")):
        return False, "La cuenta AD no tiene datos suficientes para identificar una persona."
    name = str(identity.get("full_name") or identity.get("name") or "").strip()
    if len(name.split()) < 2 or "@" in name:
        return False, "No hay evidencia suficiente de una persona institucional."
    return True, ""


def institutional_snapshot(identity):
    locators = identity.get("_linked") or [identity["_locator"]]
    locator = next((item for item in locators if item.get("source") == "RRHH"), locators[0])
    return {"locator": locator, "source": locator["source"],
            "name": identity.get("full_name") or identity.get("name") or "",
            "email": identity.get("email") or "", "username": identity.get("username") or ""}


def resolve_persisted_identity(snapshot):
    """Re-resolve a stored source and safely discover a later local link, no writes."""
    from .identity_services import resolve_common_identity, search_common_identities
    identity = resolve_common_identity(snapshot["locator"])
    eligible, reason = institutional_selection(identity)
    if not eligible:
        raise ValidationError(reason)
    result = search_common_identities(identity["email"], "email", exact=True)
    if not result["incomplete"]:
        matches = [item for item in result["identities"] if snapshot["locator"] in
                   [item.get("_locator"), *(item.get("_linked") or [])]]
        if len(matches) == 1:
            return matches[0]
    return identity
