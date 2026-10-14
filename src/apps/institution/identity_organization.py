"""Exact institutional assignments. No inference from location, name or Department."""
from collections import defaultdict
from contextvars import ContextVar
from functools import wraps

from .models import InstitutionalIdentityAssignment, OrganizationalUnit


_current = ContextVar("identity_organization", default=None)


def identifier_key(value):
    return str(value or "").strip().casefold()


class OrganizationIndex:
    def __init__(self, *, lock=False):
        assignments = InstitutionalIdentityAssignment.objects.filter(is_active=True)
        units = OrganizationalUnit.objects.all()
        if lock:
            assignments = assignments.select_for_update()
            units = units.select_for_update()
        self.units = {unit.pk: unit for unit in units}
        self.by_identifier = defaultdict(list)
        for assignment in assignments:
            for field in ("id_personal", "email", "username"):
                key = identifier_key(getattr(assignment, field))
                if key:
                    self.by_identifier[field, key].append(assignment)

    def unit_data(self, unit_id):
        path, seen = [], set()
        while unit_id is not None:
            unit = self.units.get(unit_id)
            if unit is None or not unit.is_active or unit_id in seen:
                return None, []
            seen.add(unit_id)
            path.append({"code": unit.code, "name": unit.name, "type": unit.unit_type,
                         "type_display": unit.get_unit_type_display()})
            unit_id = unit.parent_id
        path.reverse()
        return (path[-1] if path else None), path

    def enrich(self, identity):
        result = identity.copy()
        matches = {}
        for field in ("id_personal", "email", "username"):
            key = identifier_key(identity.get(field) if field != "id_personal" else
                                 identity.get("id_personal", identity.get("rrhh_id")))
            for assignment in self.by_identifier.get((field, key), []):
                matches[assignment.pk] = assignment
        conflict = len(matches) > 1
        assignment = next(iter(matches.values())) if len(matches) == 1 else None
        if assignment:
            for field in ("id_personal", "email", "username"):
                expected = identifier_key(getattr(assignment, field))
                actual = identifier_key(identity.get(field) if field != "id_personal" else
                                        identity.get("id_personal", identity.get("rrhh_id")))
                if expected and actual and expected != actual:
                    conflict = True
        mapped_id = assignment.organizational_unit_id if assignment and not conflict else None
        local_id = identity.get("_local_unit_id")
        if local_id and mapped_id and local_id != mapped_id:
            conflict = True
        # Local relationships are presentation data, never a substitute mapping.
        unit_id = local_id or (mapped_id if not conflict else None)
        unit, path = self.unit_data(unit_id)
        if unit_id and unit is None:
            conflict = True
        result.update(organizational_unit=unit, organizational_path=path,
                      organization_conflicts=["asignacion_institucional_inconsistente"] if conflict else [])
        return result


def organization_scope(function):
    """Two local queries per resolution, shared by nested source adapters."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        if _current.get() is not None:
            return function(*args, **kwargs)
        token = _current.set(OrganizationIndex())
        try:
            return function(*args, **kwargs)
        finally:
            _current.reset(token)
    return wrapped


def enrich_organization(identity):
    return (_current.get() or OrganizationIndex()).enrich(identity) if identity is not None else None
