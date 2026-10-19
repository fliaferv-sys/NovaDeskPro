"""Pure reconciliation of preloaded records; IP and network labels are not identity."""
from collections import Counter, defaultdict

from django.db.models import Prefetch

from .models import PrintingDevice, PrintingDeviceNetworkDetection
from .network_identity import normalize_mac

STATUSES = ("MATCHED", "IP_CHANGED", "NEW_DEVICE", "AMBIGUOUS", "UNIDENTIFIED", "CONFLICT")


def load_records():
    devices = list(PrintingDevice.objects.all().prefetch_related(Prefetch(
        "network_detections", queryset=PrintingDeviceNetworkDetection.objects.filter(is_current=True),
        to_attr="discovery_detections")))
    return devices, {device.pk: device.discovery_detections for device in devices}


def reconcile_findings(findings, devices, detections):
    serial_index, mac_index, ip_index = defaultdict(set), defaultdict(set), defaultdict(set)
    by_id = {device.pk: device for device in devices}
    for device in devices:
        if device.serial_number:
            serial_index[device.serial_number].add(device.pk)
        if device.is_active and device.ip_address:
            ip_index[device.ip_address].add(device.pk)
        for detection in detections.get(device.pk, []):
            mac = normalize_mac(detection.detected_mac)
            if mac:
                mac_index[mac].add(device.pk)
    serial_counts = Counter(f["serial"] for f in findings if f.get("supported") and f.get("serial"))
    mac_counts = Counter(normalize_mac(f.get("mac")) for f in findings if f.get("supported") and normalize_mac(f.get("mac")))
    rows = []
    for finding in findings:
        row = {**finding, "status": "UNIDENTIFIED", "device_id": "", "photocopier_id": "",
               "novadesk_ip": "", "action": "REVIEW", "reason": "", "network_unique": False}
        rows.append(row)
        if finding.get("error") == "MANUFACTURER_CONFLICT":
            row.update(status="CONFLICT", reason="MANUFACTURER_CONFLICT")
            continue
        if not finding.get("supported"):
            continue
        serial, mac = finding.get("serial", ""), normalize_mac(finding.get("mac"))
        if not serial and not mac:
            continue
        serial_matches = serial_index.get(serial, set()) if serial else set()
        mac_matches = mac_index.get(mac, set()) if mac else set()
        if serial_matches and mac_matches and serial_matches.isdisjoint(mac_matches):
            row.update(status="CONFLICT", reason="SERIAL_MAC_DISAGREE")
            continue
        if (len(serial_matches) > 1 or len(mac_matches) > 1
                or serial and serial_counts[serial] > 1 or mac and mac_counts[mac] > 1):
            row.update(status="AMBIGUOUS", reason="DUPLICATE_IDENTITY")
            continue
        row["network_unique"] = True
        matches = serial_matches or mac_matches
        if not matches:
            row.update(status="CONFLICT" if ip_index.get(finding["ip"]) else "NEW_DEVICE",
                       reason="IP_ALREADY_ASSIGNED" if ip_index.get(finding["ip"]) else "NO_KNOWN_IDENTITY")
            continue
        device = by_id[next(iter(matches))]
        row.update(device_id=str(device.pk), photocopier_id=device.photocopier_id or "", novadesk_ip=device.ip_address or "")
        current = detections.get(device.pk, [])
        known_macs = {normalize_mac(d.detected_mac) for d in current if normalize_mac(d.detected_mac)}
        if (serial and device.serial_number and serial != device.serial_number
                or mac and known_macs and mac not in known_macs):
            row.update(status="CONFLICT", reason="STORED_IDENTITY_DISAGREES")
        elif not device.is_active:
            row.update(status="CONFLICT", reason="INACTIVE_DEVICE")
        elif len(current) > 1:
            row.update(status="AMBIGUOUS", reason="MULTIPLE_CURRENT_DETECTIONS")
        elif ip_index.get(finding["ip"], set()) - {device.pk}:
            row.update(status="CONFLICT", reason="IP_ALREADY_ASSIGNED")
        elif not finding.get("scan_complete"):
            row.update(status="CONFLICT", reason="INCOMPLETE_SCAN")
        elif device.ip_address == finding["ip"]:
            row.update(status="MATCHED", action="NONE")
        else:
            row.update(status="IP_CHANGED", action="UPDATE_EXISTING_IP")
    # Different strong identities must not propose distinct IPs for one record.
    target_counts = Counter(row["device_id"] for row in rows if row["status"] in ("MATCHED", "IP_CHANGED"))
    for row in rows:
        if row["status"] in ("MATCHED", "IP_CHANGED") and target_counts[row["device_id"]] > 1:
            row.update(status="AMBIGUOUS", action="REVIEW", reason="MULTIPLE_FINDINGS_FOR_DEVICE", network_unique=False)
    return rows
