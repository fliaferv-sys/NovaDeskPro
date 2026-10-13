"""Central read-only technical context. Requester/detected user/custodian stay distinct."""
from django.db.models.functions import Trim, Upper

from apps.inventory.models import Asset
from .glpi_client import GLPIClient, GLPIConfig
from .glpi_diagnostics import serial_key
from .ip_lookup import (
    lookup_ip, institutional_people, contact_search_terms, active_row,
    field, redact_result,
)


PERSON_KEYS = {"Nombre completo": "full_name", "Username": "username", "Correo": "email", "Telefono": "phone",
               "Cargo": "position", "Dependencia": "department", "Ubicacion institucional": "location"}
DEVICE_KEYS = {"Tipo": "type", "Nombre del equipo": "name", "Hostname / nombre de red": "hostname",
               "MAC": "mac", "Serie": "serial", "Ubicacion GLPI": "location", "Usuario GLPI": "glpi_user",
               "Contacto GLPI": "contact", "Ultima modificacion": "last_modified"}


def normalized_fields(fields, keys, extra=None):
    values, provenance = {key: None for key in keys.values()}, {}
    for item in fields:
        key = keys.get(item["label"])
        if key:
            values[key] = None if item["value"] == "No disponible" else item["value"]
            provenance[key] = item["source"]
    values.update(extra or {})
    return {"data": values, "provenance": provenance}


def normalized_people(result):
    return {"confidence": result["confidence"], "incomplete": result["incomplete"],
            "candidates": [{**normalized_fields(item["fields"], PERSON_KEYS, item.get("context_data")), "confidence": item["confidence"],
                            "sources": item.get("sources", [])} for item in result["candidates"]]}


def public_user(user):
    return {"full_name": user.get_full_name().strip() or user.username, "username": user.username,
            "email": user.email or None, "phone": user.phone or None, "position": user.position or None}


def local_assets(serial, requester, index=None):
    if not serial_key(serial):
        return []
    assets = index.get(serial_key(serial), []) if index is not None else list(Asset.objects.annotate(context_serial=Upper(Trim("serial_number"))).filter(
        context_serial=serial_key(serial)).select_related("assigned_user").order_by("pk"))
    return [{"id": str(asset.pk), "code": asset.internal_code, "source": "NovaDesk Asset",
             "confidence": "CONFIRMADA" if len(assets) == 1 else "DESCONOCIDA",
             "can_select": bool(requester and asset.assigned_user_id == requester.pk),
             "responsible": public_user(asset.assigned_user) if asset.assigned_user_id else None} for asset in assets]


def resolve_technical_context(*, requester=None, username=None, email=None, identity=None,
                              ip=None, hostname=None, asset=None, client_factory=None):
    """Identity input supplies search keys only; never trust a posted person snapshot."""
    requested = {"ip": ip, "hostname": hostname}
    if identity:
        username = username or identity.get("username")
        email = email or identity.get("email")
    explicit_person = bool(username or email or identity)
    person_username = username or (requester.username if requester and not explicit_person else None)
    person_email = email or (requester.email if requester and not explicit_person else None)
    result = {"requester": public_user(requester) if requester else None, "person": None,
              "devices": [], "warnings": [], "input": requested}
    people_cache = {}
    def people(user, emails, contact):
        key = (repr(user), tuple(emails), contact)
        if key not in people_cache:
            people_cache[key] = institutional_people(user, emails, contact, context_fields=True)
        return people_cache[key]
    try:
        result["person"] = normalized_people(people(
            {"name": person_username} if person_username else None, [person_email] if person_email else [], ""))
    except Exception:
        result["person"] = {"confidence": "DESCONOCIDA", "incomplete": True, "candidates": []}
        result["warnings"].append("Directorio Institucional no disponible.")
    if not ip and asset:
        ip = asset.current_ip
    candidates = []
    if ip:
        try:
            client = client_factory() if client_factory else GLPIClient(GLPIConfig.from_env())
            lookup = lookup_ip(ip, client_factory=lambda: client)
            candidates = lookup["candidates"]
            result["warnings"].extend(lookup["warnings"])
            result["input"]["ip"] = lookup["ip"]
        except Exception:
            result["warnings"].append("GLPI no disponible; sin equipo confirmado.")
    elif hostname or person_username or person_email:
        try:
            client = client_factory() if client_factory else GLPIClient(GLPIConfig.from_env())
            terms = set()
            for value in (person_username, person_email):
                if value:
                    terms.update(contact_search_terms(value))
            with client:
                for kind in (("Computer",) if hostname else ("Computer", "Printer")):
                    query = hostname or person_username or person_email
                    rows = client.items(kind, filters={"name" if hostname else "contact": query})
                    for row in rows:
                        if not active_row(row):
                            continue
                        if hostname:
                            if str(row.get("name") or "").strip().casefold() != hostname.strip().casefold():
                                continue
                        elif not { (q.casefold(), f) for q, f in contact_search_terms(str(row.get("contact") or "")) } & {(q.casefold(), f) for q, f in terms}:
                            continue
                        candidates.append({"device_id": str(row["id"]), "device_type": kind, "network_confidence": "PROBABLE",
                            "people": people(None, [], row.get("contact")), "fields": [
                                field("Tipo", kind, "GLPI"), field("Nombre del equipo", row.get("name"), f"GLPI {kind}.name"),
                                field("Serie", row.get("serial"), f"GLPI {kind}.serial"),
                                field("Contacto GLPI", row.get("contact"), f"GLPI {kind}.contact"),
                            ]})
            candidates = redact_result(candidates, client)
        except Exception:
            result["warnings"].append("GLPI no disponible; sin equipo confirmado.")
            candidates = []
    asset_index = {}
    serials = {serial_key(normalized_fields(candidate["fields"], DEVICE_KEYS)["data"].get("serial")) for candidate in candidates}
    serials.discard("")
    if serials:
        for matched_asset in Asset.objects.annotate(context_serial=Upper(Trim("serial_number"))).filter(
            context_serial__in=serials).select_related("assigned_user").order_by("pk"):
            asset_index.setdefault(matched_asset.context_serial, []).append(matched_asset)
    for candidate in candidates:
        device = normalized_fields(candidate["fields"], DEVICE_KEYS)
        if result["input"].get("ip"):
            device["provenance"]["ip"] = "GLPI IPAddress.name (registro de inventario)"
        matches = local_assets(device["data"].get("serial"), requester, asset_index)
        result["devices"].append({**device, "glpi_id": candidate["device_id"], "ip": result["input"].get("ip"),
            "confidence": candidate["network_confidence"], "detected_user": normalized_people(candidate["people"]),
            "novadesk_assets": matches})
    if asset and not result["devices"]:
        result["devices"].append({"data": {"type": asset.asset_type, "name": asset.hostname or None, "hostname": asset.hostname or None,
            "serial": asset.serial_number or None, "mac": None}, "provenance": {"name": "NovaDesk Asset", "serial": "NovaDesk Asset", "ip": "NovaDesk Asset.current_ip"},
            "glpi_id": None, "ip": asset.current_ip, "confidence": "PROBABLE", "detected_user": {"confidence": "DESCONOCIDA", "incomplete": False, "candidates": []},
            "novadesk_assets": local_assets(asset.serial_number, requester)})
    return redact_result(result, client) if "client" in locals() else result
