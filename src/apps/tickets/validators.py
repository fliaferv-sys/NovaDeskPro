from pathlib import Path

from django.core.exceptions import ValidationError


# ==========================================================
# CONFIGURACIÓN DE ARCHIVOS ADJUNTOS
# ==========================================================

MAX_ATTACHMENT_SIZE = 15 * 1024 * 1024  # 15 MB

ALLOWED_ATTACHMENT_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".txt",
    ".zip",
}


# ==========================================================
# VALIDAR EXTENSIÓN
# ==========================================================

def validate_attachment_extension(uploaded_file):
    extension = Path(uploaded_file.name).suffix.lower()

    if extension not in ALLOWED_ATTACHMENT_EXTENSIONS:
        allowed = ", ".join(
            sorted(
                extension.replace(".", "").upper()
                for extension in ALLOWED_ATTACHMENT_EXTENSIONS
            )
        )

        raise ValidationError(
            f"Tipo de archivo no permitido. "
            f"Formatos aceptados: {allowed}."
        )


# ==========================================================
# VALIDAR TAMAÑO
# ==========================================================

def validate_attachment_size(uploaded_file):
    if uploaded_file.size > MAX_ATTACHMENT_SIZE:
        raise ValidationError(
            "El archivo supera el tamaño máximo permitido de 15 MB."
        )