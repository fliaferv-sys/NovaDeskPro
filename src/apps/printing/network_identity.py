"""Read-only Lexmark EWS identity lookup, independent of TCP monitoring."""
import json
import math
import re
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from django.conf import settings

from .connectivity import valid_ip

MAX_RESPONSE_BYTES = 1024 * 1024


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never follow the printer to a different IP or another endpoint.
        return None


def normalize_mac(value):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if re.fullmatch(r"[0-9a-fA-F]{12}", value):
        compact = value
    elif re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", value):
        compact = value.replace(":", "")
    elif re.fullmatch(r"(?:[0-9a-fA-F]{2}-){5}[0-9a-fA-F]{2}", value):
        compact = value.replace("-", "")
    else:
        return ""
    if compact.upper() in ("000000000000", "FFFFFFFFFFFF"):
        return ""
    return ":".join(compact[i:i + 2].upper() for i in range(0, 12, 2))


def _setting_value(nodes, settings_values, name):
    matches = []

    def visit(value):
        if isinstance(value, dict):
            if value.get("name") == name:
                matches.append(value.get("setting"))
            for child in value.values():
                if isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(nodes)
    # Ambiguous/malformed nodes must not be used to confirm an identity.
    if len(matches) != 1 or isinstance(matches[0], bool) or not re.fullmatch(r"[0-9]+", str(matches[0])):
        raise ValueError("Missing or ambiguous node")
    setting = settings_values.get(str(matches[0]))
    if not isinstance(setting, dict) or not isinstance(setting.get("val"), str):
        raise ValueError("Missing setting value")
    return setting["val"]


def fetch_network_identity(ip, *, expected_mac=None, timeout=None):
    """GET one registered IPv4; compare UAA with supplied current detection MAC.

    No database writes, redirects, proxy use, SNMP, or printer mutations.
    PRINTING_IDENTITY_TIMEOUT_SECONDS defaults to 3; --timeout may override it.
    """
    result = dict(ip=ip, mac="", hostname="", identity_status="UNVERIFIED",
                  error="", source="LEXMARK_EWS")
    if not isinstance(ip, str) or not valid_ip(ip):
        result["error"] = "INVALID_IP"
        return result
    try:
        timeout = float(getattr(settings, "PRINTING_IDENTITY_TIMEOUT_SECONDS", 3) if timeout is None else timeout)
        if not math.isfinite(timeout) or not 0 < timeout <= 30:
            raise ValueError
    except (TypeError, ValueError):
        result["error"] = "INVALID_TIMEOUT"
        return result
    request = Request(f"http://{ip}/webglue/rawcontent?c=Settings/Network",
                      headers={"Accept": "application/json"}, method="GET")
    try:
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            result["error"] = "RESPONSE_TOO_LARGE"
            return result
    except HTTPError:
        result["error"] = "HTTP_ERROR"
        return result
    except (TimeoutError, URLError, OSError, HTTPException):
        result["error"] = "NETWORK_ERROR"
        return result
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        result["error"] = "INVALID_JSON"
        return result
    try:
        root = payload["nodes"]
        values = root["settings"]
        if not isinstance(values, dict):
            raise ValueError
        mac = normalize_mac(_setting_value(root["nodes"], values, "EthernetUAA"))
        hostname = _setting_value(root["nodes"], values, "SetHostname")
    except (KeyError, TypeError, ValueError, RecursionError):
        result["error"] = "MISSING_OR_AMBIGUOUS_NODES"
        return result
    if not mac:
        result["error"] = "INVALID_MAC"
        return result
    if not hostname.strip() or len(hostname) > 255 or any(ord(c) < 32 or ord(c) == 127 for c in hostname):
        result["error"] = "INVALID_HOSTNAME"
        return result
    result.update(mac=mac, hostname=hostname)
    expected = normalize_mac(expected_mac)
    if not expected:
        result["error"] = "NO_VALID_EXPECTED_MAC"
    elif mac != expected:
        result.update(identity_status="MISMATCH", error="MAC_MISMATCH")
    else:
        result["identity_status"] = "CONFIRMED"
    return result
