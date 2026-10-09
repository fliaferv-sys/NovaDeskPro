"""Read-only grouping and conservative comparison of printer dependencies."""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import re
import unicodedata

from django.core.management.base import CommandError

from apps.inventory.models import OrganizationalLocation
from .models import PrintingDevice
from .printer_import import START_NOTES, END_NOTES, PROVISIONAL_LOCATION_CODE, BRANCH_ALIASES

STATES = ("COINCIDENCIA EXACTA", "POSIBLE COINCIDENCIA", "NO EXISTE", "AMBIGUA", "SIN DEPENDENCIA")


def normalize_dependency(value):
    text = unicodedata.normalize("NFD", str(value or "").casefold())
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split())


def comparison_alias(value):
    value = normalize_dependency(value)
    return re.sub(r"\b(?:dpto|depto)\.?(?=\s|$)", "departamento", value)


def possible_match(left, right):
    left, right = comparison_alias(left), comparison_alias(right)
    if left == right:
        return True
    prefixes = ("oficina de ", "departamento de ", "direccion de ")
    return any(a.startswith(prefix) and a[len(prefix):] == b
               for a, b in ((left, right), (right, left)) for prefix in prefixes)


def extract_fields(device):
    notes = device.notes or ""
    if notes.count(START_NOTES) != 1 or notes.count(END_NOTES) != 1:
        raise CommandError(f"Bloque importado incompleto o duplicado en impresora {device.pk}; no se interpreta.")
    start = notes.index(START_NOTES) + len(START_NOTES)
    end = notes.index(END_NOTES)
    if end < start:
        raise CommandError(f"Marcadores en orden incorrecto en impresora {device.pk}.")
    result = {"Sede": "", "Dependencia": ""}
    found = set()
    for line in notes[start:end].splitlines():
        label, separator, value = line.partition(":")
        label = label.strip()
        if separator and label in result:
            if label in found:
                raise CommandError(f"Varias lineas {label} en impresora {device.pk}; no se elige una.")
            found.add(label)
            # Drop only the importer's separator space, preserving original text.
            result[label] = value[1:] if value.startswith(" ") else value
    return result


@dataclass
class DependencyGroup:
    branch: object
    normalized: str
    originals: set = field(default_factory=set)
    note_branches: set = field(default_factory=set)
    devices: list = field(default_factory=list)
    status: str = ""
    candidates: list = field(default_factory=list)
    warnings: set = field(default_factory=set)

    @property
    def branch_label(self):
        return f"{self.branch.name} [{self.branch.code}]" if self.branch else "SIN SEDE ASIGNADA"

    def csv_row(self):
        return {
            "sede": self.branch_label,
            "dependencia_original": " | ".join(sorted(self.originals)),
            "dependencia_normalizada": self.normalized,
            "cantidad_equipos": len(self.devices),
            "ids_fotocopiadora": " | ".join(d.photocopier_id or "Sin ID" for d in self.devices),
            "series": " | ".join(d.serial_number or "Sin serie" for d in self.devices),
            "ubicacion_actual": " | ".join(sorted({d.organizational_location.name if d.organizational_location else "Sin ubicacion" for d in self.devices})),
            "estado": self.status,
            "candidato_existente": " | ".join(f"{c.name} [{c.code}; {c.pk}]" for c in self.candidates),
        }


def analyze_locations():
    groups = {}
    devices = PrintingDevice.objects.filter(notes__contains=START_NOTES).select_related(
        "branch", "organizational_location",
    ).order_by("pk")
    locations = defaultdict(list)
    for location in OrganizationalLocation.objects.filter(is_active=True, branch__is_active=True).exclude(code=PROVISIONAL_LOCATION_CODE).select_related("branch"):
        locations[location.branch_id].append(location)
    for device in devices:
        values = extract_fields(device)
        normalized = normalize_dependency(values["Dependencia"])
        group = groups.setdefault((device.branch_id, normalized), DependencyGroup(device.branch, normalized))
        group.originals.add(values["Dependencia"])
        group.note_branches.add(values["Sede"])
        group.devices.append(device)
        source = normalize_dependency(values["Sede"])
        branch = device.branch
        expected = BRANCH_ALIASES.get(source)
        if not branch:
            group.warnings.add("Sin branch guardado: no se infiere sede desde notes ni se cruzan candidatos")
        elif not branch.is_active:
            group.warnings.add("Sede guardada inactiva: no se proponen candidatos")
        elif source and ((expected and expected != branch.code) or
                         (not expected and source not in {normalize_dependency(branch.name), normalize_dependency(branch.code)})):
            group.warnings.add("Sede de notes no coincide con branch guardado; requiere verificacion manual")
        if device.organizational_location and branch and device.organizational_location.branch_id != branch.pk:
            group.warnings.add("Ubicacion actual pertenece a otra sede; no se modifica")
    for group in groups.values():
        if not group.normalized:
            group.status = "SIN DEPENDENCIA"
            continue
        candidates = locations[group.branch.pk] if group.branch and group.branch.is_active else []
        exact = [loc for loc in candidates if normalize_dependency(loc.name) == group.normalized]
        possible = [loc for loc in candidates if loc not in exact and possible_match(group.normalized, loc.name)]
        compatible = exact + possible
        if len(compatible) > 1:
            group.status, group.candidates = "AMBIGUA", compatible
        elif exact:
            group.status, group.candidates = "COINCIDENCIA EXACTA", exact
        elif possible:
            group.status, group.candidates = "POSIBLE COINCIDENCIA", possible
        else:
            group.status = "NO EXISTE"
    return sorted(groups.values(), key=lambda g: (g.branch_label, g.normalized))


def analysis_summary(groups):
    counts = Counter(group.status for group in groups)
    return {
        "total_impresoras": sum(len(g.devices) for g in groups),
        "dependencias_unicas": sum(bool(g.normalized) for g in groups),
        **{state: counts[state] for state in STATES},
    }
