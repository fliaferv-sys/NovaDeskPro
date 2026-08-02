from pathlib import Path

from django.core.exceptions import ValidationError


def validate_attachment_signature(uploaded_file):
    """Comprueba la firma binaria de los formatos adjuntos más comunes."""
    signatures_by_extension = {
        ".pdf": (b"%PDF-",),
        ".jpg": (b"\xff\xd8\xff",),
        ".jpeg": (b"\xff\xd8\xff",),
        ".png": (b"\x89PNG\r\n\x1a\n",),
        ".webp": (b"RIFF",),
        ".doc": (b"\xd0\xcf\x11\xe0",),
        ".docx": (b"PK\x03\x04",),
        ".xls": (b"\xd0\xcf\x11\xe0",),
        ".xlsx": (b"PK\x03\x04",),
        ".zip": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
    }
    signatures = signatures_by_extension.get(Path(uploaded_file.name).suffix.lower())
    if not signatures:
        return
    position = uploaded_file.tell()
    try:
        header = uploaded_file.read(12)
    finally:
        uploaded_file.seek(position)
    if not any(header.startswith(signature) for signature in signatures):
        raise ValidationError("El contenido del archivo no coincide con su extensión.")
