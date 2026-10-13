"""Server-built, reviewed context; never changes requester or asset ownership."""
import hashlib
import json
import re

from django.core import signing
from django.utils import timezone

from apps.integrations.technical_context import resolve_technical_context
from apps.integrations.automatic_context import resolve_automatic_context, automatic_selection

PERSON_FIELDS = ("full_name", "username", "email", "phone", "position", "department",
                 "location", "employee_number", "employment_type")
DEVICE_FIELDS = ("type", "name", "hostname", "mac", "serial", "location")
SALT = "tickets.reviewed-context.v1"


def safe_text(value):
    if not isinstance(value, (str, int)):
        return None
    text = str(value).strip()[:300]
    if re.search(r"token|password|passwd|authorization|secret|https?://[^\s]*@", text, re.I):
        return None
    return text or None


def person_snapshot(person):
    data = person.get("data") or {}
    result = {key: safe_text(data.get(key)) for key in PERSON_FIELDS}
    result["sources"] = [safe_text(source) for source in person.get("sources", []) if safe_text(source)]
    result["confidence"] = safe_text(person.get("confidence"))
    return result


def fingerprint(context):
    return hashlib.sha256(json.dumps(context, sort_keys=True, default=str).encode()).hexdigest()


def can_review(user):
    return user.is_authenticated and (user.is_superuser or user.role in ("ADMIN", "TECHNICIAN"))


def review_token(context, user, query):
    return signing.dumps({"user": str(user.pk), "query": query, "digest": fingerprint(context)}, salt=SALT, compress=True)


def build_snapshot(user, selection):
    """Fail open for ticket creation, closed for context association."""
    if not user.is_authenticated or selection == "skip" or len(selection) > 12000:
        return None
    try:
        if not selection:
            context = resolve_automatic_context(user)
            selected = automatic_selection(context)
            if selected is None:
                return None
        else:
            selected = json.loads(selection)
            proof = signing.loads(selected["token"], salt=SALT, max_age=1800)
            if proof["user"] != str(user.pk):
                return None
            query = proof["query"]
            if query.get("automatic"):
                context = resolve_automatic_context(user)
                if not can_review(user):
                    safe_selection = automatic_selection(context)
                    if safe_selection is None or any(selected.get(key) != value for key, value in safe_selection.items()):
                        return None
            elif can_review(user):
                context = resolve_technical_context(requester=user, **query)
            else:
                return None
        # Signed inputs came from the validated, read-only GET endpoint.
        if selection and fingerprint(context) != proof["digest"]:
            return None
        index = selected["device"]
        if type(index) is not int or index < 0:
            return None
        device = context["devices"][index]
        def choose(candidates, key):
            number = selected.get(key)
            if number is None:
                return None
            if type(number) is not int or number < 0:
                raise ValueError("Invalid selection")
            return candidates[number]
        requester = choose((context.get("person") or {}).get("candidates", []), "requester")
        detected = choose((device.get("detected_user") or {}).get("candidates", []), "detected")
        asset = choose(device.get("novadesk_assets", []), "asset")
        snapshot = {
            "requester_identity": person_snapshot(requester) if requester else {
                **{key: safe_text((context.get("requester") or {}).get(key)) for key in PERSON_FIELDS},
                "sources": ["NOVADESK"], "confidence": "CONFIRMADA"},
            "detected_user": person_snapshot(detected) if detected else None,
            "device": {**{key: safe_text((device.get("data") or {}).get(key)) for key in DEVICE_FIELDS},
                       "ip": safe_text(device.get("ip")), "glpi_id": safe_text(device.get("glpi_id")),
                       "sources": sorted({safe_text(v) for v in device.get("provenance", {}).values() if safe_text(v)}),
                       "confidence": safe_text(device.get("confidence"))},
            "novadesk_asset": {"asset_id": safe_text(asset.get("id")), "code": safe_text(asset.get("code")),
                               "responsible_identity": {key: safe_text((asset.get("responsible") or {}).get(key)) for key in PERSON_FIELDS}} if asset else None,
            "metadata": {"reviewed_by": str(user.pk), "reviewed_at": timezone.now().isoformat(),
                         "resolver_version": "1", "warnings": [safe_text(w) for w in context.get("warnings", []) if safe_text(w)]},
        }
        snapshot["device"]["association_confidence"] = safe_text(device.get("association_confidence"))
        snapshot["metadata"]["association_mode"] = "AUTOMATICA" if (
            (not selection or proof["query"].get("automatic")) and
            automatic_selection(context) is not None and
            all(selected.get(key) == value for key, value in automatic_selection(context).items())
        ) else "REVISADA"
        return snapshot
    except Exception:
        # No raw exceptions or external response bodies in logs/UI.
        return None
