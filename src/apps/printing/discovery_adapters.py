"""Read-only vendor adapters. Unsupported hosts are never labelled printers."""
import json
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener

from .network_identity import fetch_network_identity, normalize_mac, _NoRedirect, MAX_RESPONSE_BYTES, _setting_value
from .snmp_identity import fetch_printer_serial


def _safe_text(value, limit=150):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        return ""
    return value


def _device_information(ip, timeout):
    """Optional DeviceInformation; only explicitly named setting nodes are used.

    Unknown firmware schemas yield empty fields, never guessed serials.
    """
    request = Request(f"http://{ip}/webglue/rawcontent?c=DeviceInformation",
                      headers={"Accept": "application/json"}, method="GET")
    try:
        with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            return {}, "DEVICE_INFORMATION_TOO_LARGE"
        payload = json.loads(raw)
        nodes = payload["nodes"]["nodes"]
        settings = payload["nodes"]["settings"]
        values = {}
        for field, name in (("serial", "SerialNumber"), ("model", "ModelName"), ("manufacturer", "Manufacturer")):
            try:
                values[field] = _safe_text(_setting_value(nodes, settings, name))
            except (ValueError, TypeError, AttributeError):
                values[field] = ""
        return values, ""
    except (HTTPError, URLError, OSError, HTTPException):
        return {}, "DEVICE_INFORMATION_UNAVAILABLE"
    except (ValueError, UnicodeError, KeyError, TypeError, RecursionError, AttributeError):
        return {}, "DEVICE_INFORMATION_UNSUPPORTED"


class LexmarkEWSAdapter:
    source = "LEXMARK_EWS"

    def identify(self, ip, *, timeout):
        identity = fetch_network_identity(ip, timeout=timeout)
        error = identity["error"]
        if error in ("NETWORK_ERROR", "INVALID_IP", "INVALID_TIMEOUT"):
            return None
        result = dict(ip=ip, mac="", hostname="", manufacturer="", model="", serial="",
                      supported=False, source="", error=error, snmp_status="NOT_ATTEMPTED",
                      snmp_error="", serial_source="", identity_verified=False)
        mac = normalize_mac(identity["mac"])
        if not mac or not identity["hostname"]:
            # HTTP answered, but the Lexmark identity contract was not met.
            return result
        info, info_error = _device_information(ip, timeout)
        manufacturer = info.get("manufacturer", "")
        if manufacturer and manufacturer.casefold() not in ("lexmark", "lexmark international", "lexmark international, inc."):
            result.update(mac=mac, hostname=identity["hostname"], manufacturer=manufacturer,
                          model=info.get("model", ""), serial=info.get("serial", ""),
                          error="MANUFACTURER_CONFLICT")
            return result
        result.update(mac=mac, hostname=identity["hostname"], manufacturer="Lexmark",
                      serial=info.get("serial", ""), model=info.get("model", ""), supported=True,
                      source=self.source, error=info_error)
        snmp = fetch_printer_serial(ip, timeout=timeout)
        result["snmp_status"] = snmp["status"]
        result["snmp_error"] = snmp["error"]
        result["serial_source"] = "LEXMARK_EWS" if result["serial"] else ""
        if snmp["status"] == "CONFIRMED":
            if result["serial"] and result["serial"] != snmp["serial"]:
                result["error"] = "SERIAL_SOURCE_CONFLICT"
                return result
            else:
                result["serial"] = snmp["serial"]
                result["serial_source"] = "SNMPV2C"
        if result["serial"]:
            # Bracket the serial query with two independent EWS MAC reads.
            # The stored serial/MAC pair is additionally required for --apply.
            after = fetch_network_identity(ip, timeout=timeout)
            after_mac = normalize_mac(after.get("mac"))
            if not after_mac or not after.get("hostname"):
                result.update(error="NETWORK_IDENTITY_UNVERIFIED", serial="", serial_source="")
            elif after_mac != mac:
                result.update(error="NETWORK_IDENTITY_CHANGED", serial="", serial_source="")
            else:
                result["identity_verified"] = True
        return result


# Add real, tested adapters here as protocols become known. No placeholder vendors.
ADAPTERS = (LexmarkEWSAdapter(),)


def identify_host(ip, *, timeout):
    unidentified = None
    for adapter in ADAPTERS:
        finding = adapter.identify(ip, timeout=timeout)
        if finding and finding["supported"]:
            return finding
        unidentified = finding or unidentified
    return unidentified
