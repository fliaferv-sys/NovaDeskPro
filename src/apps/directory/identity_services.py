import csv
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Q

from apps.accounts.models import User
from apps.directory.ad_services import (
    ActiveDirectoryError,
    get_ad_user_by_email,
    search_ad_users,
    search_ad_users_by_emails,
)
from apps.directory.services import (
    DirectoryDatabaseError,
    get_directory_employee_by_id_personal,
    get_directory_employees,
    search_directory_employees,
)
from apps.institution.identity_organization import enrich_organization, organization_scope


class InstitutionalIdentityError(Exception):
    pass


SOURCE_RRHH = "RRHH"
SOURCE_ACTIVE_DIRECTORY = "ACTIVE_DIRECTORY"
SOURCE_LOCAL = "LOCAL"


DIRECTORY_DEFAULT_LIMIT = 5000

LINK_PERMANENT = "PERMANENT"
LINK_CONTRACTED = "CONTRACTED"
LINK_OUTSOURCED = "OUTSOURCED"
LINK_OTHER = "OTHER"

_VINCULO_FIRST_WORD = {
    "permanente": LINK_PERMANENT,
    "contratado": LINK_CONTRACTED,
    "tercerizado": LINK_OUTSOURCED,
}


def _normalize_vinculo_token(value):
    """Normaliza un vínculo de RR.HH. para comparar sin depender de
    mayúsculas, minúsculas ni espacios sobrantes."""
    if value is None:
        return ""
    return " ".join(str(value).split()).casefold()


def classify_rrhh_vinculo(vinculo):
    """Clasifica el vínculo de RR.HH. en las cuatro categorías de los KPI.

    La comparación es robusta: ignora mayúsculas/minúsculas, colapsa espacios
    y toma la primera palabra, de modo que variantes como ``"PERMANENTE "``,
    ``"Permanente  (Ley 15)"`` o ``"Contratado"`` se clasifican igual.
    Cualquier otro vínculo (comisionado, pasante, etc.) cae en "OTROS".
    """
    normalized = _normalize_vinculo_token(vinculo)
    if not normalized:
        return LINK_OTHER

    first_word = normalized.split(" ")[0]
    return _VINCULO_FIRST_WORD.get(first_word, LINK_OTHER)


def build_institutional_kpis(identities):
    """Calcula los KPI institucionales sobre el listado completo de RR.HH."""
    counts = {
        LINK_PERMANENT: 0,
        LINK_CONTRACTED: 0,
        LINK_OUTSOURCED: 0,
        LINK_OTHER: 0,
    }

    for identity in identities or ():
        counts[classify_rrhh_vinculo(identity.get("employment_type"))] += 1

    return {
        "total": len(identities or ()),
        "permanent": counts[LINK_PERMANENT],
        "contracted": counts[LINK_CONTRACTED],
        "outsourced": counts[LINK_OUTSOURCED],
        "other": counts[LINK_OTHER],
    }


@organization_scope
def get_institutional_directory(limit=DIRECTORY_DEFAULT_LIMIT):
    """RRHH base list enriched only by safely corresponding AD identities."""
    rows = get_directory_employees(limit=limit)
    rrhh = [_normalize_rrhh_employee(row) for row in rows]
    anchors = list(User.objects.filter(id_personal__in=[row["id_personal"] for row in rrhh if row["id_personal"] is not None]))
    try:
        ad = search_ad_users_by_emails([row["email"] for row in rrhh] + [user.email for user in anchors])
    except ActiveDirectoryError:
        ad = []
    return _directory_consolidation(rrhh, [_normalize_ad_user(user) for user in ad], anchors, include_local=False)


@organization_scope
def _directory_consolidation(rrhh, ad, local_users=(), *, include_local=True):
    """Adapt the legacy directory contract to the shared safe identity merges."""
    identities = []
    for identity in rrhh + ad:
        item = identity.copy()
        item["full_name"] = item["name"]
        item["rrhh_id"] = item.get("id_personal")
        item["_locator"] = ({"source": SOURCE_RRHH, "id": item["id_personal"]} if item["source"] == SOURCE_RRHH
                            else {"source": SOURCE_ACTIVE_DIRECTORY, "username": item["username"], "email": item["email"]})
        if item["source"] == SOURCE_RRHH and not item.get("email"):
            anchors = [user for user in local_users if user.id_personal and user.id_personal == item["id_personal"]]
            if len(anchors) == 1:
                anchor = anchors[0]
                matches = [other for other in ad if anchor.email and anchor.username
                    and other.get("email", "").strip().casefold() == anchor.email.strip().casefold()
                    and other.get("username", "").casefold() == anchor.username.casefold()]
                if len(matches) == 1:
                    item["email"] = matches[0]["email"]
                    item["_directory_original_email"] = ""
        identities.append(item)
    for user in local_users if include_local else ():
        item = _normalize_local_user(user)
        item.update(full_name=item["name"], rrhh_id=item.get("id_personal"), local_user_id=str(user.pk),
                    _locator={"source": SOURCE_LOCAL, "id": str(user.pk)})
        identities.append(item)
    original = {repr(item["_locator"]): index for index, item in enumerate(identities)}
    institutional = consolidate_institutional_identities([item for item in identities if item["source"] != SOURCE_LOCAL])
    for item in institutional:
        if "_directory_original_email" in item and not item.get("_consolidated"):
            item["email"] = item["_directory_original_email"]
    protected = [item for item in institutional if item["source"] == SOURCE_RRHH and not item.get("_consolidated")]
    merged = protected + _merge_linked_identities([item for item in institutional if item not in protected]
        + [item for item in identities if item["source"] == SOURCE_LOCAL])
    merged.sort(key=lambda item: min(original.get(repr(locator), len(original)) for locator in
        [item["_locator"], *(item.get("_linked") or [])]))
    result = []
    for item in merged:
        sources = item.get("sources") or sorted({loc["source"] for loc in item.get("_linked", [])}) or [item["source"]]
        item["sources"] = sources
        item["source_label"] = " + ".join({SOURCE_RRHH: "RR.HH.", SOURCE_ACTIVE_DIRECTORY: "AD", SOURCE_LOCAL: "NovaDesk"}.get(source, source) for source in sources)
        if item["source"] == SOURCE_ACTIVE_DIRECTORY and item.get("email") and not item.get("employment_type"):
            item["employment_type"] = "Tercerizado"
        # Internal locators/identifiers are never part of the directory display contract.
        enriched = _enrich_with_organizational_unit(item)
        result.append({key: value for key, value in enriched.items() if not key.startswith("_") and key not in {"local_user_id", "rrhh_id"}})
    return result


def _enrich_with_organizational_unit(identity):
    return enrich_organization(identity)


def _build_employee_photo_url(employee_number):
    employee_number = str(employee_number or "").strip()
    if not employee_number:
        return ""

    media_dir = Path(settings.MEDIA_ROOT) / "funcionarios"

    for extension in (".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"):
        file_name = f"{employee_number}F{extension}"
        if (media_dir / file_name).exists():
            return f"{settings.MEDIA_URL}funcionarios/{file_name}"

    return ""


@lru_cache(maxsize=1)
def _load_tercerizados():
    csv_path = Path(__file__).resolve().parent / "data" / "tercerizados.csv"

    if not csv_path.exists():
        return {}

    terceros = {}

    try:
        with csv_path.open(
            mode="r",
            encoding="utf-8-sig",
            newline="",
        ) as file:
            reader = csv.DictReader(file)

            for row in reader:
                email = str(row.get("CorreoAD") or "").strip().casefold()
                username = str(row.get("UsuarioAD") or "").strip().casefold()

                data = {
                    "ci": str(row.get("CI") or "").strip(),
                    "photo_file": str(row.get("ArchivoFoto") or "").strip(),
                }

                if email:
                    terceros[f"email:{email}"] = data

                if username:
                    terceros[f"username:{username}"] = data

    except (OSError, csv.Error):
        return {}

    return terceros


def _get_tercerizado(user):
    terceros = _load_tercerizados()

    email = str(user.get("email") or "").strip().casefold()
    username = str(user.get("username") or "").strip().casefold()

    if email:
        tercero = terceros.get(f"email:{email}")
        if tercero:
            return tercero

    if username:
        tercero = terceros.get(f"username:{username}")
        if tercero:
            return tercero

    return None


def _build_tercerizado_photo_url(tercero):
    if not tercero:
        return ""

    file_name = str(tercero.get("photo_file") or "").strip()

    if not file_name:
        return ""

    # Solo aceptar el nombre de archivo, nunca una ruta externa.
    if Path(file_name).name != file_name:
        return ""

    photo_path = Path(settings.MEDIA_ROOT) / "funcionarios" / file_name

    if not photo_path.exists():
        return ""

    return f"{settings.MEDIA_URL}funcionarios/{file_name}"


def get_user_photo_url(user, *, identity=None):
    """Resolve an existing institutional photo without saving a user image."""
    if getattr(user, "profile_image", None):
        return user.profile_image.url
    employee_number = str(
        getattr(user, "employee_number", "") or ""
    ).strip()

    photo_url = _build_employee_photo_url(employee_number)

    if photo_url:
        return photo_url

    # Optional already-resolved identity avoids additional institutional queries.
    if identity:
        photo_url = _build_employee_photo_url(identity.get("employee_number") or "")
        if photo_url:
            return photo_url
        if identity.get("photo_url"):
            return identity["photo_url"]

    tercero = _get_tercerizado({
        "email": getattr(user, "email", "") or "",
        "username": getattr(user, "username", "") or "",
    })

    return _build_tercerizado_photo_url(tercero)


def _normalize_rrhh_employee(employee):
    return {
        "source": SOURCE_RRHH,
        "id_personal": employee.get("IdPersonal"),
        "employee_number": employee.get("LegajoNro") or "",
        "name": employee.get("NombresApellidos") or "",
        "first_name": "",
        "last_name": "",
        "email": employee.get("Mail") or "",
        "phone": employee.get("Telefono") or "",
        "location": employee.get("Ubicacion") or "",
        "position": employee.get("Cargo") or "",
        "employment_type": employee.get("Vinculo") or "",
        "status": employee.get("Estado") or "",
        "username": "",
        "is_active": employee.get("Estado") == "Activo",
        "photo_url": _build_employee_photo_url(employee.get("LegajoNro") or ""),
    }


def _normalize_ad_user(user):
    is_active = bool(user.get("is_active", False))
    tercero = _get_tercerizado(user)

    return {
        "is_person": user.get("is_person"),
        "is_technical": bool(user.get("is_technical", False)),
        "is_shared": bool(user.get("is_shared", False)),
        "source": SOURCE_ACTIVE_DIRECTORY,
        "id_personal": None,
        "employee_number": "",
        "name": user.get("name") or "",
        "first_name": user.get("first_name") or "",
        "last_name": user.get("last_name") or "",
        "email": user.get("email") or "",
        "phone": "",
        "location": "",
        "position": "",
        "employment_type": "Tercerizado" if tercero else "",
        "status": "Activo" if is_active else "Inactivo",
        "username": user.get("username") or "",
        "is_active": is_active,
        "photo_url": _build_tercerizado_photo_url(tercero),
    }

def _normalize_local_user(user):
    employment_type_display = getattr(
        user,
        "get_employment_type_display",
        None,
    )
    employment_type = (
        employment_type_display()
        if callable(employment_type_display)
        else ""
    )
    unit = getattr(user, "organizational_unit", None)
    branch = getattr(user, "branch", None)

    return {
        "source": SOURCE_LOCAL,
        "id_personal": user.id_personal,
        "employee_number": user.employee_number or "",
        "name": user.get_full_name().strip() or user.email or "",
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "email": user.email or "",
        "phone": user.phone or "",
        "location": "",
        "_local_unit_id": unit.pk if unit else None,
        "branch": {"code": branch.code, "name": branch.name} if branch else None,
        "position": user.position or "",
        "employment_type": employment_type or "",
        "status": "Activo" if user.is_active else "Inactivo",
        "username": user.username or "",
        "is_active": user.is_active,
        "photo_url": _build_employee_photo_url(user.employee_number or ""),
    }


@organization_scope
def resolve_institutional_identity(*, id_personal=None, email=None, local_user=None):
    try:
        if id_personal is not None:
            try:
                employee = get_directory_employee_by_id_personal(id_personal)
            except DirectoryDatabaseError:
                employee = None
            if employee and email and employee.get("Mail") and employee["Mail"].strip().casefold() != email.strip().casefold():
                raise InstitutionalIdentityError("El identificador y el correo son contradictorios.")
            if employee:
                return _enrich_with_organizational_unit(
                    _normalize_rrhh_employee(employee)
                )

        normalized_email = email.strip() if isinstance(email, str) else ""
        if normalized_email:
            try:
                employees = search_directory_employees(
                    normalized_email,
                    limit=20,
                )
            except DirectoryDatabaseError:
                employees = []

            normalized_email_key = normalized_email.casefold()
            exact_employees = [employee for employee in employees or []
                               if str(employee.get("Mail") or "").strip().casefold() == normalized_email_key]
            if len(exact_employees) > 1 or len(employees) >= 20:
                raise InstitutionalIdentityError("El correo institucional es ambiguo o incompleto.")
            if len(exact_employees) == 1:
                return _enrich_with_organizational_unit(_normalize_rrhh_employee(exact_employees[0]))

            try:
                ad_user = get_ad_user_by_email(normalized_email)
            except ActiveDirectoryError:
                ad_user = None
            if ad_user:
                return _enrich_with_organizational_unit(
                    _normalize_ad_user(ad_user)
                )

        if local_user is not None:
            return _enrich_with_organizational_unit(
                _normalize_local_user(local_user)
            )

        if normalized_email:
            local_user = User.objects.filter(
                email__iexact=normalized_email,
            ).first()
            if local_user:
                return _enrich_with_organizational_unit(
                    _normalize_local_user(local_user)
                )

        return None
    except Exception as exc:
        raise InstitutionalIdentityError(
            "No fue posible resolver la identidad institucional."
        ) from exc


@organization_scope
def resolve_identity_for_user(user):
    """Read-only account enrichment uses the same confirmed matching as sync."""
    if user is None:
        raise ValueError("user no puede ser None.")
    from apps.accounts.institutional_sync import resolve_sync_identity
    try:
        identity, evidence, conflicts = resolve_sync_identity(user)
    except Exception:
        identity = None
    if identity:
        identity["username"] = user.username
        identity["email"] = identity.get("email") or user.email
        identity["_local_unit_id"] = user.organizational_unit_id
        if user.branch_id:
            identity["branch"] = {"code": user.branch.code, "name": user.branch.name}
        identity["source_label"] = " + ".join({SOURCE_RRHH: "RR.HH.", SOURCE_ACTIVE_DIRECTORY: "AD"}.get(source, source) for source in identity["sources"])
        return _enrich_with_organizational_unit(identity)
    return _enrich_with_organizational_unit(_normalize_local_user(user))


@organization_scope
def search_institutional_identities(query="", limit=20):
    if not isinstance(query, str):
        raise ValueError("query debe ser una cadena.")
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= 100
    ):
        raise ValueError("limit debe ser un entero entre 1 y 100.")

    query = query.strip()
    if len(query) < 2:
        return []

    try:
        try:
            rrhh_employees = search_directory_employees(query, limit=limit)
        except DirectoryDatabaseError:
            rrhh_employees = []
        rrhh = [_normalize_rrhh_employee(employee) for employee in rrhh_employees or []]

        try:
            ad_users = search_ad_users(query, limit=limit)
        except ActiveDirectoryError:
            ad_users = []
        ad = [_normalize_ad_user(user) for user in ad_users or []]

        local_filter = (
            Q(email__icontains=query)
            | Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(employee_number__icontains=query)
        )
        if query.isdecimal():
            local_filter |= Q(id_personal=int(query))

        local_users = list(User.objects.filter(local_filter).select_related("organizational_unit", "branch").distinct()[:limit])
        missing_ids = [item["id_personal"] for item in rrhh if not item["email"] and item["id_personal"] is not None]
        anchors = list(User.objects.filter(id_personal__in=missing_ids)) if missing_ids else []
        try:
            extra = search_ad_users_by_emails([item["email"] for item in rrhh] + [user.email for user in anchors])
        except ActiveDirectoryError:
            extra = []
        for user in extra:
            normalized = _normalize_ad_user(user)
            if normalized not in ad:
                ad.append(normalized)
        for user in anchors:
            if user not in local_users:
                local_users.append(user)
        return _directory_consolidation(rrhh, ad, local_users)[:limit]
    except Exception as exc:
        raise InstitutionalIdentityError(
            "No fue posible buscar identidades institucionales."
        ) from exc







class AmbiguousInstitutionalIdentity(InstitutionalIdentityError):
    """More than one record in an institutional source shares an email."""


def find_institutional_identity_by_email(email):
    """Compatibility adapter for the legacy email-only Admin endpoint."""
    result = search_common_identities(email.strip().casefold(), "email", exact=True)
    if result["incomplete"]:
        raise InstitutionalIdentityError("No fue posible confirmar la identidad institucional.")
    if len(result["identities"]) > 1:
        raise AmbiguousInstitutionalIdentity("Hay coincidencias ambiguas para ese correo.")
    if not result["identities"]:
        return None
    identity = result["identities"][0]
    legacy = {key: value for key, value in identity.items() if not key.startswith("_")}
    legacy["id_personal"] = identity["rrhh_id"]
    legacy["employment_type"] = identity["employment_relationship"]
    if not legacy.get("document_number"):
        legacy.pop("document_number", None)
    return legacy


# Common identity contract. Legacy directory consumers keep their existing schema.
IDENTITY_SEARCH_FIELDS = frozenset({"email", "username", "employee_number", "document_number", "name"})
IDENTITY_RESULT_LIMIT = 20
SOURCE_OUTSOURCED = "TERCERIZADOS"


def normalize_identity_employment(value):
    """One classification entry point for forms and API consumers."""
    value = str(value or "").strip()
    if not value:
        return ""
    labels = {str(label).casefold(): code for code, label in User.EmploymentType.choices}
    return labels.get(value.casefold(), {
        "pasante": User.EmploymentType.INTERN,
        "consultor": User.EmploymentType.CONSULTANT,
        "proveedor externo": User.EmploymentType.EXTERNAL_PROVIDER,
    }.get(value.casefold(), classify_rrhh_vinculo(value)))


def _common_identity(identity, locator, local_user=None, document_number=""):
    identity = _enrich_with_organizational_unit(identity)
    relationship = str(identity.get("employment_type") or "").strip()
    result = {
        key: str(identity.get(key) or "").strip()
        for key in ("name", "first_name", "last_name", "email", "username", "employee_number", "phone", "position", "location", "photo_url", "source")
    }
    result.update(
        full_name=result["name"],
        document_number=str(document_number or "").strip(),
        employment_relationship=relationship,
        employment_type=normalize_identity_employment(relationship),
        organizational_unit=identity.get("organizational_unit"),
        organizational_path=identity.get("organizational_path", []),
        branch=identity.get("branch"),
        status=identity.get("status"),
        source_label=identity.get("source_label") or {SOURCE_RRHH: "RR.HH.", SOURCE_ACTIVE_DIRECTORY: "AD", SOURCE_LOCAL: "NovaDesk"}.get(identity.get("source"), identity.get("source")),
        organization_conflicts=identity.get("organization_conflicts", []),
        _local_unit_id=identity.get("_local_unit_id"),
        local_user_id=str(local_user.pk) if local_user else None,
        rrhh_id=identity.get("id_personal"),
        _locator=locator,
        is_active=identity.get("is_active"),
        is_person=identity.get("is_person"),
        is_technical=bool(identity.get("is_technical", False)),
        is_shared=bool(identity.get("is_shared", False)),
    )
    return result


def _outsourced_records():
    """Recover searchable mapping keys without reading a second personal-data file."""
    mapping = _load_tercerizados()
    groups = {}
    for key, record in mapping.items():
        groups.setdefault(id(record), []).append((key, record))
    for entries in groups.values():
        emails = [key[6:] for key, _ in entries if key.startswith("email:")]
        usernames = [key[9:] for key, _ in entries if key.startswith("username:")]
        # Do not collapse conflicting aliases into a unique account.
        for key, record in entries:
            if emails and not key.startswith("email:"):
                continue
            yield {
                "email": key[6:] if key.startswith("email:") else "",
                "username": usernames[0] if len(usernames) == 1 else "",
                "ci": record.get("ci") or "",
                "record": record,
                "key": key,
            }


def _mapping_identity(row):
    identity = _normalize_ad_user(row)
    identity["is_active"] = None  # Mapping alone has no activity status.
    identity["source"] = SOURCE_OUTSOURCED
    identity["employment_type"] = "Tercerizado"
    identity["photo_url"] = _build_tercerizado_photo_url(row["record"])
    return _common_identity(identity, {"source": SOURCE_OUTSOURCED, "key": row["key"]}, document_number=row["ci"])


def _identity_matches(identity, field, query, exact=False):
    values = [identity.get(field) or ""]
    if field == "name":
        values = [identity.get("full_name") or "", " ".join(filter(None, [identity.get("first_name"), identity.get("last_name")]))]
    query = " ".join(query.split()).casefold()
    return any((" ".join(str(value).split()).casefold() == query if exact else query in " ".join(str(value).split()).casefold()) for value in values if value)


def _merge_linked_identities(identities):
    """Merge only through explicit RRHH/local links or email AND username.

    Matching email alone is never evidence to collapse institutional records.
    Conflicting identifiers and duplicate source records remain candidates.
    """
    result = list(identities)
    for local in [item for item in identities if item["source"] == SOURCE_LOCAL]:
        linked = []
        for source in (SOURCE_RRHH, SOURCE_ACTIVE_DIRECTORY, SOURCE_OUTSOURCED):
            matches = []
            for item in result:
                if item["source"] != source:
                    continue
                same_email = bool(local["email"] and local["email"].casefold() == item["email"].casefold())
                if source == SOURCE_RRHH:
                    safe = bool(local["rrhh_id"] and local["rrhh_id"] == item["rrhh_id"] and (same_email or not item["email"]))
                else:
                    safe = same_email and bool(local["username"] and local["username"].casefold() == item["username"].casefold())
                if safe and not any(local.get(key) and item.get(key) and str(local.get(key)).casefold() != str(item.get(key)).casefold() for key in ("document_number", "employee_number")):
                    matches.append(item)
            if len(matches) == 1:
                linked.extend(matches)
        if not linked:
            continue
        # A local anchor cannot make conflicting institutional identifiers agree.
        if any(len({str(item.get(key)).strip().casefold() for item in linked + [local] if item.get(key)}) > 1
               for key in ("rrhh_id", "employee_number", "document_number")):
            continue
        primary = next((item for item in linked if item["source"] == SOURCE_RRHH), linked[0])
        merged = primary.copy()
        for item in linked + [local]:
            for key, value in item.items():
                if not key.startswith("_") and not merged.get(key) and value:
                    merged[key] = value
        known_activity = [item.get("is_active") for item in linked if item.get("is_active") is not None]
        merged["is_active"] = all(known_activity) if known_activity else None
        merged["is_technical"] = any(item.get("is_technical") for item in linked)
        merged["is_shared"] = any(item.get("is_shared") for item in linked)
        merged["is_person"] = False if any(item.get("is_person") is False for item in linked) else primary.get("is_person")
        merged["sources"] = sorted({locator["source"] for item in linked + [local] for locator in [item["_locator"], *(item.get("_linked") or [])]})
        merged["local_user_id"] = local["local_user_id"]
        merged["_locator"] = {"source": SOURCE_LOCAL, "id": local["local_user_id"]}
        merged["_linked"] = [locator for item in linked for locator in
                             [item["_locator"], *(item.get("_linked") or [])]]
        merged["_local_unit_id"] = local.get("_local_unit_id")
        if local in result:
            result.remove(local)
        for item in linked:
            result.remove(item)
        result.append(merged)
    return result


def consolidate_institutional_identities(identities):
    """Read-only RRHH/AD consolidation. Does not alter signed selection flows."""
    from collections import defaultdict
    import unicodedata
    from django.core.validators import validate_email

    def normalized(value):
        text = unicodedata.normalize("NFD", str(value or ""))
        return " ".join("".join(c for c in text if not unicodedata.combining(c)).split()).casefold()

    groups, result = defaultdict(list), []
    for identity in identities:
        email = str(identity.get("email") or "").strip().casefold()
        try:
            validate_email(email)
            valid = email.rsplit("@", 1)[-1] == settings.DIRECTORY_AD_DOMAIN.casefold()
        except ValidationError:
            valid = False
        if valid and identity.get("source") in {SOURCE_RRHH, SOURCE_ACTIVE_DIRECTORY}:
            groups[email].append(identity)
        else:
            result.append(identity)
    for email, members in groups.items():
        sources = [item["source"] for item in members]
        safe = len(members) == 2 and set(sources) == {SOURCE_RRHH, SOURCE_ACTIVE_DIRECTORY}
        account = email.split("@", 1)[0]
        usernames = {str(item.get("username") or "").strip().casefold() for item in members if item.get("username")}
        shared_id = any(len({normalized(item.get(key)) for item in members if item.get(key)}) == 1
                        and all(item.get(key) for item in members)
                        for key in ("rrhh_id", "employee_number", "document_number"))
        safe &= bool(usernames == {account} or (not usernames and shared_id))
        # Missing complementary fields are fine; contradicting populated fields
        # and duplicate records from one source are never silently collapsed.
        for key in ("rrhh_id", "employee_number", "document_number", "local_user_id", "full_name", "name",
                    "position", "phone", "location", "organizational_unit"):
            values = {normalized(item.get(key)) for item in members if item.get(key)}
            if len(values) > 1:
                safe = False
        for flag in ("is_active", "is_person", "is_shared", "is_technical"):
            known = {item[flag] for item in members if item.get(flag) is not None}
            if len(known) > 1:
                safe = False
        if not safe:
            result.extend(members)
            continue
        rrhh = next(item for item in members if item["source"] == SOURCE_RRHH)
        ad = next(item for item in members if item["source"] == SOURCE_ACTIVE_DIRECTORY)
        merged = rrhh.copy()
        for key, value in ad.items():
            if not key.startswith("_") and merged.get(key) in (None, "", [], {}):
                merged[key] = value
        merged["username"] = ad.get("username") or rrhh.get("username") or ""
        merged["email"] = email
        merged["sources"] = sorted(set(sources))
        merged["_linked"] = [item["_locator"] for item in members]
        merged["_consolidated"] = True
        result.append(merged)
    return result


@organization_scope
def search_common_identities(query, field="email", *, exact=False):
    """Bounded searches with explicit completeness and ambiguity information."""
    if field not in IDENTITY_SEARCH_FIELDS or not isinstance(query, str):
        raise ValueError("Búsqueda de identidad inválida.")
    query = query.strip()
    if not 2 <= len(query) <= 254:
        raise ValueError("La búsqueda debe tener entre 2 y 254 caracteres.")
    limit = IDENTITY_RESULT_LIMIT + 1
    identities = []
    incomplete = False
    rrhh_queries = [(query, field)] if field in {"email", "employee_number", "name"} else []
    ad_queries = [(query, field)] if field in {"email", "username", "name"} else []
    mappings = list(_outsourced_records())
    relevant_mappings = [row for row in mappings if _identity_matches({"document_number": row["ci"], "email": row["email"], "username": row["username"]}, field, query, exact)]
    if field == "document_number" and len(relevant_mappings) == 1:
        # Avoid one AD roundtrip per candidate for broad partial CI searches.
        # The current RRHH view has no CI column. Use mapping keys to reach AD.
        ad_queries += [(row["username"], "username") if row["username"] else (row["email"], "email") for row in relevant_mappings[:limit] if row["username"] or row["email"]]
    try:
        for term, rrhh_field in rrhh_queries:
            rows = search_directory_employees(term, limit=limit, search_field=rrhh_field, exact=exact)
            incomplete |= len(rows) >= limit
            for row in rows:
                identity = _normalize_rrhh_employee(row)
                identities.append(_common_identity(identity, {"source": SOURCE_RRHH, "id": row.get("IdPersonal")}))
    except DirectoryDatabaseError:
        incomplete = True
    try:
        for term, ad_field in ad_queries:
            rows = search_ad_users(term, limit=limit, search_field=ad_field, exact=exact or field == "document_number")
            incomplete |= len(rows) >= limit
            for row in rows:
                tercero = _get_tercerizado(row)
                identities.append(_common_identity(_normalize_ad_user(row), {"source": SOURCE_ACTIVE_DIRECTORY, "username": row.get("username") or "", "email": row.get("email") or ""}, document_number=(tercero or {}).get("ci", "")))
    except ActiveDirectoryError:
        incomplete = True
    # A mapping enriches an AD record only when BOTH account keys agree.
    for row in relevant_mappings[:limit]:
        matches = [item for item in identities if item["source"] == SOURCE_ACTIVE_DIRECTORY and row["email"] and row["username"] and item["email"].casefold() == row["email"].casefold() and item["username"].casefold() == row["username"].casefold()]
        if len(matches) != 1:
            identities.append(_mapping_identity(row))
    incomplete |= len(relevant_mappings) >= limit
    lookup = "iexact" if exact else "icontains"
    if field == "name":
        from django.db.models.functions import Concat
        from django.db.models import Value
        users = User.objects.annotate(identity_full_name=Concat("first_name", Value(" "), "last_name")).filter(**{f"identity_full_name__{lookup}": query})
    else:
        users = User.objects.filter(**{f"{field}__{lookup}": query})
    local_users = list(users.select_related("department", "organizational_unit", "branch")[:limit])
    incomplete |= len(local_users) >= limit
    for user in local_users:
        identities.append(_common_identity(_normalize_local_user(user), {"source": SOURCE_LOCAL, "id": str(user.pk)}, user, user.document_number))
    links = Q(pk__in=[])
    for item in identities:
        if item["source"] == SOURCE_RRHH and item["rrhh_id"]:
            links |= Q(id_personal=item["rrhh_id"])
        elif item["source"] in {SOURCE_ACTIVE_DIRECTORY, SOURCE_OUTSOURCED} and item["email"] and item["username"]:
            links |= Q(email__iexact=item["email"], username__iexact=item["username"])
    for user in User.objects.filter(links).select_related("organizational_unit", "branch"):
        if not any(candidate.get("local_user_id") == str(user.pk) for candidate in identities):
            identities.append(_common_identity(_normalize_local_user(user), {"source": SOURCE_LOCAL, "id": str(user.pk)}, user, user.document_number))
    identities = _merge_linked_identities(identities)
    identities = consolidate_institutional_identities(identities)
    for item in identities:
        item.update(_enrich_with_organizational_unit(item))
        sources = item.get("sources") or [item["source"]]
        item["source_label"] = " + ".join({SOURCE_RRHH: "RR.HH.", SOURCE_ACTIVE_DIRECTORY: "AD", SOURCE_LOCAL: "NovaDesk"}.get(source, source) for source in sources)
    identities = [item for item in identities if _identity_matches(item, field, query, exact)]
    exact_matches = [item for item in identities if _identity_matches(item, field, query, True)]
    incomplete |= len(identities) > IDENTITY_RESULT_LIMIT
    return {"identities": identities[:IDENTITY_RESULT_LIMIT], "incomplete": incomplete, "exact_unique": not incomplete and len(exact_matches) == 1, "exact_identity": exact_matches[0] if not incomplete and len(exact_matches) == 1 else None}


@organization_scope
def resolve_common_identity(locator, linked=None):
    """Re-read selected source keys. No posted personal fields are trusted."""
    source = locator.get("source")
    try:
        if source == SOURCE_LOCAL:
            user = User.objects.select_related("department", "organizational_unit", "branch").filter(pk=locator.get("id")).first()
            identity = _common_identity(_normalize_local_user(user), locator, user, user.document_number) if user else None
        elif source == SOURCE_RRHH:
            rows = search_directory_employees(str(locator.get("id") or ""), limit=2, search_field="rrhh_id", exact=True)
            rows = [row for row in rows if row.get("IdPersonal") == locator.get("id")]
            if len(rows) != 1:
                raise InstitutionalIdentityError("La identidad RRHH ya no es inequívoca.")
            identity = _common_identity(_normalize_rrhh_employee(rows[0]), locator)
        elif source == SOURCE_ACTIVE_DIRECTORY:
            field = "username" if locator.get("username") else "email"
            value = locator.get(field)
            rows = search_ad_users(value, limit=2, search_field=field, exact=True) if value else []
            rows = [row for row in rows if str(row.get("email") or "").casefold() == str(locator.get("email") or "").casefold()]
            if len(rows) != 1:
                raise InstitutionalIdentityError("La cuenta seleccionada ya no es inequívoca.")
            row = rows[0]
            identity = _common_identity(_normalize_ad_user(row), locator, document_number=(_get_tercerizado(row) or {}).get("ci", ""))
        elif source == SOURCE_OUTSOURCED:
            rows = [row for row in _outsourced_records() if row["key"] == locator.get("key")]
            identity = _mapping_identity(rows[0]) if len(rows) == 1 else None
            if identity and rows[0]["email"] and rows[0]["username"]:
                try:
                    accounts = search_ad_users(rows[0]["username"], limit=2, search_field="username", exact=True)
                except ActiveDirectoryError:
                    accounts = []
                if len(accounts) == 1 and str(accounts[0].get("email") or "").casefold() == rows[0]["email"].casefold():
                    account = _normalize_ad_user(accounts[0])
                    for key in ("name", "first_name", "last_name"):
                        identity[key] = account.get(key) or ""
                    identity["full_name"] = identity["name"]
                    identity["is_active"] = account.get("is_active")
                    identity["is_technical"] = account.get("is_technical", False)
                    identity["is_shared"] = account.get("is_shared", False)
                    identity["is_person"] = account.get("is_person")
        else:
            identity = None
        if identity is None:
            raise InstitutionalIdentityError("La identidad seleccionada ya no está disponible.")
        if linked:
            identities = [identity] + [resolve_common_identity(item) for item in linked if item != locator]
            merged = consolidate_institutional_identities(_merge_linked_identities(identities))
            if len(merged) != 1:
                raise InstitutionalIdentityError("El vínculo institucional cambió; seleccione nuevamente.")
            identity = merged[0]
        identity = _enrich_with_organizational_unit(identity)
        sources = identity.get("sources") or [identity["source"]]
        identity["source_label"] = " + ".join({SOURCE_RRHH: "RR.HH.", SOURCE_ACTIVE_DIRECTORY: "AD", SOURCE_LOCAL: "NovaDesk"}.get(value, value) for value in sources)
        return identity
    except (DirectoryDatabaseError, ActiveDirectoryError, ValueError, ValidationError) as exc:
        raise InstitutionalIdentityError("No fue posible validar la identidad seleccionada.") from exc
