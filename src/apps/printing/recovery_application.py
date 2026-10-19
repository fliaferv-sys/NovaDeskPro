"""Transactional application and cooldown for MAC-confirmed IP recovery."""
from dataclasses import dataclass, replace
from datetime import timedelta
import ipaddress

from django.db import transaction
from django.db.models import Prefetch, Q
from django.utils import timezone

from .connectivity import valid_ip, with_connectivity
from .models import PrintingDevice, PrintingDeviceNetworkDetection
from .network_identity import normalize_mac

COOLDOWN = timedelta(minutes=30)


def detection_snapshot(detection):
    return {field.attname: getattr(detection, field.attname) for field in detection._meta.concrete_fields}


@dataclass(frozen=True)
class RecoveryCandidate:
    device_id: object
    old_ip: str
    expected_mac: str
    detection: dict
    attempt_at: object = None

    @classmethod
    def capture(cls, device, detection):
        return cls(device.pk, device.ip_address, normalize_mac(detection.detected_mac), detection_snapshot(detection))


def _current_detection(device, candidate):
    current = list(device.network_detections.select_for_update().filter(is_current=True).order_by("pk")[:2])
    return (current[0] if len(current) == 1 and detection_snapshot(current[0]) == candidate.detection
            and normalize_mac(current[0].detected_mac) == candidate.expected_mac else None)


def offline_candidates(*, limit, now=None):
    now = now or timezone.now()
    devices = with_connectivity(PrintingDevice.objects.filter(
        is_active=True, supports_network=True, connection_status="OFFLINE",
    ).exclude(monitor_error__in=("DUPLICATE_IP", "NO_IP")).filter(
        Q(last_recovery_attempt_at__isnull=True) | Q(last_recovery_attempt_at__lte=now - COOLDOWN)
    )).order_by("pk").prefetch_related(Prefetch(
        "network_detections", queryset=PrintingDeviceNetworkDetection.objects.filter(is_current=True),
        to_attr="recovery_detections"))
    candidates = []
    for device in devices:
        detections = device.recovery_detections
        if (valid_ip(device.ip_address) and not device.monitor_ip_conflict and len(detections) == 1
                and normalize_mac(detections[0].detected_mac)):
            candidates.append((device, RecoveryCandidate.capture(device, detections[0])))
            if len(candidates) >= limit:
                break
    return candidates


@transaction.atomic
def claim_automatic_attempt(candidate, *, now=None):
    """Reserve an attempt across processes; dry-run must never call this."""
    now = now or timezone.now()
    device = PrintingDevice.objects.select_for_update().filter(pk=candidate.device_id).first()
    if (device is None or not device.is_active or not device.supports_network
            or device.connection_status != "OFFLINE" or device.ip_address != candidate.old_ip
            or device.monitor_error in ("DUPLICATE_IP", "NO_IP") or not valid_ip(device.ip_address)
            or device.last_recovery_attempt_at and device.last_recovery_attempt_at > now - COOLDOWN
            or PrintingDevice.objects.filter(ip_address=device.ip_address).exclude(pk=device.pk).exists()
            or _current_detection(device, candidate) is None):
        return None
    device.last_recovery_attempt_at = now
    device.save(update_fields=["last_recovery_attempt_at"])
    return replace(candidate, attempt_at=now)


@transaction.atomic
def apply_recovery(candidate, result, *, subnet, automatic=False):
    unchanged = dict(updated=False, history_created=False, unchanged=False, error="")
    try:
        network = ipaddress.ip_network(subnet, strict=True)
        address = ipaddress.IPv4Address(result.get("found_ip"))
        valid = (network.version == 4 and network.prefixlen == 24 and address in network
                 and address not in (network.network_address, network.broadcast_address)
                 and valid_ip(str(address)) and result.get("status") == "FOUND"
                 and result.get("match_count") == 1 and result.get("scanned_hosts") == 254
                 and not result.get("error") and result.get("source") == "LEXMARK_EWS"
                 and result.get("subnet") == str(network)
                 and normalize_mac(result.get("found_mac")) == candidate.expected_mac
                 and normalize_mac(result.get("expected_mac")) == candidate.expected_mac
                 and bool(candidate.expected_mac))
    except (TypeError, ValueError):
        valid = False
    if not valid:
        return {**unchanged, "error": "INVALID_RECOVERY_EVIDENCE"}

    # Serialize recovery writers even for different printers proposing the same
    # currently-unused IP. Locks are held only while applying, never during HTTP.
    devices = list(PrintingDevice.objects.select_for_update().order_by("pk"))
    device = next((d for d in devices if d.pk == candidate.device_id), None)
    if device is None or not device.is_active or device.ip_address != candidate.old_ip:
        return {**unchanged, "error": "DEVICE_CHANGED"}
    detection = _current_detection(device, candidate)
    if detection is None:
        return {**unchanged, "error": "DETECTION_CHANGED"}
    if automatic and (not device.supports_network or device.connection_status != "OFFLINE"
                      or device.monitor_error in ("DUPLICATE_IP", "NO_IP") or candidate.attempt_at is None
                      or device.last_recovery_attempt_at != candidate.attempt_at):
        return {**unchanged, "error": "AUTOMATIC_ELIGIBILITY_CHANGED"}
    new_ip = str(address)
    if new_ip == device.ip_address:
        return {**unchanged, "unchanged": True}
    if any(d.pk != device.pk and d.is_active and d.ip_address == new_ip for d in devices):
        return {**unchanged, "error": "IP_ALREADY_ASSIGNED"}

    _write_ip_change(device, detection, new_ip, candidate.expected_mac,
                     source="LEXMARK_EWS_AUTO_RECOVERY", reason="Recuperación automática por coincidencia exacta de MAC.")
    return dict(updated=True, history_created=True, unchanged=False, error="")


def _write_ip_change(device, detection, new_ip, mac, *, source, reason):
    """Shared write path; caller must hold device/detection locks in atomic()."""
    old_ip = device.ip_address
    if detection is not None:
        detection.is_current = False
        detection.save(update_fields=["is_current"])
    PrintingDeviceNetworkDetection.objects.create(
        printing_device=device, detected_ip=new_ip, detected_mac=mac,
        detection_source=source, is_current=True,
        notes=f"IP anterior: {old_ip or '-'}; IP nueva: {new_ip}. {reason}")
    fields = ["ip_address", "connection_status", "monitored_ip", "monitor_method", "monitor_error",
              "monitor_evidence", "updated_at"]
    if device.connection_status != "UNKNOWN":
        device.last_status_change_at = timezone.now()
        fields.append("last_status_change_at")
    device.ip_address = new_ip
    device.connection_status = "UNKNOWN"
    device.monitored_ip = None
    device.monitor_method = ""
    device.monitor_error = ""
    device.monitor_evidence = {}
    device.save(update_fields=fields)


@dataclass(frozen=True)
class DiscoveryCandidate:
    device_id: object
    old_ip: str
    serial: str
    detections: tuple

    @classmethod
    def capture(cls, device, detections):
        snapshots = tuple(detection_snapshot(d) for d in sorted(detections, key=lambda d: str(d.pk)))
        return cls(device.pk, device.ip_address, device.serial_number, snapshots)


@transaction.atomic
def apply_discovery_change(candidate, finding):
    """Discovery adds serial evidence but shares all history/reset writes above."""
    from .network_map import authorized_network
    from .network_reconciliation import reconcile_findings

    failed = dict(updated=False, error="INVALID_DISCOVERY_EVIDENCE")
    try:
        entry = authorized_network(finding["subnet"])
        network = ipaddress.ip_network(entry.subnet, strict=True)
        address = ipaddress.IPv4Address(finding["ip"])
        valid = (finding["status"] == "IP_CHANGED" and finding.get("network_unique")
                 and finding.get("scan_complete") and finding.get("source") == "LEXMARK_EWS"
                 and finding.get("supported") and valid_ip(str(address)) and address in network
                 and address not in (network.network_address, network.broadcast_address)
                 and finding.get("device_id") == str(candidate.device_id)
                 and (finding.get("serial") or normalize_mac(finding.get("mac"))))
    except (ValueError, TypeError, KeyError):
        valid = False
    if not valid:
        return failed
    devices = list(PrintingDevice.objects.select_for_update().order_by("pk"))
    device = next((d for d in devices if d.pk == candidate.device_id), None)
    if (device is None or not device.is_active or device.ip_address != candidate.old_ip
            or device.serial_number != candidate.serial):
        return {**failed, "error": "DEVICE_CHANGED"}
    detections = list(PrintingDeviceNetworkDetection.objects.select_for_update().filter(is_current=True).order_by("pk"))
    by_device = {}
    for detection in detections:
        by_device.setdefault(detection.printing_device_id, []).append(detection)
    current = by_device.get(device.pk, [])
    captured = tuple(detection_snapshot(d) for d in sorted(current, key=lambda d: str(d.pk)))
    if captured != candidate.detections:
        return {**failed, "error": "DETECTION_CHANGED"}
    fresh = reconcile_findings([finding], devices, by_device)[0]
    if fresh["status"] != "IP_CHANGED" or fresh["device_id"] != str(candidate.device_id):
        return {**failed, "error": fresh["reason"] or "IDENTITY_CHANGED"}
    _write_ip_change(device, current[0] if current else None, str(address), normalize_mac(finding.get("mac")),
                     source="LEXMARK_EWS_DISCOVERY", reason="Conciliación por identidad exacta de serial/MAC obtenida de EWS.")
    return dict(updated=True, error="")
