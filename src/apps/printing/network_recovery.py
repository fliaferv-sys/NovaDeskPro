"""Operator-selected /24 recovery; proposes an IP without database writes."""
import ipaddress
import math

from .network_identity import fetch_network_identity, normalize_mac


def recover_network_identity(subnet, expected_mac, *, timeout=0.4):
    """Scan each usable address sequentially, including after the first match.

    responsive_hosts counts valid Lexmark EWS identities, including other MACs;
    a generic HTTP response does not count as identity evidence. Ordinary network
    failures are expected. Unexpected probe failures invalidate a unique result.
    """
    expected = normalize_mac(expected_mac)
    result = dict(expected_mac=expected, subnet=str(subnet), found_ip="", found_mac="",
                  hostname="", status="INVALID", scanned_hosts=0, responsive_hosts=0,
                  error="", source="LEXMARK_EWS")
    if not expected:
        result["error"] = "INVALID_EXPECTED_MAC"
        return result
    try:
        network = ipaddress.ip_network(subnet, strict=True)
        if network.version != 4 or network.prefixlen != 24:
            raise ValueError
    except (TypeError, ValueError):
        result["error"] = "INVALID_SUBNET"
        return result
    result["subnet"] = str(network)
    try:
        timeout = float(timeout)
        if not math.isfinite(timeout) or not 0 < timeout <= 3:
            raise ValueError
    except (TypeError, ValueError):
        result["error"] = "INVALID_TIMEOUT"
        return result

    matches = []
    incomplete = False
    for host in network.hosts():
        ip = str(host)
        result["scanned_hosts"] += 1
        try:
            identity = fetch_network_identity(ip, expected_mac=expected, timeout=timeout)
        except Exception:
            # Never include exception text, raw responses or credentials.
            incomplete = True
            continue
        if identity["identity_status"] not in ("CONFIRMED", "MISMATCH"):
            continue
        detected_mac = normalize_mac(identity["mac"])
        if not detected_mac:
            continue
        result["responsive_hosts"] += 1
        # Match by exact UAA, never just HTTP reachability or hostname.
        if detected_mac == expected:
            matches.append((ip, detected_mac, identity["hostname"]))
    if len(matches) > 1:
        result.update(status="AMBIGUOUS", error="MULTIPLE_MAC_MATCHES")
    elif incomplete:
        result["error"] = "INCOMPLETE_SCAN"
    elif matches:
        ip, mac, hostname = matches[0]
        result.update(status="FOUND", found_ip=ip, found_mac=mac, hostname=hostname)
    else:
        result["status"] = "NOT_FOUND"
    return result
