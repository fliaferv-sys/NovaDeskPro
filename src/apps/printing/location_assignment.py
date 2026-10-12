"""Safe assignment plans; never create locations or infer missing branches."""
from collections import defaultdict

from django.core.management.base import CommandError

from apps.accounts.models import Branch
from apps.inventory.models import OrganizationalLocation
from .location_analysis import extract_fields, normalize_dependency, possible_match
from .models import PrintingDevice
from .printer_import import START_NOTES, BRANCH_ALIASES, PROVISIONAL_LOCATION_CODE

STATES = ("ACTUALIZADO", "SIN CAMBIOS", "PENDIENTE", "REVISAR", "ERROR")


def assignment_plan(lock=False):
    devices = PrintingDevice.objects.filter(notes__contains=START_NOTES).only(
        "pk", "notes", "branch_id", "organizational_location_id"
    ).order_by("pk")
    branches = Branch.objects.order_by("pk")
    locations = OrganizationalLocation.objects.order_by("pk")
    if lock:
        branches = branches.select_for_update()
        locations = locations.select_for_update()
        devices = devices.select_for_update()
    branch_map = {branch.pk: branch for branch in branches}
    location_map = {location.pk: location for location in locations}
    active = defaultdict(list)
    for location in location_map.values():
        if location.is_active and location.code != PROVISIONAL_LOCATION_CODE:
            active[location.branch_id].append(location)
    plans = []
    for device in devices:
        try:
            status, candidate, reason = classify(device, branch_map, location_map, active)
        except CommandError as exc:
            status, candidate, reason = "ERROR", None, str(exc)
        plans.append((device, status, candidate, reason))
    return plans


def classify(device, branches, locations, active):
    fields = extract_fields(device)
    branch = branches.get(device.branch_id)
    source = normalize_dependency(fields["Sede"])
    if not branch or not branch.is_active:
        return "REVISAR", None, "Sede guardada ausente o inactiva"
    expected = BRANCH_ALIASES.get(source)
    if not source or (expected != branch.code if expected else source not in {
            normalize_dependency(branch.name), normalize_dependency(branch.code)}):
        return "REVISAR", None, "Sede importada ausente o incompatible con branch guardado"
    current = locations.get(device.organizational_location_id)
    if current and current.branch_id != branch.pk:
        return "REVISAR", None, "Ubicacion actual pertenece a otra sede"
    dependency = normalize_dependency(fields["Dependencia"])
    if not dependency:
        return "PENDIENTE", None, "Sin dependencia importada"
    exact = [loc for loc in active[branch.pk] if normalize_dependency(loc.name) == dependency]
    possible = [loc for loc in active[branch.pk] if loc not in exact and possible_match(dependency, loc.name)]
    if current and current.code != PROVISIONAL_LOCATION_CODE and current not in exact:
        return "REVISAR", None, "Ubicacion real distinta; no se sobrescribe"
    if len(exact) > 1 or (exact and possible):
        return "REVISAR", None, "Coincidencia ambigua en la misma sede"
    if not exact:
        return ("REVISAR" if possible else "PENDIENTE"), None, (
            "Solo hay posibles coincidencias; requieren seleccion manual" if possible
            else "No existe ubicacion activa exacta en la misma sede")
    candidate = exact[0]
    if current and current.pk == candidate.pk:
        return "SIN CAMBIOS", candidate, "Ubicacion exacta ya asignada"
    return "ACTUALIZADO", candidate, f"Coincidencia exacta unica: {branch.name} - {candidate.name}"
