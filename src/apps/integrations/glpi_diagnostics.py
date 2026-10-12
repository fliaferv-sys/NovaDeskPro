"""Read-only comparisons. No save, update, create or inferred associations."""
from collections import Counter, defaultdict
import ipaddress

from django.db import connection

from apps.directory.identity_services import search_common_identities
from apps.directory.identity_selection import institutional_selection
from apps.inventory.models import Asset, OrganizationalLocation
from apps.printing.location_analysis import normalize_dependency
from apps.printing.models import PrintingDevice

SERIAL_STATES = ("COINCIDE", "SOLO_GLPI", "SOLO_NOVADESK", "DUPLICADO_GLPI", "DUPLICADO_NOVADESK", "REVISAR")


def serial_key(value):
    return str(value or "").strip().upper()


def serial_comparison(glpi, local):
    groups = [defaultdict(list), defaultdict(list)]
    output = []
    for index, rows in enumerate((glpi, local)):
        for row in rows:
            serial = serial_key(row.get("serial"))
            if serial:
                groups[index][serial].append(row)
            else:
                output.append({"estado": "REVISAR", "motivo": "Sin serie; no se compara por IP o nombre",
                    "glpi": [row] if index == 0 else [], "novadesk": [row] if index == 1 else []})
    for serial in sorted(set(groups[0]) | set(groups[1])):
        left, right = groups[0][serial], groups[1][serial]
        statuses = []
        if len(left) > 1:
            statuses.append("DUPLICADO_GLPI")
        if len(right) > 1:
            statuses.append("DUPLICADO_NOVADESK")
        if not statuses:
            statuses = ["COINCIDE" if left and right else "SOLO_GLPI" if left else "SOLO_NOVADESK"]
        for status in statuses:
            output.append({"estado": status, "serial": serial, "glpi": left, "novadesk": right})
    return output


def local_printers():
    # Do not require unrelated pending schema changes for a read-only diagnostic.
    with connection.cursor() as cursor:
        columns = {column.name for column in connection.introspection.get_table_description(cursor, PrintingDevice._meta.db_table)}
    fields = ["id", "serial_number", "photocopier_id", "ip_address",
              "organizational_location__name", "organizational_location__branch__name",
              "responsible_user__first_name", "responsible_user__last_name", "responsible_user__username"]
    if "responsible_identity" in columns:
        fields.append("responsible_identity")
    result = []
    for row in PrintingDevice.objects.order_by("pk").values(*fields):
        snapshot = row.get("responsible_identity") or {}
        name = " ".join(filter(None, [row["responsible_user__first_name"], row["responsible_user__last_name"]]))
        location = " - ".join(filter(None, [row["organizational_location__branch__name"], row["organizational_location__name"]]))
        result.append({"id": str(row["id"]), "serial": row["serial_number"], "photocopier_id": row["photocopier_id"],
            "ip": row["ip_address"], "location": location,
            "responsable": snapshot.get("name") or name or row["responsible_user__username"] or ""})
    return result


def printer_diagnostics(printers, locations, network_ips=None):
    location_names = {str(row["id"]): row.get("completename") or row.get("name") or "" for row in locations}
    rows = []
    for printer in printers:
        location = printer.get("locations_id")
        rows.append({"id": printer["id"], "serial": printer.get("serial"), "name": printer.get("name"),
            "model": printer.get("printermodels_id"), "location": location_names.get(str(location), location or ""),
            "contact": printer.get("contact") or "", "ips_detectadas": (network_ips or {}).get(str(printer["id"]), [])})
    result = serial_comparison(rows, local_printers())
    for item in result:
        if item["estado"] != "COINCIDE":
            continue
        glpi, local = item["glpi"][0], item["novadesk"][0]
        differences = []
        if normalize_dependency(glpi["location"]) != normalize_dependency(local["location"]):
            differences.append("UBICACION_DIFERENTE / INFORMACION PARCIAL: REVISAR")
        if network_ips is None:
            differences.append("IP_GLPI_NO_CONSULTADA")
        elif glpi["ips_detectadas"]:
            if local["ip"] and set(glpi["ips_detectadas"]) != {local["ip"]}:
                differences.append("IP_DIFERENTE (dato detectado; no se sobrescribe)")
            elif not local["ip"]:
                differences.append("IP_NOVADESK_VACIA: REVISAR")
        else:
            differences.append("SIN_IP_DETECTADA_GLPI")
        item["diferencias"] = differences
    return result


def computer_diagnostics(computers):
    # Serial is the only matching key in phase 1; tag/hostname are evidence only.
    local = [{"id": str(row["id"]), "serial": row["serial_number"], "inventory": row["internal_code"],
              "patrimonial_code": row["patrimonial_code"], "hostname": row["hostname"]}
             for row in Asset.objects.filter(asset_type__in=[Asset.AssetType.DESKTOP, Asset.AssetType.LAPTOP]).order_by("pk").values(
                 "id", "serial_number", "internal_code", "patrimonial_code", "hostname")]
    glpi = [{"id": row["id"], "serial": row.get("serial"), "name": row.get("name"),
             "inventory": row.get("otherserial")} for row in computers]
    return serial_comparison(glpi, local)


def user_diagnostics(users):
    results, cache = [], {}
    for user in users:
        emails = sorted({str(email).strip() for email in user.get("emails", []) if email})
        username = str(user.get("name") or "").strip()
        terms = [(email, "email") for email in emails] or ([(username, "username")] if username else [])
        candidates, incomplete = {}, False
        for term, field in terms:
            if not 2 <= len(term) <= 254:
                incomplete = True
                continue
            key = (term.casefold(), field)
            if key not in cache:
                cache[key] = search_common_identities(term, field, exact=True)
            answer = cache[key]
            incomplete |= answer["incomplete"]
            for candidate in answer["identities"]:
                locator = repr(candidate.get("_locator"))
                candidates[locator] = candidate
        values = list(candidates.values())
        if incomplete or len(values) > 1:
            status, reason = "REVISAR", "Busqueda incompleta o identidades ambiguas; no se vincula"
        elif len(values) == 1:
            allowed, reason = institutional_selection(values[0])
            status = "COINCIDE" if allowed else "REVISAR"
        else:
            status, reason = "NO_ENCONTRADO", "Sin coincidencia exacta por correo/username"
            full_name = " ".join(filter(None, [user.get("firstname"), user.get("realname")])).strip()
            if 2 <= len(full_name) <= 254:
                key = (full_name.casefold(), "name")
                if key not in cache:
                    cache[key] = search_common_identities(full_name, "name", exact=True)
                if cache[key]["identities"] or cache[key]["incomplete"]:
                    status, reason = "REVISAR", "Solo nombre o fuente incompleta; no establece correspondencia segura"
        results.append({"estado": status, "glpi_id": user["id"], "username": username, "emails": emails,
            "motivo": reason, "candidatos": len(values),
            "identidad": {key: values[0].get(key) for key in ("full_name", "email", "source", "local_user_id")} if status == "COINCIDE" else None})
    return results


def location_diagnostics(locations):
    existing = list(OrganizationalLocation.objects.select_related("branch").order_by("pk"))
    results = []
    for location in locations:
        text = location.get("completename") or location.get("name") or ""
        exact = [row for row in existing if normalize_dependency(text) == normalize_dependency(f"{row.branch.name} - {row.name}")]
        results.append({"estado": "PROPUESTA_REVISAR", "glpi_id": location["id"], "glpi_location": text,
            "motivo": "No hay equivalencia de sede GLPI aprobada; no se asocia automaticamente",
            "candidatos_textuales": [f"{row.branch.name} - {row.name}" for row in exact]})
    return results


def printer_network_ips(ports, names, addresses):
    printers = {str(row["id"]): str(row["items_id"]) for row in ports
                if row.get("itemtype") == "Printer" and row.get("items_id") is not None}
    chains = {str(row["id"]): printers[str(row["items_id"])] for row in names
              if row.get("itemtype") == "NetworkPort" and str(row.get("items_id")) in printers}
    ips = defaultdict(set)
    for row in addresses:
        if row.get("itemtype") != "NetworkName" or str(row.get("items_id")) not in chains:
            continue
        try:
            address = ipaddress.ip_address(str(row.get("name") or ""))
        except ValueError:
            continue
        ips[chains[str(row["items_id"])]].add(str(address))
    return {key: sorted(value) for key, value in ips.items()}


def counts(rows):
    return dict(Counter(row["estado"] for row in rows))
