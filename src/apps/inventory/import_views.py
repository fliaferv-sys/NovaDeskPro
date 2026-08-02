# ==========================================================
# VISTAS DE IMPORTACIÓN MASIVA DE ACTIVOS
# SPRINT 16
# ==========================================================

from pathlib import Path
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import FileResponse
from django.shortcuts import redirect, render

from .forms import AssetImportForm
from .services.excel_import import (
    generate_asset_import_template,
    import_valid_assets,
    preview_asset_import,
)


# ==========================================================
# CONSTANTES
# ==========================================================

IMPORT_SESSION_KEY = "asset_import_temporary_file"


# ==========================================================
# PERMISOS
# ==========================================================

def can_import_assets(user):
    """
    Permite importar activos a:
    - Administradores
    - Supervisores
    - Superusuarios
    """

    return (
        user.is_superuser
        or user.role in {
            "ADMIN",
            "SUPERVISOR",
        }
    )


# ==========================================================
# ARCHIVO TEMPORAL
# ==========================================================

def delete_temporary_import_file(request):
    """
    Elimina el Excel temporal guardado durante la vista previa.
    """

    temporary_path = request.session.pop(
        IMPORT_SESSION_KEY,
        None,
    )

    if (
        temporary_path
        and default_storage.exists(temporary_path)
    ):
        default_storage.delete(temporary_path)


def save_temporary_import_file(
    request,
    uploaded_file,
):
    """
    Guarda temporalmente el Excel para confirmar después
    la importación sin solicitar nuevamente el archivo.
    """

    delete_temporary_import_file(request)

    extension = Path(
        uploaded_file.name
    ).suffix.lower()

    temporary_name = (
        f"inventory/imports/tmp/"
        f"{request.user.pk}_{uuid4().hex}{extension}"
    )

    uploaded_file.seek(0)

    saved_path = default_storage.save(
        temporary_name,
        ContentFile(uploaded_file.read()),
    )

    request.session[
        IMPORT_SESSION_KEY
    ] = saved_path

    request.session.modified = True

    return saved_path


# ==========================================================
# DESCARGAR PLANTILLA EXCEL
# ==========================================================

@login_required
def asset_import_template_view(request):
    if not can_import_assets(request.user):
        raise PermissionDenied(
            "No tiene permisos para descargar "
            "la plantilla de importación."
        )

    excel_buffer = generate_asset_import_template()

    return FileResponse(
        excel_buffer,
        as_attachment=True,
        filename="Plantilla_Importacion_Activos.xlsx",
        content_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
    )


# ==========================================================
# IMPORTACIÓN MASIVA
# ==========================================================

@login_required
def asset_import_view(request):
    if not can_import_assets(request.user):
        raise PermissionDenied(
            "No tiene permisos para importar activos."
        )

    preview_result = None
    import_result = None

    # ------------------------------------------------------
    # CONFIRMAR IMPORTACIÓN
    # ------------------------------------------------------

    if (
        request.method == "POST"
        and request.POST.get("action") == "import"
    ):
        temporary_path = request.session.get(
            IMPORT_SESSION_KEY
        )

        if (
            not temporary_path
            or not default_storage.exists(temporary_path)
        ):
            messages.error(
                request,
                (
                    "El archivo temporal ya no está disponible. "
                    "Seleccione nuevamente el archivo Excel."
                ),
            )

            return redirect(
                "inventory:asset_import"
            )

        try:
            with default_storage.open(
                temporary_path,
                "rb",
            ) as excel_file:
                preview_result = preview_asset_import(
                    excel_file
                )

            import_result = import_valid_assets(
                preview_result
            )

        except ValidationError as exc:
            messages.error(
                request,
                " ".join(exc.messages),
            )

        except Exception as exc:
            messages.error(
                request,
                (
                    "Ocurrió un error inesperado durante "
                    f"la importación: {exc}"
                ),
            )

        else:
            messages.success(
                request,
                (
                    "Importación finalizada. "
                    f"Activos importados: "
                    f"{import_result.imported_rows}. "
                    f"Filas omitidas: "
                    f"{import_result.skipped_rows}."
                ),
            )

        finally:
            delete_temporary_import_file(
                request
            )

        form = AssetImportForm()

    # ------------------------------------------------------
    # GENERAR VISTA PREVIA
    # ------------------------------------------------------

    elif request.method == "POST":
        form = AssetImportForm(
            request.POST,
            request.FILES,
        )

        if form.is_valid():
            uploaded_file = form.cleaned_data[
                "excel_file"
            ]

            try:
                uploaded_file.seek(0)

                preview_result = preview_asset_import(
                    uploaded_file
                )

            except ValidationError as exc:
                form.add_error(
                    "excel_file",
                    " ".join(exc.messages),
                )

            except Exception as exc:
                form.add_error(
                    "excel_file",
                    (
                        "No fue posible procesar el archivo: "
                        f"{exc}"
                    ),
                )

            else:
                save_temporary_import_file(
                    request,
                    uploaded_file,
                )

                if preview_result.total_rows == 0:
                    messages.warning(
                        request,
                        (
                            "El archivo no contiene filas "
                            "de activos para importar."
                        ),
                    )

                elif preview_result.valid_rows == 0:
                    messages.error(
                        request,
                        (
                            "Ninguna fila es válida. "
                            "Corrija el archivo antes de importar."
                        ),
                    )

                elif preview_result.invalid_rows:
                    messages.warning(
                        request,
                        (
                            f"Se encontraron "
                            f"{preview_result.invalid_rows} "
                            "filas con errores. Solo se "
                            "importarán las filas válidas."
                        ),
                    )

                else:
                    messages.success(
                        request,
                        (
                            "Vista previa generada "
                            "correctamente. Todas las filas "
                            "son válidas."
                        ),
                    )

    # ------------------------------------------------------
    # PRIMERA CARGA
    # ------------------------------------------------------

    else:
        delete_temporary_import_file(
            request
        )

        form = AssetImportForm()

    return render(
        request,
        "inventory/asset_import.html",
        {
            "form": form,
            "preview_result": preview_result,
            "import_result": import_result,
        },
    )