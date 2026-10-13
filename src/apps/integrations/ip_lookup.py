"""On-demand IP -> GLPI relationships -> institutional identity, no writes."""
import ipaddress
import re
from django.conf import settings

from apps.directory.identity_services import search_common_identities, consolidate_institutional_identities
from apps.directory.identity_policies import technical_ip_identity_payload
from .glpi_client import GLPIClient, GLPIConfig, GLPIError
from .glpi_diagnostic_stage import DiagnosticStage


class IPLookupError(Exception):
    pass


def ipv4(value):
    try:
        return str(ipaddress.IPv4Address(str(value).strip()))
    except ValueError:
        raise ValueError("Introduzca una direccion IPv4 valida.") from None


def valid_id(value):
    return str(value) if re.fullmatch(r"[1-9][0-9]*", str(value)) else None


def active_row(row):
    return str(row.get("is_deleted", 0)) != "1" and str(row.get("is_template", 0)) != "1"


def field(label, value, source):
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        value = ""
    return {"label": label, "value": value if value not in (None, "") else "No disponible", "source": source}


def contact_search_terms(value, hint=None):
    """Aliases are lookup terms, never generated identity attributes."""
    text = value.strip()
    kind = hint or ("email" if "@" in text else "name" if " " in text else "username")
    terms = [(text, kind)]
    if text.count("@") == 1:
        account, realm = text.split("@")
        netbios = str(getattr(settings, "DIRECTORY_AD_NETBIOS_DOMAIN", "PETROPAR") or "PETROPAR")
        domain = str(settings.DIRECTORY_AD_DOMAIN).strip()
        if realm.casefold() == netbios.casefold() and re.fullmatch(r"[A-Za-z0-9._-]+", account) and domain:
            terms.extend([(account, "username"), (f"{account}@{domain}", "email")])
    return terms


def institutional_people(user, emails, contact, *, context_fields=False):
    terms = [(email, "email") for email in emails if isinstance(email, str) and email.strip()]
    username = (user or {}).get("name")
    if isinstance(username, str) and username.strip():
        terms.append((username, "username"))
    trusted_terms = {(term.strip().casefold(), kind) for term, kind in terms}
    terms = [variant for term, kind in terms for variant in contact_search_terms(term, kind)]
    if isinstance(contact, str) and contact.strip():
        terms.extend(contact_search_terms(contact))
    terms = list(dict.fromkeys((query.strip() if kind == "name" else query.strip().casefold(), kind) for query, kind in terms))
    candidates, evidence, incomplete = {}, {}, False
    for query, search_field in terms:
        if not 2 <= len(query.strip()) <= 254:
            incomplete = True
            continue
        answer = search_common_identities(query.strip(), search_field, exact=True)
        incomplete |= answer["incomplete"]
        for identity in answer["identities"]:
            key = repr(identity.get("_locator"))
            candidates[key] = identity
            if (query.strip().casefold(), search_field) in trusted_terms:
                evidence.setdefault(key, set()).add(search_field)
            else:
                evidence.setdefault(key, set())
    results = []
    consolidated = consolidate_institutional_identities(list(candidates.values()))
    for identity in consolidated:
        key = repr(identity.get("_locator"))
        status = "DESCONOCIDA" if incomplete or len(consolidated) != 1 or identity.get("is_active") is False or identity.get("is_person") is False or identity.get("is_shared") or identity.get("is_technical") else (
            "CONFIRMADA" if identity.get("_consolidated") or (user and {"email", "username"}.issubset(evidence.get(key, set()))) else "PROBABLE")
        payload = technical_ip_identity_payload(identity)
        if context_fields:
            from apps.directory.identity_policies import technical_context_identity_payload
            payload = technical_context_identity_payload(identity)
        unit = payload.get("organizational_unit")
        if isinstance(unit, dict):
            payload["organizational_unit"] = unit.get("name")
        sources = identity.get("sources") or sorted({locator.get("source", "") for locator in identity.get("_linked", []) if locator.get("source")})
        provenance = "Directorio Institucional: " + (", ".join(sources) if sources else payload.get("source") or "fuente no informada")
        if len(sources) > 1:
            provenance += " (ficha combinada; origen individual no disponible)"
        results.append({"confidence": status, "sources": sources or [payload.get("source")], "fields": [
            field(label, payload.get(name), "NovaDesk: asignacion institucional" if name == "organizational_unit" else provenance)
            for name, label in (("full_name", "Nombre completo"), ("username", "Username"), ("email", "Correo"), ("position", "Cargo"),
                                ("organizational_unit", "Dependencia"), ("phone", "Telefono"), ("location", "Ubicacion institucional"))]})
        if context_fields:
            results[-1]["context_data"] = {key: payload.get(key) for key in ("employee_number", "employment_type")}
    return {"candidates": results, "incomplete": incomplete,
            "confidence": results[0]["confidence"] if len(results) == 1 else "DESCONOCIDA",
            "reason": "Equivalencia de identidad; no confirma responsabilidad del equipo." if results else "No identificado en el Directorio Institucional."}


def redact_result(value, client):
    if isinstance(value, dict):
        return {key: redact_result(item, client) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_result(item, client) for item in value]
    # Redact before normalizing/truncating: a long or spaced secret must not
    # become a visible partial credential that no longer matches the redactor.
    return " ".join(client.redact(value).split())[:250] if isinstance(value, str) else value


def lookup_ip(value, *, client_factory=None):
    address = ipv4(value)  # Reject invalid input before configuration or HTTP.
    stage = DiagnosticStage()
    try:
        client = client_factory() if client_factory else GLPIClient(GLPIConfig.from_env())
        cache = {}
        def get(itemtype, identifier):
            identifier = valid_id(identifier)
            if not identifier:
                return None
            key = (itemtype, identifier)
            if key not in cache:
                stage.set(f"consulta {itemtype}")
                cache[key] = client.item(itemtype, identifier)
            return cache[key]
        candidates, warnings = [], []
        stage.set("apertura de sesion GLPI")
        with client:
            stage.set("busqueda IPAddress")
            addresses = client.items("IPAddress", filters={"name": address})
            seen = set()
            for ip in addresses:
                try:
                    matches = ipv4(ip.get("name", "")) == address
                except ValueError:
                    matches = False
                if not matches or not active_row(ip):
                    continue
                if ip.get("itemtype") != "NetworkName":
                    warnings.append("La IP tiene una relacion distinta de NetworkName; requiere revision.")
                    continue
                name = get("NetworkName", ip.get("items_id"))
                if not name or not active_row(name) or name.get("itemtype") != "NetworkPort":
                    warnings.append("Relacion NetworkName -> NetworkPort incompleta o inactiva.")
                    continue
                port = get("NetworkPort", name.get("items_id"))
                if not port or not active_row(port):
                    warnings.append("Puerto ausente o inactivo.")
                    continue
                key = (str(port.get("id")), str(name.get("id")))
                if key in seen:
                    continue
                seen.add(key)
                device_type = port.get("itemtype")
                device = get(device_type, port.get("items_id")) if device_type in {"Computer", "Printer"} else None
                if device and not active_row(device):
                    warnings.append("El equipo relacionado esta eliminado o es una plantilla.")
                    continue
                device = device or {}
                location = get("Location", device.get("locations_id"))
                state = get("State", device.get("states_id"))
                user = get("User", device.get("users_id"))
                if user and (not active_row(user) or str(user.get("is_active", 1)) == "0"):
                    warnings.append("Usuario GLPI inactivo: no se resuelve identidad automaticamente.")
                    user = None
                    people = {"candidates": [], "incomplete": False, "confidence": "DESCONOCIDA", "reason": "Usuario GLPI inactivo."}
                else:
                    emails = []
                    if user:
                        stage.set("consulta UserEmail")
                        emails = [row.get("email") for row in client.items(f"User/{user['id']}/UserEmail")]
                    stage.set("consulta Directorio Institucional")
                    people = institutional_people(user, emails, device.get("contact"))
                candidates.append({"device_type": device_type or "Desconocido", "device_id": valid_id(port.get("items_id")),
                    "network_confidence": "CONFIRMADA" if device else "DESCONOCIDA",
                    "people": people, "fields": [
                        field("Tipo", device_type, "GLPI NetworkPort.itemtype"),
                        field("Nombre del equipo", device.get("name"), f"GLPI {device_type}.name"),
                        field("Hostname / nombre de red", name.get("name"), "GLPI NetworkName.name (sin inferir FQDN)"),
                        field("MAC", port.get("mac"), "GLPI NetworkPort.mac"),
                        field("Serie", device.get("serial"), f"GLPI {device_type}.serial"),
                        field("Ubicacion GLPI", (location or {}).get("completename") or (location or {}).get("name"), "GLPI Location"),
                        field("Usuario GLPI", (user or {}).get("name"), "GLPI User, relacion users_id del equipo"),
                        field("Contacto GLPI", device.get("contact"), f"GLPI {device_type}.contact (texto libre)"),
                        field("Ultima modificacion", device.get("date_mod"), f"GLPI {device_type}.date_mod; no es fecha de inventario"),
                        field("Estado registrado", (state or {}).get("name"), "GLPI State; no indica disponibilidad en vivo"),
                        field("Ultimo inventario", "No disponible en el contrato estandar GLPI 9.5.5", "Puede depender del plugin de inventario"),
                    ]})
            stage.set("cierre de sesion GLPI")
        result = {"ip": address, "candidates": candidates, "warnings": sorted(set(warnings)),
                  "status": "IDENTIFICADO" if candidates else "NO_IDENTIFICADO"}
        return redact_result(result, client)
    except Exception:
        # Do not expose raw GLPI responses, exceptions, URLs or credentials to users.
        safe = f"Consulta no disponible. Etapa: {stage.name}. No se modificaron datos."
        raise IPLookupError(safe) from None
