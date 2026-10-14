"""Conservative, individual institutional synchronization; never writes on resolution."""
import re
import logging
import unicodedata

from django.conf import settings
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction

from apps.accounts.access import user_has_role
from apps.accounts.models import User
from apps.activity.models import ActivityLog
from apps.directory.services import search_directory_employees
from apps.directory.ad_services import search_ad_users
from apps.directory.identity_services import _normalize_rrhh_employee
from apps.institution.identity_organization import OrganizationIndex

SYNC_FIELDS = ("id_personal", "employee_number", "phone", "position")


def text_key(value):
    text = unicodedata.normalize("NFD", str(value or ""))
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split()).casefold()


def phone_key(value):
    return re.sub(r"[\s().+-]", "", str(value or ""))


def resolve_sync_identity(user, *, rrhh_search=None, ad_search=None):
    """Use existing source search rules; no name-only or phone-only links."""
    rrhh_search = rrhh_search or search_directory_employees
    ad_search = ad_search or search_ad_users
    evidence, rows, cache = [], [], {}
    def rrhh(value, field):
        key = (str(value), field)
        if key not in cache:
            cache[key] = rrhh_search(str(value), limit=100, search_field=field, exact=field != "name")
            if len(cache[key]) >= 100:
                raise ValueError("Incomplete source")
        return cache[key]
    email = (user.email or "").strip().casefold()
    username = (user.username or "").strip().casefold()
    account_safe = bool(email and "@" in email and email.rsplit("@", 1)[1] == settings.DIRECTORY_AD_DOMAIN.casefold()
                        and username == email.split("@", 1)[0])
    # Direct identifiers outrank other evidence, but inconsistent identifiers
    # never get ignored merely because a higher-priority match was found.
    for value, field in ((user.id_personal, "rrhh_id"), (user.employee_number, "employee_number")):
        if value is not None and str(value).strip():
            found = rrhh(value, field)
            if len(found) != 1:
                return None, evidence, ["identificador_ambiguo_o_ausente"]
            if rows and str(rows[0].get("IdPersonal")) != str(found[0].get("IdPersonal")):
                return None, evidence, ["identificadores_contradictorios"]
            rows = found
            evidence.append(field)
    if account_safe:
        email_rows = rrhh(email, "email")
        if len(email_rows) > 1:
            return None, evidence, ["correo_rrhh_ambiguo"]
        if rows and email_rows and str(rows[0].get("IdPersonal")) != str(email_rows[0].get("IdPersonal")):
            return None, evidence, ["correo_identificador_contradictorio"]
        if not rows and email_rows:
            rows = email_rows
            evidence.append("correo_username_institucional")
    if not rows and account_safe:
        by_email = ad_search(email, limit=100, search_field="email", exact=True)
        by_username = ad_search(username, limit=100, search_field="username", exact=True)
        if len(by_email) != 1 or len(by_username) != 1:
            return None, evidence, ["cuenta_ad_ambigua_o_ausente"]
        for account in (by_email[0], by_username[0]):
            if ((account.get("email") or "").strip().casefold() != email or
                (account.get("username") or "").strip().casefold() != username or
                account.get("is_active") is not True or account.get("is_person") is False or
                account.get("is_shared") or account.get("is_technical")):
                return None, evidence, ["cuenta_ad_incompatible"]
        name = by_email[0].get("name") or ""
        if not name or not phone_key(user.phone):
            return None, evidence, ["evidencia_insuficiente"]
        if text_key(by_username[0].get("name")) != text_key(name):
            return None, evidence, ["cuenta_ad_incompatible"]
        if user.get_full_name().strip() and text_key(user.get_full_name()) != text_key(name):
            return None, evidence, ["nombre_local_contradictorio"]
        name_rows = [row for row in rrhh(name, "name") if text_key(row.get("NombresApellidos")) == text_key(name)]
        # Even same-name records cannot be reduced arbitrarily by taking first.
        rows = [row for row in name_rows if phone_key(row.get("Telefono")) == phone_key(user.phone)]
        if len(rows) != 1:
            return None, evidence, ["nombre_telefono_ambiguo_o_ausente"]
        evidence.extend(("ad_correo_username", "rrhh_nombre_telefono"))
    if not rows:
        return None, evidence, []
    row = rows[0]
    if row.get("Estado") != "Activo":
        return None, evidence, ["identidad_inactiva"]
    if row.get("Mail") and email and row["Mail"].strip().casefold() != email:
        return None, evidence, ["correo_contradictorio"]
    if user.phone and row.get("Telefono") and phone_key(user.phone) != phone_key(row["Telefono"]):
        return None, evidence, ["telefono_contradictorio"]
    identity = _normalize_rrhh_employee(row)
    identity["sources"] = ["RRHH", "ACTIVE_DIRECTORY"] if "ad_correo_username" in evidence else ["RRHH"]
    return identity, evidence, []


def build_user_institutional_sync_plan(user):
    plan = {"matched_identity": None, "proposed_changes": {}, "conflicts": [],
            "evidence": [], "confidence": "DESCONOCIDA", "can_apply": False}
    try:
        identity, evidence, conflicts = resolve_sync_identity(user)
        plan.update(matched_identity=identity, evidence=evidence, conflicts=conflicts)
        if not identity:
            return plan
        plan["confidence"] = "CONFIRMADA"
        blocking = False
        for field in SYNC_FIELDS:
            current, candidate = getattr(user, field), identity.get(field)
            if candidate in (None, ""):
                continue
            try:
                candidate = User._meta.get_field(field).clean(candidate, user)
            except ValidationError:
                plan["conflicts"].append(field + ":valor_invalido")
                blocking = True
                continue
            if current not in (None, ""):
                equal = phone_key(current) == phone_key(candidate) if field == "phone" else text_key(current) == text_key(candidate)
                if not equal:
                    plan["conflicts"].append(field + ":valor_local_conservado")
                    if field in ("id_personal", "employee_number", "phone"):
                        blocking = True
                continue
            if field in ("id_personal", "employee_number") and User.objects.exclude(pk=user.pk).filter(**{field: candidate}).exists():
                plan["conflicts"].append(field + ":ya_asociado")
                blocking = True
            else:
                plan["proposed_changes"][field] = candidate
        organization_identity = {**identity, "email": identity.get("email") or user.email,
                                 "username": user.username}
        index = OrganizationIndex(lock=transaction.get_connection().in_atomic_block)
        organization = index.enrich(organization_identity)
        plan["matched_identity"] = organization
        plan["conflicts"].extend(organization["organization_conflicts"])
        unit = organization.get("organizational_unit")
        if unit and not organization["organization_conflicts"]:
            unit_id = next(pk for pk, value in index.units.items() if value.code == unit["code"])
            if user.organizational_unit_id is None:
                plan["proposed_changes"]["organizational_unit_id"] = unit_id
            elif user.organizational_unit_id != unit_id:
                plan["conflicts"].append("organizational_unit:valor_local_conservado")
        plan["can_apply"] = not blocking
        return plan
    except Exception:
        plan["conflicts"].append("fuente_no_disponible")
        return plan


@transaction.atomic
def apply_user_institutional_sync(user, plan=None, *, actor):
    """Discard supplied plans and rebuild under lock immediately before saving."""
    if not (actor.is_authenticated and (actor.pk == user.pk or user_has_role(actor, {"ADMIN", "SUPERVISOR"}))):
        raise PermissionDenied
    locked = User.objects.select_for_update().get(pk=user.pk)
    result = build_user_institutional_sync_plan(locked)
    if not result["can_apply"] or not result["proposed_changes"]:
        return result
    for field, value in result["proposed_changes"].items():
        setattr(locked, field, value)
    locked.save(update_fields=list(result["proposed_changes"]))
    record_sync_activity(locked, actor, result["proposed_changes"])
    for field in result["proposed_changes"]:
        setattr(user, field, getattr(locked, field))
    if "organizational_unit_id" in result["proposed_changes"]:
        user._state.fields_cache.pop("organizational_unit", None)
    return result


def record_sync_activity(user, actor, changes):
    ActivityLog.objects.create(user=actor, action=ActivityLog.ACTION_UPDATE, module="accounts",
        object_type="User", object_id=str(user.pk),
        description="Sincronización institucional. Campos completados: " + ", ".join(sorted(changes)))


def try_sync_user_institutional_data(user, *, actor):
    """Controlled login/admin hooks. Failures never escape into those workflows."""
    try:
        # Fully populated accounts need neither external reads nor duplicate writes.
        if all(getattr(user, field) not in (None, "") for field in SYNC_FIELDS):
            if user.organizational_unit_id:
                return None
            mapped = OrganizationIndex().enrich({"id_personal": user.id_personal,
                                                 "email": user.email, "username": user.username})
            if not mapped.get("organizational_unit") or mapped["organization_conflicts"]:
                return None
        result = apply_user_institutional_sync(user, actor=actor)
        if "fuente_no_disponible" in result["conflicts"]:
            logging.getLogger(__name__).warning("Institutional sync unavailable; normal workflow continues.")
        return result
    except Exception as exc:
        logging.getLogger(__name__).warning("Institutional sync failed (%s); normal workflow continues.", type(exc).__name__)
        return None
