"""Server-owned identity contexts. Browser configuration never grants access."""
import hashlib
import json
from dataclasses import dataclass

from django.contrib import admin
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import User
from apps.core.models import Department
from apps.institution.models import OrganizationalUnit
from .identity_services import InstitutionalIdentityError, resolve_common_identity


CONTRACT_FIELDS = frozenset({
    "name", "first_name", "last_name", "full_name", "email", "username",
    "document_number", "employee_number", "phone", "position", "location",
    "organizational_unit", "organizational_path", "employment_relationship",
    "employment_type", "photo_url", "source", "local_user_id", "rrhh_id",
})
SUMMARY_FIELDS = frozenset({"full_name", "email", "employee_number", "source"})
ACCOUNT_FORM_FIELDS = frozenset({
    "email", "username", "first_name", "last_name", "document_number",
    "employee_number", "phone", "position", "employment_type",
    "department", "organizational_unit",
})
REFERENCE_SALT = "directory.identity.v1"
REFERENCE_MAX_AGE = 1800


@dataclass(frozen=True)
class IdentityPolicy:
    context: str
    object_id: str = ""
    fields: frozenset = CONTRACT_FIELDS
    summary_fields: frozenset = SUMMARY_FIELDS


def authorize_identity_context(request, context, object_id=""):
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
        return identity
    except (signing.BadSignature, ValueError, KeyError, TypeError, InstitutionalIdentityError) as exc:
        raise ValidationError("La selección institucional venció, cambió o no pudo validarse. Seleccione nuevamente o quite la selección para continuar manualmente.") from exc


def account_form_values(identity):
    values = {key: identity.get(key) for key in ACCOUNT_FORM_FIELDS if identity.get(key) and key not in {"username", "department", "organizational_unit"}}
    if identity.get("email"):
        values["username"] = identity["email"].split("@", 1)[0]
    elif identity.get("username"):
        values["username"] = identity["username"]
    location = str(identity.get("location") or "").strip()
    if location:
        departments = list(Department.objects.filter(name__iexact=location, is_active=True)[:2])
        if len(departments) == 1:
            values["department"] = {"value": str(departments[0].pk), "label": str(departments[0])}
    unit = identity.get("organizational_unit")
    if unit and unit.get("code"):
        units = list(OrganizationalUnit.objects.filter(code=unit["code"], is_active=True)[:2])
        if len(units) == 1:
            values["organizational_unit"] = {"value": str(units[0].pk), "label": str(units[0])}
    return values


def serialize_identity(request, policy, identity, *, summary=False):
    fields = policy.summary_fields if summary else policy.fields
    payload = {key: identity.get(key) for key in fields}
    payload["reference"] = issue_identity_reference(request, policy, identity)
    return payload
