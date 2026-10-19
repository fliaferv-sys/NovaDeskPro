"""Bounded, read-only SNMPv2c Printer-MIB serial lookup; no ORM or logging."""
import hmac
import math
import secrets
import socket

from django.conf import settings
from django.views.decorators.debug import sensitive_variables

from .connectivity import valid_ip

SERIAL_OID = "1.3.6.1.2.1.43.5.1.1.17.1"
SERIAL_OID_ARCS = tuple(int(part) for part in SERIAL_OID.split("."))
MAX_RESPONSE_BYTES = 4096


class SNMPValidationError(ValueError):
    """Contains only an application-defined safe error code."""


def _protocol():
    # Disabled/unconfigured installations do not require optional SNMP packages.
    from pyasn1.codec.ber import decoder, encoder
    from pysnmp.proto.api import v2c
    return decoder, encoder, v2c


def _validate_ber_framing(data):
    """SNMP uses definite BER lengths and primitive encodings of simple types.

    This checks framing/limits only. The library's SNMP ASN.1 schema validates
    the actual message, PDU, varbind and value structure below.
    """
    if not isinstance(data, bytes) or not data or len(data) > MAX_RESPONSE_BYTES:
        raise SNMPValidationError("INVALID_ASN1")
    nodes = 0

    def element(offset, end, depth):
        nonlocal nodes
        nodes += 1
        if depth > 8 or nodes > 32 or offset + 2 > end:
            raise SNMPValidationError("INVALID_ASN1")
        tag, length = data[offset], data[offset + 1]
        offset += 2
        if tag & 31 == 31:
            raise SNMPValidationError("INVALID_ASN1")
        if length & 128:
            count = length & 127
            if not 1 <= count <= 4 or offset + count > end:
                raise SNMPValidationError("INVALID_ASN1")
            length = int.from_bytes(data[offset:offset + count], "big")
            offset += count
        finish = offset + length
        if finish > end:
            raise SNMPValidationError("INVALID_ASN1")
        if tag == 0x02 and (not 1 <= length <= 4 or length > 1 and (
                data[offset] == 0 and data[offset + 1] < 128
                or data[offset] == 255 and data[offset + 1] >= 128)):
            raise SNMPValidationError("INVALID_ASN1")
        if tag & 32:
            if tag != 0x30 and not 0xA0 <= tag <= 0xA8:
                raise SNMPValidationError("INVALID_ASN1")
            while offset < finish:
                offset = element(offset, finish, depth + 1)
        return finish

    if element(0, len(data), 0) != len(data):
        raise SNMPValidationError("INVALID_ASN1")


@sensitive_variables("community")
def build_serial_request(request_id, community):
    _, encoder, v2c = _protocol()
    pdu = v2c.GetRequestPDU()
    v2c.apiPDU.set_defaults(pdu)
    v2c.apiPDU.set_request_id(pdu, request_id)
    v2c.apiPDU.set_varbinds(pdu, [(SERIAL_OID, v2c.Null(""))])
    message = v2c.Message()
    v2c.apiMessage.set_defaults(message)
    v2c.apiMessage.set_version(message, 1)  # SNMPv2c's wire version.
    v2c.apiMessage.set_community(message, community)
    v2c.apiMessage.set_pdu(message, pdu)
    return encoder.encode(message)


@sensitive_variables("data", "community", "message")
def decode_serial_response(data, *, request_id, community):
    _validate_ber_framing(data)
    decoder, _, v2c = _protocol()
    try:
        message, remainder = decoder.decode(data, asn1Spec=v2c.Message())
        if remainder or message.isInconsistent:
            raise SNMPValidationError("INVALID_ASN1")
        if int(v2c.apiMessage.get_version(message)) != 1:
            raise SNMPValidationError("WRONG_VERSION")
        if not hmac.compare_digest(v2c.apiMessage.get_community(message).asOctets(), community):
            raise SNMPValidationError("WRONG_COMMUNITY")
        if message["data"].getName() != "response":
            raise SNMPValidationError("WRONG_PDU")
        pdu = v2c.apiMessage.get_pdu(message)
        if int(v2c.apiPDU.get_request_id(pdu)) != request_id:
            raise SNMPValidationError("WRONG_REQUEST_ID")
        if int(v2c.apiPDU.get_error_status(pdu)) != 0:
            raise SNMPValidationError("AGENT_ERROR")
        if int(v2c.apiPDU.get_error_index(pdu)) != 0:
            raise SNMPValidationError("INVALID_ERROR_INDEX")
        bindings = v2c.apiPDU.get_varbinds(pdu)
        if len(bindings) != 1:
            raise SNMPValidationError("INVALID_VARBINDS")
        oid, value = bindings[0]
        if tuple(oid) != SERIAL_OID_ARCS:
            raise SNMPValidationError("WRONG_OID")
        if value.tagSet != v2c.OctetString().tagSet:
            raise SNMPValidationError("INVALID_VALUE_TYPE")
        raw = value.asOctets()
        if not 1 <= len(raw) <= 150 or any(byte < 32 or byte > 126 for byte in raw):
            raise SNMPValidationError("INVALID_SERIAL")
        serial = raw.decode("ascii").strip()
        if not serial or serial.casefold() in ("unknown", "n/a", "none", "not available"):
            raise SNMPValidationError("INVALID_SERIAL")
        return serial
    except SNMPValidationError:
        raise
    except Exception:
        # Library exception messages may embed the packet/community. Never expose.
        raise SNMPValidationError("INVALID_ASN1") from None


@sensitive_variables("community", "packet", "data")
def fetch_printer_serial(ip, *, timeout=None, retries=None):
    result = dict(ip=ip, serial="", status="UNVERIFIED", error="", source="SNMPV2C", oid=SERIAL_OID)
    if not isinstance(ip, str) or not valid_ip(ip):
        return {**result, "error": "INVALID_IP"}
    community = getattr(settings, "PRINTING_SNMP_COMMUNITY_SECRET", "")
    if not community:
        return {**result, "error": "NOT_CONFIGURED"}
    if not isinstance(community, str):
        return {**result, "error": "INVALID_CONFIGURATION"}
    try:
        community = community.encode("utf-8")
    except UnicodeError:
        return {**result, "error": "INVALID_CONFIGURATION"}
    if not 1 <= len(community) <= 255:
        return {**result, "error": "INVALID_CONFIGURATION"}
    try:
        configured_timeout = float(getattr(settings, "PRINTING_SNMP_TIMEOUT_SECONDS", 0.5))
        timeout = configured_timeout if timeout is None else float(timeout)
        retries = getattr(settings, "PRINTING_SNMP_RETRIES", 0) if retries is None else retries
        if isinstance(retries, str) and retries in ("0", "1"):
            retries = int(retries)
        if (not math.isfinite(configured_timeout) or not 0 < configured_timeout <= 3
                or not math.isfinite(timeout) or not 0 < timeout <= 3 or type(retries) is not int
                or not 0 <= retries <= 1):
            raise ValueError
        timeout = min(timeout, configured_timeout)
    except (ValueError, TypeError):
        return {**result, "error": "INVALID_CONFIGURATION"}
    request_id = secrets.randbelow(2147483647) + 1
    try:
        packet = build_serial_request(request_id, community)
    except ImportError:
        return {**result, "error": "DEPENDENCY_UNAVAILABLE"}
    except Exception:
        return {**result, "error": "REQUEST_ERROR"}
    try:
        # A connected UDP socket accepts replies only from this IP and port.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as transport:
            transport.settimeout(timeout)
            transport.connect((ip, 161))
            for attempt in range(retries + 1):
                transport.send(packet)
                try:
                    data = transport.recv(MAX_RESPONSE_BYTES + 1)
                except TimeoutError:
                    if attempt < retries:
                        continue
                    return {**result, "error": "TIMEOUT"}
                serial = decode_serial_response(data, request_id=request_id, community=community)
                return {**result, "serial": serial, "status": "CONFIRMED"}
    except SNMPValidationError as exc:
        return {**result, "error": str(exc)}
    except OSError:
        return {**result, "error": "NETWORK_ERROR"}
    except Exception:
        return {**result, "error": "SNMP_ERROR"}
    return {**result, "error": "TIMEOUT"}
