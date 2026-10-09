"""Conservative proposals using the existing read-only location analysis."""
from collections import Counter
from dataclasses import dataclass, field
import re

from .location_analysis import analyze_locations, comparison_alias, normalize_dependency

CLASSIFICATIONS = ("PROPUESTA CREAR", "REVISAR", "POSIBLE PERSONA", "POSIBLE DUPLICADO")
INSTITUTIONAL_WORDS = frozenset({
    "direccion", "departamento", "dpto", "depto", "gerencia", "secretaria",
    "unidad", "coordinacion", "division", "seccion", "laboratorio", "informatica",
    "auditoria", "asesoria", "presidencia", "administracion", "finanzas",
    "tesoreria", "almacenes", "patrimonio", "contabilidad", "facturacion",
    "mantenimiento", "cargadero", "comercializacion", "marketing", "licitaciones",
})
INSTITUTIONAL_PHRASES = frozenset({
    "recursos humanos", "programacion y evaluacion", "servicios generales",
    "control de cantidad", "control de calidad", "salud ocupacional", "seguridad industrial",
})
GENERIC_LABELS = frozenset({
    "direccion", "departamento", "dpto", "depto", "gerencia", "secretaria", "unidad",
    "coordinacion", "division", "seccion", "oficina", "general", "sector", "otro", "otros",
    "sin dato", "sin datos", "pendiente", "no aplica", "n/a", "s/n",
})
NAME_STARTS = frozenset({
    "ana", "ruth", "juan", "jose", "maria", "carlos", "luis", "roberto", "pedro",
    "marta", "carmen", "jorge", "miguel", "antonio", "laura", "patricia", "rosa",
    "andrea", "daniel", "david", "fernando", "ricardo", "elena", "teresa", "silvia",
})


def institutional_text(normalized):
    words = set(re.findall(r"[a-z]+", normalized))
    return bool(words & INSTITUTIONAL_WORDS or
                any(phrase in normalized for phrase in INSTITUTIONAL_PHRASES))


def possible_person(original):
    words = original.strip().split()
    return (2 <= len(words) <= 3 and normalize_dependency(words[0]) in NAME_STARTS
            and all(word.isalpha() and (word.istitle() or word.isupper()) for word in words))


def suspicious_text(normalized):
    return (not normalized or len(normalized) > 150 or comparison_alias(normalized) in GENERIC_LABELS
            or not any(char.isalpha() for char in normalized)
            or bool(re.search(r"[^a-z0-9 .()/_-]", normalized))
            or bool(re.search(r"\b(?:backup|prueba|test|temporal|pendiente)\b", normalized))
            or "@" in normalized
            or bool(re.search(r"\barea\b", normalized)))


@dataclass
class LocationProposal:
    group: object
    classification: str
    reason: str
    related: list = field(default_factory=list)

    def csv_row(self):
        base = self.group.csv_row()
        return {key: base[key] for key in (
            "sede", "dependencia_original", "dependencia_normalizada", "cantidad_equipos",
            "ids_fotocopiadora", "series", "ubicacion_actual",
        )} | {"clasificacion": self.classification, "motivo": self.reason,
             "candidato_relacionado": " | ".join(self.related)}


def propose_locations():
    groups = analyze_locations()
    proposals = []
    for group in groups:
        normalized = group.normalized
        related = []
        variants = sorted({text.strip() for text in group.originals})
        if len(variants) > 1:
            related.extend(variants)
        for other in groups:
            if other is not group and other.branch == group.branch and comparison_alias(other.normalized) == comparison_alias(normalized):
                related.extend(sorted(other.originals))
        existing = [f"{candidate.name} [{candidate.code}; {candidate.pk}]" for candidate in group.candidates]
        if group.warnings:
            classification, reason = "REVISAR", "; ".join(sorted(group.warnings))
        elif suspicious_text(normalized):
            classification, reason = "REVISAR", "Texto vacio, generico, extrano, provisional o incompatible con la estructura solicitada"
        elif institutional_text(normalized) and not (set(re.findall(r"[a-z]+", comparison_alias(normalized))) - {
            "direccion", "departamento", "gerencia", "secretaria", "unidad", "coordinacion",
            "division", "seccion", "de", "del", "la", "el", "los", "las", "y",
        }):
            classification, reason = "REVISAR", "Denominacion institucional sin contenido especifico"
        elif not institutional_text(normalized):
            if variants and all(possible_person(original) for original in variants):
                classification, reason = "POSIBLE PERSONA", "Dos o tres palabras con forma de nombre propio y nombre inicial reconocido, sin senal institucional; requiere confirmacion"
            else:
                classification, reason = "REVISAR", "No hay senal institucional suficiente ni evidencia clara de nombre propio"
        elif related:
            classification, reason = "POSIBLE DUPLICADO", "Variantes de case/tildes/espacios o Dpto./Depto./Departamento dentro de la misma sede; no se fusionan"
        elif group.candidates:
            classification, reason = "REVISAR", "Hay ubicaciones existentes compatibles; verificar antes de proponer una nueva"
        else:
            classification, reason = "PROPUESTA CREAR", "Senal institucional explicita, sin candidatos existentes, variantes detectadas ni datos dudosos; propuesta pendiente de aprobacion"
        proposals.append(LocationProposal(group, classification, reason, sorted(set(related + existing))))
    return proposals


def proposal_summary(proposals):
    counts = Counter(p.classification for p in proposals)
    return {"total_impresoras": sum(len(p.group.devices) for p in proposals),
            "dependencias_unicas": sum(bool(p.group.normalized) for p in proposals),
            **{category: counts[category] for category in CLASSIFICATIONS}}
