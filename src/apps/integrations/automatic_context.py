"""Requester-only discovery using existing resolver and explicit local custody."""
from apps.inventory.models import Asset
from .technical_context import resolve_technical_context, public_user
from .glpi_diagnostics import serial_key


def resolve_automatic_context(requester):
    context = resolve_technical_context(requester=requester)
    owned = list(Asset.objects.filter(assigned_user=requester).select_related("assigned_user__department", "assigned_user__organizational_unit", "assigned_user__branch").order_by("pk"))
    devices = context["devices"]
    for device in devices:
        # Contact evidence remains probable. Only an explicit unique local link
        # permits automatic association; never promote network confidence.
        matches = device.get("novadesk_assets", [])
        device["auto_eligible"] = len(matches) == 1 and matches[0].get("can_select") is True
        device["association_confidence"] = "CONFIRMADA" if device["auto_eligible"] else "PROBABLE"
    for asset in owned:
        existing = [d for d in devices if serial_key(asset.serial_number) and serial_key(d["data"].get("serial")) == serial_key(asset.serial_number)]
        if existing:
            if len(existing) > 1:
                for device in existing:
                    device["auto_eligible"] = False
            continue
        devices.append({"data": {"type": asset.asset_type, "name": asset.hostname or asset.internal_code,
                                 "hostname": asset.hostname or None, "serial": asset.serial_number or None},
                        "ip": asset.current_ip or None, "glpi_id": None,
                        "confidence": "PROBABLE", "association_confidence": "CONFIRMADA", "auto_eligible": True,
                        "provenance": {"name": "NovaDesk Asset", "ip": "NovaDesk Asset.current_ip", "serial": "NovaDesk Asset"},
                        "detected_user": {"candidates": [], "confidence": "DESCONOCIDA", "incomplete": False},
                        "novadesk_assets": [{"id": str(asset.pk), "code": asset.internal_code,
                            "responsible": public_user(requester), "can_select": True, "confidence": "CONFIRMADA", "source": "NovaDesk Asset"}]})
    context["automatic"] = True
    return context


def automatic_selection(context):
    devices = context.get("devices", [])
    if len(devices) != 1 or not devices[0].get("auto_eligible"):
        return None
    person = context.get("person") or {}
    detected = devices[0].get("detected_user") or {}
    return {"device": 0, "requester": 0 if len(person.get("candidates", [])) == 1 and not person.get("incomplete") else None,
            "detected": 0 if len(detected.get("candidates", [])) == 1 and not detected.get("incomplete") else None,
            "asset": 0}
