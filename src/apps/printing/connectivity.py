"""Bounded TCP probes of registered printer IPs; never called by web views."""
import ipaddress
import socket
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from .models import PrintingDevice


def valid_ip(value):
    try:
        ip = ipaddress.IPv4Address(value)
        return not (ip.is_unspecified or ip.is_multicast or ip.is_loopback
                    or ip.is_link_local or str(ip) == "255.255.255.255")
    except (ValueError, TypeError, ipaddress.AddressValueError):
        return False


def with_connectivity(queryset):
    duplicates = PrintingDevice.objects.filter(ip_address=OuterRef("ip_address")).exclude(pk=OuterRef("pk"))
    return queryset.annotate(monitor_ip_conflict=Exists(duplicates))


def ip_conflict(device):
    if hasattr(device, "monitor_ip_conflict"):
        return device.monitor_ip_conflict
    return PrintingDevice.objects.filter(ip_address=device.ip_address).exclude(pk=device.pk).exists()


def effective_status(device, *, now=None):
    now = now or timezone.now()
    ttl = timedelta(seconds=settings.PRINTING_MONITOR_MAX_AGE_SECONDS)
    if (not device.supports_network or not valid_ip(device.ip_address)
            or device.monitored_ip != device.ip_address or not device.last_checked_at
            or not now - ttl <= device.last_checked_at <= now
            or device.monitor_method != "TCP"
            or not isinstance(device.monitor_evidence, dict)
            or device.monitor_evidence.get("network_port") != device.network_port
            or device.connection_status not in ("ONLINE", "OFFLINE")
            or ip_conflict(device)):
        return "UNKNOWN"
    return device.connection_status


def probe_device(device, *, timeout=None):
    timeout = settings.PRINTING_MONITOR_TIMEOUT_SECONDS if timeout is None else timeout
    if not 0 < timeout <= 10:
        raise ValueError("Timeout must be between 0 and 10 seconds.")
    result = dict(connection_status="UNKNOWN", monitored_ip=None, monitor_method="",
                  monitor_error="", monitor_evidence={"network_port": device.network_port})
    if not device.ip_address:
        result["monitor_error"] = "NO_IP"
        return result
    if not valid_ip(device.ip_address):
        result["monitor_error"] = "INVALID_IP"
        return result
    result["monitored_ip"] = device.ip_address
    if ip_conflict(device):
        result["monitor_error"] = "DUPLICATE_IP"
        return result
    if not device.supports_network or not 1 <= device.network_port <= 65535:
        result["monitor_error"] = "INVALID_NETWORK_CONFIGURATION"
        return result
    result["monitor_method"] = "TCP"
    ports = list(dict.fromkeys((device.network_port, 443, 80)))
    attempted = []
    for port in ports:
        attempted.append(port)
        try:
            with socket.create_connection((device.ip_address, port), timeout=timeout):
                pass
        except OSError:
            continue
        except Exception:
            # Do not expose exception messages (or configuration/credentials).
            result["monitor_error"] = "PROBE_ERROR"
            result["monitor_evidence"]["attempted_ports"] = attempted
            return result
        result["connection_status"] = "ONLINE"
        result["monitor_evidence"].update(attempted_ports=attempted, reachable_port=port,
            host_reachable=True, print_port_reachable=port == device.network_port)
        return result
    result["connection_status"] = "OFFLINE"
    result["monitor_error"] = "NO_RESPONSE"
    result["monitor_evidence"].update(attempted_ports=attempted, host_reachable=False,
                                      print_port_reachable=False)
    return result


@transaction.atomic
def persist_result(device, result, checked_at):
    current = PrintingDevice.objects.select_for_update().get(pk=device.pk)
    # Ignore measurements if the operator changed the target during the probe,
    # or another execution already stored a newer measurement.
    if ((current.ip_address, current.network_port, current.supports_network, current.is_active)
            != (device.ip_address, device.network_port, device.supports_network, device.is_active)
            or current.last_checked_at and current.last_checked_at > checked_at):
        return False
    if current.ip_address and ip_conflict(current):
        result = {**result, "connection_status": "UNKNOWN", "monitor_error": "DUPLICATE_IP",
                  "monitor_evidence": {"network_port": current.network_port}}
    fields = list(result) + ["last_checked_at"]
    if current.connection_status != result["connection_status"]:
        current.last_status_change_at = checked_at
        fields.append("last_status_change_at")
    for field, value in result.items():
        setattr(current, field, value)
    current.last_checked_at = checked_at
    if current.connection_status == "ONLINE":
        current.last_online_at = checked_at
        fields.append("last_online_at")
    current.save(update_fields=fields)
    return True
