"""Explicit initial enrollment; never updates inventory IPs or printer configuration."""
import ipaddress
import json
from time import monotonic

from django.db import connection, transaction
from django.utils import timezone

from .discovery_adapters import identify_host
from .models import PrintingDevice, PrintingDeviceNetworkDetection
from .network_identity import normalize_mac
from .network_map import authorized_network
from .network_recovery import validate_scan_options
from .recovery_application import detection_snapshot


def load_inventory(*, locked=False):
    devices = PrintingDevice.objects.order_by("pk")
    detections = PrintingDeviceNetworkDetection.objects.order_by("pk")
    if locked:
        devices, detections = devices.select_for_update(), detections.select_for_update()
    return list(devices), list(detections)


def snapshot(devices, detections):
    operational_fields = {
        "connection_status",
        "last_checked_at",
        "last_online_at",
        "last_status_change_at",
        "monitor_method",
        "monitor_error",
        "monitor_evidence",
    }
    return ([{f.attname: getattr(d, f.attname)
              for f in d._meta.concrete_fields
              if f.attname not in operational_fields} for d in devices],
            [detection_snapshot(d) for d in detections])


def physical_identity(finding):
    try:
        entry = authorized_network(finding["subnet"])
        network = ipaddress.ip_network(entry.subnet)
        address = ipaddress.IPv4Address(finding["ip"])
        valid_ip = address in network and address not in (network.network_address, network.broadcast_address)
    except (KeyError, TypeError, ValueError):
        return False
    serial = finding.get("serial")
    return bool(valid_ip and finding.get("supported") and finding.get("identity_verified")
                and finding.get("source") == "LEXMARK_EWS" and finding.get("serial_source") == "SNMPV2C"
                and finding.get("snmp_status") == "CONFIRMED" and not finding.get("snmp_error")
                and finding.get("error") in ("", "DEVICE_INFORMATION_UNAVAILABLE", "DEVICE_INFORMATION_UNSUPPORTED")
                and finding.get("hostname") and normalize_mac(finding.get("mac"))
                and isinstance(serial, str) and 0 < len(serial) <= 150
                and serial == serial.strip() and all(32 <= ord(c) < 127 for c in serial))


def evaluate(finding, devices, detections):
    """Conservative policy over current AND historical detections, without writes."""
    row = {**finding, "status": "BLOCKED", "reason": "INCOMPLETE_IDENTITY", "device_id": "", "photocopier_id": ""}
    if not physical_identity(finding) or not finding.get("scan_complete"):
        return row
    matches = [d for d in devices if d.serial_number == finding["serial"]]
    if len(matches) != 1:
        return {**row, "reason": "SERIAL_NOT_UNIQUE"}
    device = matches[0]
    row.update(device_id=str(device.pk), photocopier_id=device.photocopier_id or "")
    own = [d for d in detections if d.printing_device_id == device.pk]
    current = [d for d in own if d.is_current]
    mac = normalize_mac(finding["mac"])
    reason = ""
    if not device.is_active or not device.supports_network:
        reason = "INACTIVE_OR_NON_NETWORK_DEVICE"
    elif any(normalize_mac(d.detected_mac) == mac and d.printing_device_id != device.pk for d in detections):
        reason = "MAC_ALREADY_ASSOCIATED"
    elif any(d.detected_mac and normalize_mac(d.detected_mac) != mac for d in own):
        reason = "HISTORICAL_IDENTITY_CONFLICT"
    elif any(normalize_mac(d.detected_mac) for d in own):
        reason = "ALREADY_ASSOCIATED"
    elif len(current) > 1:
        reason = "MULTIPLE_CURRENT_DETECTIONS"
    elif current and current[0].detected_ip not in (None, "", finding["ip"], device.ip_address):
        reason = "CURRENT_DETECTION_CONFLICT"
    elif any(d.pk != device.pk and d.ip_address == finding["ip"] for d in devices):
        reason = "IP_ALREADY_ASSIGNED"
    if reason:
        return {**row, "reason": reason, "status": "ALREADY_ASSOCIATED" if reason == "ALREADY_ASSOCIATED" else "BLOCKED"}
    return {**row, "status": "PENDING_INITIAL_BINDING", "reason": "UNIQUE_PHYSICAL_SERIAL"}


def apply_initial_binding(finding, baseline, *, timeout=1):
    """Fresh bracketed EWS/SNMP proof, then locked snapshot/uniqueness checks."""
    _, timeout = validate_scan_options(finding["subnet"], timeout, 1)
    try:
        live = identify_host(finding["ip"], timeout=timeout)
    except Exception:
        return "PHYSICAL_REVALIDATION_FAILED"
    live = {**(live or {}), "subnet": finding["subnet"]}
    if (not physical_identity(live) or live.get("ip") != finding["ip"]
            or live.get("serial") != finding.get("serial")
            or normalize_mac(live.get("mac")) != normalize_mac(finding.get("mac"))):
        return "PHYSICAL_IDENTITY_CHANGED"
    return _record(finding, baseline, verified_at=monotonic())


@transaction.atomic
def _record(finding, baseline, *, verified_at):
    # Row locks alone do not prevent phantom serial/MAC inserts on PostgreSQL.
    # This short write lock covers existing administrative writers as well.
    if connection.vendor == "postgresql":
        tables = ", ".join(connection.ops.quote_name(model._meta.db_table)
                           for model in (PrintingDevice, PrintingDeviceNetworkDetection))
        with connection.cursor() as cursor:
            cursor.execute(f"LOCK TABLE {tables} IN SHARE ROW EXCLUSIVE MODE")
    devices, detections = load_inventory(locked=True)
    if snapshot(devices, detections) != baseline:
        return "INVENTORY_CHANGED"
    row = evaluate(finding, devices, detections)
    if row["status"] != "PENDING_INITIAL_BINDING":
        return row["reason"]
    if monotonic() - verified_at > 10:
        return "PHYSICAL_REVALIDATION_EXPIRED"
    device = next(d for d in devices if str(d.pk) == row["device_id"])
    for detection in detections:
        if detection.printing_device_id == device.pk and detection.is_current:
            detection.is_current = False
            detection.save(update_fields=["is_current"])
    evidence = dict(printing_device_id=str(device.pk), photocopier_id=device.photocopier_id,
                    serial=finding["serial"], mac=normalize_mac(finding["mac"]), ip=finding["ip"],
                    validated_at=timezone.now().isoformat(), source="LEXMARK_EWS+SNMPV2C",
                    result="INITIAL_IDENTITY_CONFIRMED")
    created = PrintingDeviceNetworkDetection.objects.create(printing_device=device, detected_ip=finding["ip"],
        detected_mac=evidence["mac"], detection_source="LEXMARK_EWS_SNMP_INITIAL", is_current=True,
        notes=json.dumps(evidence, ensure_ascii=True))
    # Advance only by our locked write; concurrent changes are never absorbed.
    baseline[1][:] = [detection_snapshot(d) for d in sorted([*detections, created], key=lambda d: str(d.pk))]
    return "BOUND"
