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

    detection.is_current = False
    detection.save(update_fields=["is_current"])
    PrintingDeviceNetworkDetection.objects.create(
        printing_device=device, detected_ip=new_ip, detected_mac=candidate.expected_mac,
        detection_source="LEXMARK_EWS_AUTO_RECOVERY", is_current=True,
        notes=f"IP anterior: {candidate.old_ip or '-'}; IP nueva: {new_ip}. "
              "Recuperación automática por coincidencia exacta de MAC.")
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
    return dict(updated=True, history_created=True, unchanged=False, error="")
