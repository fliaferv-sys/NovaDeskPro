"""Server-owned identity contexts. Browser configuration never grants access."""
import hashlib
import json
from dataclasses import dataclass

from django.contrib import admin
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import User
from apps.institution.models import OrganizationalUnit
from .identity_services import InstitutionalIdentityError, resolve_common_identity


CONTRACT_FIELDS = frozenset({
    "selectable", "has_local_user", "selection_requirement", "selection_reason",
    "name", "first_name", "last_name", "full_name", "email", "username",
    "document_number", "employee_number", "phone", "position", "location",
    "organizational_unit", "organizational_path", "employment_relationship",
    "employment_type", "photo_url", "source", "source_label", "sources", "status", "branch", "local_user_id", "rrhh_id",
})
SUMMARY_FIELDS = frozenset({"full_name", "email", "employee_number", "source"})
ACCOUNT_FORM_FIELDS = frozenset({
    "email", "username", "first_name", "last_name", "document_number",
    "employee_number", "phone", "position", "employment_type",
    "organizational_unit",
})
REFERENCE_SALT = "directory.identity.v1"
REFERENCE_MAX_AGE = 1800

# Read-only technical IP query. No CI, employee numbers, local IDs or signed
# form-selection references are needed. Authorization lives in the query view.
TECHNICAL_IP_IDENTITY_FIELDS = frozenset({
    "full_name", "username", "email", "position", "organizational_unit", "phone", "location", "source",
})


def technical_ip_identity_payload(identity):
    return {key: identity.get(key) for key in TECHNICAL_IP_IDENTITY_FIELDS}


def technical_context_identity_payload(identity):
    """Server-owned whitelist for a ticket context; never client-selected fields."""
    return {**technical_ip_identity_payload(identity),
            "employee_number": identity.get("employee_number"),
            "employment_type": identity.get("employment_relationship") or identity.get("employment_type")}


@dataclass(frozen=True)
class IdentityPolicy:
    context: str
    object_id: str = ""
    fields: frozenset = CONTRACT_FIELDS
    summary_fields: frozenset = SUMMARY_FIELDS
    auto_resolve: bool = True
    selection_requirement: str = "autofill"


def authorize_identity_context(request, context, object_id=""):
    if isinstance(context, str) and context.startswith("inventory."):
        from apps.accounts.access import can_manage_inventory
        from apps.inventory.models import Asset, StockDelivery, ToolLoan
        parts = context.split(".")
        admin_context = len(parts) == 4 and parts[1] == "admin"
        kind = parts[-2] if len(parts) in (3, 4) else ""
        operation = parts[-1]
        model = {"asset": Asset, "delivery": StockDelivery, "loan": ToolLoan}.get(kind)
        if model is None or operation not in {"add", "change"} or (len(parts) != 3 and not admin_context):
            raise PermissionDenied
        try:
            obj = model.objects.filter(pk=object_id).first() if object_id else None
        except (ValueError, ValidationError):
            obj = None
        if operation == "add" and object_id or operation == "change" and obj is None:
            raise PermissionDenied
        if admin_context:
            model_admin = admin.site._registry[model]
            allowed = admin.site.has_permission(request) and (
                model_admin.has_add_permission(request) if operation == "add" else model_admin.has_change_permission(request, obj))
        else:
            allowed = can_manage_inventory(request.user)
        if not allowed or (kind == "delivery" and obj and obj.status != "DRAFT"):
            raise PermissionDenied
        fields = frozenset({"full_name", "email", "username", "source", "local_user_id"})
        return IdentityPolicy(context, str(object_id or ""), fields, fields, auto_resolve=False, selection_requirement="institutional")
    if not request.user.is_authenticated or not admin.site.has_permission(request):
        raise PermissionDenied
    user_admin = admin.site._registry[User]
    if context == "accounts.add":
        if object_id or not user_admin.has_add_permission(request):
            raise PermissionDenied
    elif context == "accounts.change":
        try:
            obj = User.objects.filter(pk=object_id).first() if object_id else None
        except (ValueError, ValidationError):
            obj = None
        if obj is None or not user_admin.has_change_permission(request, obj):
            raise PermissionDenied
    elif context in {"printing.add", "printing.change"}:
        from apps.printing.models import PrintingDevice
        device_admin = admin.site._registry[PrintingDevice]
        if context == "printing.add":
            if object_id or not device_admin.has_add_permission(request):
                raise PermissionDenied
        else:
            try:
                obj = PrintingDevice.objects.filter(pk=object_id).first() if object_id else None
            except (ValueError, ValidationError):
                obj = None
            if obj is None or not device_admin.has_change_permission(request, obj):
                raise PermissionDenied
        fields = frozenset({"full_name", "email", "username", "source", "local_user_id"})
        return IdentityPolicy(context, str(object_id or ""), fields, fields, auto_resolve=False, selection_requirement="institutional")
    else:
        # Additional modules must explicitly register their own policies.
        raise PermissionDenied
    return IdentityPolicy(context, str(object_id or ""))


def identity_identifiers(identity):
    return {key: identity.get(key) for key in ("source", "rrhh_id", "local_user_id", "email", "username", "employee_number", "document_number")}


def issue_identity_reference(request, policy, identity):
    # Signed claims contain source keys, never CI or a personal-data snapshot.
    fingerprint = hashlib.sha256(json.dumps(identity_identifiers(identity), sort_keys=True).encode()).hexdigest()
    return signing.dumps({
        "locator": identity["_locator"], "linked": identity.get("_linked", []),
        "fingerprint": fingerprint, "actor": str(request.user.pk),
        "context": policy.context, "object_id": policy.object_id,
    }, salt=REFERENCE_SALT, compress=True)


def validate_identity_reference(request, policy, reference):
    try:
        claims = signing.loads(reference, salt=REFERENCE_SALT, max_age=REFERENCE_MAX_AGE)
        if (claims.get("actor"), claims.get("context"), claims.get("object_id")) != (str(request.user.pk), policy.context, policy.object_id):
            raise ValueError("Reference scope mismatch")
        identity = resolve_common_identity(claims["locator"], claims.get("linked"))
        fingerprint = hashlib.sha256(json.dumps(identity_identifiers(identity), sort_keys=True).encode()).hexdigest()
        if fingerprint != claims.get("fingerprint"):
            raise ValueError("Identity identifiers changed")
        validate_selection(policy, identity)
        return identity
    except (signing.BadSignature, ValueError, KeyError, TypeError, InstitutionalIdentityError) as exc:
        raise ValidationError("La selección institucional venció, cambió o no pudo validarse. Seleccione nuevamente o quite la selección para continuar manualmente.") from exc


def account_form_values(identity):
    values = {key: identity.get(key) for key in ACCOUNT_FORM_FIELDS if identity.get(key) and key not in {"username", "department", "organizational_unit"}}
    if identity.get("email"):
        values["username"] = identity["email"].split("@", 1)[0]
    elif identity.get("username"):
        values["username"] = identity["username"]
    unit = identity.get("organizational_unit")
    if unit and unit.get("code") and not identity.get("organization_conflicts"):
        units = list(OrganizationalUnit.objects.filter(code=unit["code"], is_active=True)[:2])
        if len(units) == 1:
            values["organizational_unit"] = {"value": str(units[0].pk), "label": str(units[0])}
    return values


def serialize_identity(request, policy, identity, *, summary=False):
    fields = policy.summary_fields if summary else policy.fields
    payload = {key: identity.get(key) for key in fields}
    payload.update(selection_capabilities(policy, identity))
    payload["reference"] = issue_identity_reference(request, policy, identity)
    return payload


def identity_form_values(policy, identity):
    if policy.context.startswith(("printing.", "inventory.")):
        user = associated_local_user(identity)
        return {"local_user_id": {"value": str(user.pk) if user else "", "label": str(user) if user else ""}}
    return account_form_values(identity)


def associated_local_user(identity):
    """Only use the secure link established by the common resolver."""
    user_id = identity.get("local_user_id")
    if not user_id:
        return None
    try:
        return User.objects.filter(pk=user_id).first()
    except (ValueError, ValidationError):
        return None


def selection_capabilities(policy, identity):
    from .identity_selection import institutional_selection
    eligible, reason = institutional_selection(identity)
    has_local = associated_local_user(identity) is not None
    requirement = policy.selection_requirement
    selectable = (True if requirement == "autofill" else
                  has_local if requirement == "local_user" else
                  eligible and has_local if requirement == "both" else eligible)
    if not selectable and requirement in {"local_user", "both"} and not has_local:
        reason = "Esta seleccion requiere una cuenta local existente."
    return {"selectable": selectable, "has_local_user": has_local,
            "selection_requirement": requirement, "selection_reason": "" if selectable else reason}


def validate_selection(policy, identity):
    capabilities = selection_capabilities(policy, identity)
    if not capabilities["selectable"]:
        raise ValidationError(capabilities["selection_reason"])
