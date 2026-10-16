"""Bounded /24 discovery shared by manual and grouped automatic recovery."""
import ipaddress
import math
from concurrent.futures import ThreadPoolExecutor

from .network_identity import fetch_network_identity, normalize_mac


def validate_scan_options(subnet, timeout, workers=1):
    network = ipaddress.ip_network(subnet, strict=True)
    if network.version != 4 or network.prefixlen != 24:
        raise ValueError("INVALID_SUBNET")
    timeout = float(timeout)
    if not math.isfinite(timeout) or not 0 < timeout <= 3:
        raise ValueError("INVALID_TIMEOUT")
    if not isinstance(workers, int) or isinstance(workers, bool) or not 1 <= workers <= 8:
        raise ValueError("INVALID_WORKERS")
    return network, timeout


def scan_network_identities(subnet, *, timeout=1, workers=8, expected_mac=None):
    """One complete /24, retaining only normalized MAC/IP/hostname evidence.

    responsive_hosts counts valid EWS identities, not generic HTTP responses.
    No database operations occur in this function or its worker threads.
    """
    scan = dict(subnet=str(subnet), status="INVALID", identities={}, scanned_hosts=0,
                responsive_hosts=0, error="", source="LEXMARK_EWS")
    try:
        network = ipaddress.ip_network(subnet, strict=True)
        if network.version != 4 or network.prefixlen != 24:
            raise ValueError
    except (TypeError, ValueError):
        scan["error"] = "INVALID_SUBNET"
        return scan
    try:
        network, timeout = validate_scan_options(subnet, timeout, workers)
    except (TypeError, ValueError):
        scan["error"] = "INVALID_TIMEOUT_OR_WORKERS"
        return scan
    scan["subnet"] = str(network)

    def probe(ip):
        try:
            identity = fetch_network_identity(ip, expected_mac=expected_mac, timeout=timeout)
            valid = identity["identity_status"] in ("CONFIRMED", "MISMATCH") or (
                identity["identity_status"] == "UNVERIFIED" and identity["error"] == "NO_VALID_EXPECTED_MAC")
            if not valid:
                return ip, None, False
            mac = normalize_mac(identity["mac"])
            if not mac:
                return ip, None, True
            return ip, {"mac": mac, "hostname": identity["hostname"]}, False
        except Exception:
            return ip, None, True

    def collect(results):
        incomplete = False
        for ip, identity, failed in results:
            scan["scanned_hosts"] += 1
            incomplete |= failed
            if identity:
                scan["responsive_hosts"] += 1
                scan["identities"].setdefault(identity["mac"], []).append(
                    {"ip": ip, "hostname": identity["hostname"]})
        return incomplete

    ips = (str(host) for host in network.hosts())
    try:
        if workers == 1:
            incomplete = collect(map(probe, ips))
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                incomplete = collect(executor.map(probe, ips))
    except Exception:
        incomplete = True
    if incomplete or scan["scanned_hosts"] != 254:
        scan["error"] = "INCOMPLETE_SCAN"
    else:
        scan["status"] = "COMPLETE"
    return scan


def recovery_result(scan, expected_mac):
    expected = normalize_mac(expected_mac)
    result = dict(expected_mac=expected, subnet=scan["subnet"], found_ip="", found_mac="",
                  hostname="", status="INVALID", scanned_hosts=scan["scanned_hosts"],
                  responsive_hosts=scan["responsive_hosts"], match_count=0,
                  error=scan["error"], source="LEXMARK_EWS")
    if not expected:
        result["error"] = "INVALID_EXPECTED_MAC"
        return result
    if scan["status"] != "COMPLETE" or scan["scanned_hosts"] != 254:
        return result
    matches = scan["identities"].get(expected, [])
    result["match_count"] = len(matches)
    if len(matches) > 1:
        result.update(status="AMBIGUOUS", error="MULTIPLE_MAC_MATCHES")
    elif matches:
        result.update(status="FOUND", found_ip=matches[0]["ip"], found_mac=expected,
                      hostname=matches[0]["hostname"])
    else:
        result["status"] = "NOT_FOUND"
    return result


def recover_network_identity(subnet, expected_mac, *, timeout=0.4):
    if not normalize_mac(expected_mac):
        return recovery_result(dict(subnet=str(subnet), scanned_hosts=0, responsive_hosts=0,
                                    status="INVALID", identities={}, error="INVALID_EXPECTED_MAC"), expected_mac)
    scan = scan_network_identities(subnet, timeout=timeout, workers=1, expected_mac=normalize_mac(expected_mac))
    result = recovery_result(scan, expected_mac)
    if result["error"] == "INVALID_TIMEOUT_OR_WORKERS":
        result["error"] = "INVALID_TIMEOUT"
    return result
