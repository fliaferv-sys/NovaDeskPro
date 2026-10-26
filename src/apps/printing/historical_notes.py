"""Read-only interpretation of explicitly labelled legacy inventory lines."""
import re


_LINE_START = r"(?:\A|[\r\n])[^\S\r\n]*"
_LABELLED_LINE = re.compile(
    _LINE_START + r"(?P<label>Responsable|Dependencia)[^\S\r\n]*:[^\S\r\n]*(?P<value>[^\r\n]*)",
    re.IGNORECASE,
)


def historical_search_pattern(term, *, dependency_only=False):
    """Match a whole word in a labelled value, never elsewhere in notes.

    Explicit CR/LF boundaries support Windows and older imported line endings.
    The escaped term cannot introduce regex operators. Whole-word boundaries
    keep Ariel separate from Mariel without changing structured-field searches.
    """
    label = "Dependencia" if dependency_only else "(?:Responsable|Dependencia)"
    return (_LINE_START + label + r"[^\S\r\n]*:[^\r\n]*(?<!\w)"
            + re.escape(term) + r"(?!\w)")


def historical_values(notes):
    result = {"responsibles": [], "dependencies": []}
    seen = {key: set() for key in result}
    for match in _LABELLED_LINE.finditer(notes or ""):
        key = "responsibles" if match["label"].casefold() == "responsable" else "dependencies"
        value = match["value"].strip()
        if value and value.casefold() not in seen[key]:
            result[key].append(value)
            seen[key].add(value.casefold())
    return result


def with_historical_labels(device):
    """Attach display-only values; do not save, link accounts or overwrite notes."""
    values = historical_values(device.notes)
    device.historical_responsibles = values["responsibles"]
    device.historical_dependencies = values["dependencies"]
    return device
