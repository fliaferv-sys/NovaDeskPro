"""Shared conservative validation for Excel-origin photocopier identifiers."""
from collections import defaultdict
import re


ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_/-]{0,49}\Z")
INVALID_MARKERS = {"s/n", "n/a", "na", "n-a", "none", "null", "pendiente", "sin-id", "sin_id", "sin-dato", "sin_dato"}


def origin_id(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("ID origen debe ser texto o entero; no se convierten decimales ni otros tipos")
    value = str(value).strip()
    if not ID_PATTERN.fullmatch(value):
        raise ValueError("ID origen invalido: requiere 1-50 caracteres ASCII, letras/digitos, guion, guion bajo o barra /; sin espacios internos")
    if value.casefold() in INVALID_MARKERS or (value.isdecimal() and not int(value)):
        raise ValueError("ID origen contiene un marcador sin identificacion valida")
    return value


def id_key(value):
    return str(value or "").strip().casefold()


def existing_id_owners(devices):
    owners = defaultdict(set)
    for device in devices:
        if device.photocopier_id:
            owners[id_key(device.photocopier_id)].add(device.pk)
    return owners


def resolve_origin_id(value, current_id, device_pk, owners, counts):
    try:
        candidate = origin_id(value)
    except ValueError as exc:
        return "REVISAR", None, str(exc)
    if candidate is None:
        return "SIN CAMBIOS", None, "ID origen ausente o vacio; no se usa N° origen"
    key = id_key(candidate)
    if counts[key] > 1:
        return "REVISAR", None, "ID origen duplicado en el lote; se revisan todos los registros que lo reclaman"
    if owners.get(key, set()) - {device_pk}:
        return "REVISAR", None, "ID origen ya usado por otra impresora"
    if current_id:
        if current_id == candidate:
            return "SIN CAMBIOS", None, "ID ya coincidente"
        return "REVISAR", None, "photocopier_id existente distinto de ID origen; no se sobrescribe"
    return "ACTUALIZADO", candidate, "ID origen valido y libre"
