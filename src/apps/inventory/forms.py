# ==========================================================
# FORMULARIOS
# MÓDULO INVENTARIO
# NOVADESK PRO
# ==========================================================

from pathlib import Path

from django import forms
from django.utils import timezone

from apps.accounts.models import User

from .models import (
    Asset,
    AssetTechnicalHistory,
    AcquisitionBatch,
    OrganizationalLocation,
)


# ==========================================================
# CAMPO PERSONALIZADO PARA UBICACIONES
# ==========================================================

class OrganizationalLocationChoiceField(
    forms.ModelChoiceField
):
    """
    Muestra la sede y la ruta completa de cada ubicación.

    Ejemplo:
    Planta Industrial 1 - Edificio A / Piso 2 / Oficina 203
    """

    def label_from_instance(self, obj):
        return (
            f"{obj.branch.name} - "
            f"{obj.full_path}"
        )


# ==========================================================
# FORMULARIO DE ACTIVOS INFORMÁTICOS
# ==========================================================

class AssetForm(forms.ModelForm):

    physical_location = OrganizationalLocationChoiceField(
        queryset=OrganizationalLocation.objects.none(),
        required=False,
        label="Ubicación física detallada",
        empty_label="Seleccione una ubicación",
        widget=forms.Select(
            attrs={
                "class": "form-control",
            }
        ),
    )

    class Meta:
        model = Asset

        fields = [
            "internal_code",
            "patrimonial_code",
            "asset_type",
            "brand",
            "model",
            "serial_number",
            "hostname",
            "acquisition_batch",

            # Custodio
            "assigned_user",

            # Ubicación física
            "branch",
            "physical_location",
            "department",
            "location",

            # Estado
            "operational_status",
            "connection_status",

            # Datos técnicos
            "operating_system",
            "current_ip",
            "mac_address",

            # Compra y garantía
            "purchase_date",
            "warranty_expiration",
            "supplier",

            # Observaciones
            "notes",
        ]

        widgets = {
            "internal_code": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ej.: PC-ADM-001",
                }
            ),

            "patrimonial_code": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Código patrimonial",
                }
            ),

            "asset_type": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),

            "acquisition_batch": forms.Select(
                attrs={"class": "form-control"}
            ),

            "brand": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ej.: HP, Dell, Lenovo",
                }
            ),

            "model": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Modelo del equipo",
                }
            ),

            "serial_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Número de serie",
                }
            ),

            "hostname": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ej.: PC-ADM-001",
                }
            ),

            "assigned_user": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),

            "branch": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),

            "department": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": (
                        "Departamento o dependencia"
                    ),
                }
            ),

            "location": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": (
                        "Ej.: Rack 2, mesa 14, puesto 08"
                    ),
                }
            ),

            "operational_status": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),

            "connection_status": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),

            "operating_system": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ej.: Windows 11 Pro",
                }
            ),

            "current_ip": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ej.: 192.168.1.25",
                }
            ),

            "mac_address": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": (
                        "Ej.: 00:1A:2B:3C:4D:5E"
                    ),
                }
            ),

            "purchase_date": forms.DateInput(
                attrs={
                    "class": "form-control",
                    "type": "date",
                }
            ),

            "warranty_expiration": forms.DateInput(
                attrs={
                    "class": "form-control",
                    "type": "date",
                }
            ),

            "supplier": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Proveedor",
                }
            ),

            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": (
                        "Observaciones del activo"
                    ),
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["acquisition_batch"].queryset = AcquisitionBatch.objects.order_by(
            "-date", "code"
        )
        for field_name in (
            "brand",
            "model",
            "patrimonial_code",
            "serial_number",
            "acquisition_batch",
        ):
            self.fields[field_name].required = True

        # ==================================================
        # USUARIOS ACTIVOS DISPONIBLES COMO CUSTODIOS
        # ==================================================

        self.fields["assigned_user"].queryset = (
            User.objects
            .filter(
                is_active=True,
                approval_status=(
                    User.ApprovalStatus.APPROVED
                ),
            )
            .select_related(
                "branch"
            )
            .order_by(
                "first_name",
                "last_name",
            )
        )

        self.fields["assigned_user"].empty_label = (
            "Sin usuario asignado"
        )

        # ==================================================
        # MOSTRAR SOLAMENTE SEDES ACTIVAS
        # ==================================================

        self.fields["branch"].queryset = (
            self.fields["branch"]
            .queryset
            .filter(
                is_active=True
            )
            .order_by(
                "name"
            )
        )

        self.fields["branch"].empty_label = (
            "Seleccione una sede"
        )

        # ==================================================
        # UBICACIONES FÍSICAS ACTIVAS
        # ==================================================

        active_locations = (
            OrganizationalLocation.objects
            .filter(
                is_active=True,
                branch__is_active=True,
            )
            .select_related(
                "branch",
                "parent",
            )
            .order_by(
                "branch__name",
                "name",
            )
        )

        selected_branch_id = None

        # Cuando el formulario fue enviado.
        if self.is_bound:
            selected_branch_id = (
                self.data.get("branch")
            )

        # Cuando se está editando un activo existente.
        elif (
            self.instance
            and self.instance.pk
            and self.instance.branch_id
        ):
            selected_branch_id = (
                self.instance.branch_id
            )

        # Si ya se eligió una sede, mostrar únicamente
        # sus ubicaciones.
        if selected_branch_id:
            active_locations = (
                active_locations.filter(
                    branch_id=selected_branch_id
                )
            )

        self.fields[
            "physical_location"
        ].queryset = active_locations

        # ==================================================
        # AYUDAS VISUALES
        # ==================================================

        self.fields["assigned_user"].help_text = (
            "Persona responsable o custodio del equipo. "
            "Puede estar en una sede distinta a la "
            "ubicación física del activo."
        )

        self.fields["branch"].help_text = (
            "Sede donde se encuentra físicamente "
            "el equipo."
        )

        self.fields[
            "physical_location"
        ].help_text = (
            "Edificio, piso, oficina, depósito, "
            "sala técnica o sector dentro de la sede."
        )

        self.fields["department"].help_text = (
            "Departamento responsable o área donde "
            "se utiliza el equipo."
        )

        self.fields["location"].help_text = (
            "Referencia adicional, por ejemplo: "
            "rack, mesa, puesto o sector específico."
        )

    # ======================================================
    # VALIDACIÓN DE UBICACIÓN
    # ======================================================

    def clean(self):
        cleaned_data = super().clean()

        for field_name, label in {
            "brand": "La marca",
            "model": "El modelo",
            "patrimonial_code": "El patrimonio",
            "serial_number": "El número de serie",
            "acquisition_batch": "El lote",
        }.items():
            if not cleaned_data.get(field_name):
                self.add_error(field_name, f"{label} es obligatorio para registrar el equipo.")

        branch = cleaned_data.get(
            "branch"
        )

        physical_location = cleaned_data.get(
            "physical_location"
        )

        assigned_user = cleaned_data.get(
            "assigned_user"
        )

        # No permitir una ubicación detallada sin sede.
        if physical_location and not branch:
            self.add_error(
                "branch",
                (
                    "Debe seleccionar la sede correspondiente "
                    "a la ubicación física."
                ),
            )

        # Comprobar que la ubicación pertenece a la sede.
        if (
            branch
            and physical_location
            and physical_location.branch_id
            != branch.pk
        ):
            self.add_error(
                "physical_location",
                (
                    "La ubicación seleccionada no pertenece "
                    "a la sede indicada."
                ),
            )

        # No impedir que custodio y activo estén en sedes
        # distintas, porque puede ocurrir en la práctica.
        # Solamente conservamos la información para futuros
        # avisos y auditorías.
        if (
            assigned_user
            and branch
            and assigned_user.branch_id
            and assigned_user.branch_id
            != branch.pk
        ):
            self.add_warning_message = (
                "El custodio pertenece a una sede diferente."
            )

        return cleaned_data

    # ======================================================
    # VALIDACIÓN DE DIRECCIÓN MAC
    # ======================================================

    def clean_mac_address(self):
        mac_address = (
            self.cleaned_data.get(
                "mac_address",
                ""
            )
            .strip()
            .upper()
        )

        if not mac_address:
            return ""

        mac_address = mac_address.replace(
            "-",
            ":",
        )

        parts = mac_address.split(":")

        if (
            len(parts) != 6
            or any(
                len(part) != 2
                for part in parts
            )
        ):
            raise forms.ValidationError(
                "Ingrese una dirección MAC válida. "
                "Ejemplo: 00:1A:2B:3C:4D:5E."
            )

        try:
            int(
                "".join(parts),
                16,
            )

        except ValueError as exc:
            raise forms.ValidationError(
                "La dirección MAC contiene "
                "caracteres inválidos."
            ) from exc

        return ":".join(parts)

    # ======================================================
    # VALIDACIÓN DE FECHAS
    # ======================================================

    def clean(self):
        cleaned_data = super().clean()

        branch = cleaned_data.get(
            "branch"
        )

        physical_location = cleaned_data.get(
            "physical_location"
        )

        purchase_date = cleaned_data.get(
            "purchase_date"
        )

        warranty_expiration = cleaned_data.get(
            "warranty_expiration"
        )

        if physical_location and not branch:
            self.add_error(
                "branch",
                (
                    "Debe seleccionar la sede correspondiente "
                    "a la ubicación física."
                ),
            )

        if (
            branch
            and physical_location
            and physical_location.branch_id
            != branch.pk
        ):
            self.add_error(
                "physical_location",
                (
                    "La ubicación seleccionada no pertenece "
                    "a la sede indicada."
                ),
            )

        if (
            purchase_date
            and warranty_expiration
            and warranty_expiration < purchase_date
        ):
            self.add_error(
                "warranty_expiration",
                (
                    "La fecha de vencimiento de garantía "
                    "no puede ser anterior a la compra."
                ),
            )

        return cleaned_data


# ==========================================================
# FORMULARIO DE INTERVENCIONES TÉCNICAS
# SPRINT 13
# ==========================================================

class AssetTechnicalHistoryForm(forms.ModelForm):

    class Meta:
        model = AssetTechnicalHistory

        fields = [
            "ticket",
            "intervention_type",
            "technician",
            "diagnosis",
            "action_taken",
            "components_replaced",
            "duration_minutes",
            "cost",
            "intervention_date",
            "notes",
        ]

        widgets = {
            "ticket": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),

            "intervention_type": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),

            "technician": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),

            "diagnosis": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": (
                        "Describe el diagnóstico técnico "
                        "realizado..."
                    ),
                }
            ),

            "action_taken": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": (
                        "Describe el trabajo realizado "
                        "sobre el equipo..."
                    ),
                }
            ),

            "components_replaced": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": (
                        "Ej.: SSD 512 GB, memoria RAM, "
                        "fuente de poder..."
                    ),
                }
            ),

            "duration_minutes": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": 1,
                    "placeholder": "Ej.: 45",
                }
            ),

            "cost": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": 0,
                    "step": "0.01",
                    "placeholder": "Ej.: 250000",
                }
            ),

            "intervention_date": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M",
                attrs={
                    "class": "form-control",
                    "type": "datetime-local",
                }
            ),

            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": (
                        "Observaciones adicionales "
                        "de la intervención..."
                    ),
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        asset = kwargs.pop(
            "asset",
            None,
        )

        super().__init__(
            *args,
            **kwargs
        )

        # Solo mostrar técnicos activos y aprobados.
        self.fields["technician"].queryset = (
            User.objects
            .filter(
                role=User.Role.TECHNICIAN,
                is_active=True,
                approval_status=(
                    User.ApprovalStatus.APPROVED
                ),
            )
            .order_by(
                "first_name",
                "last_name",
            )
        )

        self.fields["technician"].empty_label = (
            "Seleccione un técnico"
        )

        self.fields["ticket"].required = False

        self.fields["ticket"].empty_label = (
            "Sin ticket relacionado"
        )

        if asset is not None:
            self.fields["ticket"].queryset = (
                asset.tickets
                .order_by(
                    "-created_at"
                )
            )

        else:
            self.fields["ticket"].queryset = (
                self.fields["ticket"]
                .queryset
                .none()
            )

        if (
            self.instance
            and self.instance.pk
            and self.instance.intervention_date
        ):
            local_date = timezone.localtime(
                self.instance.intervention_date
            )

            self.initial[
                "intervention_date"
            ] = local_date.strftime(
                "%Y-%m-%dT%H:%M"
            )

        elif not self.is_bound:
            self.initial[
                "intervention_date"
            ] = timezone.localtime().strftime(
                "%Y-%m-%dT%H:%M"
            )

    def clean_duration_minutes(self):
        duration = self.cleaned_data.get(
            "duration_minutes"
        )

        if (
            duration is not None
            and duration <= 0
        ):
            raise forms.ValidationError(
                "La duración debe ser mayor que cero."
            )

        return duration

    def clean_cost(self):
        cost = self.cleaned_data.get(
            "cost"
        )

        if (
            cost is not None
            and cost < 0
        ):
            raise forms.ValidationError(
                "El costo no puede ser negativo."
            )

        return cost

    def clean(self):
        cleaned_data = super().clean()

        ticket = cleaned_data.get(
            "ticket"
        )

        if (
            ticket
            and self.instance.asset_id
            and ticket.asset_id
            != self.instance.asset_id
        ):
            self.add_error(
                "ticket",
                (
                    "El ticket seleccionado no pertenece "
                    "a este equipo."
                ),
            )

        return cleaned_data


# ==========================================================
# FORMULARIO DE IMPORTACIÓN MASIVA DE ACTIVOS
# SPRINT 16
# ==========================================================

class AssetImportForm(forms.Form):

    excel_file = forms.FileField(
        label="Archivo Excel",
        help_text=(
            "Seleccione un archivo .xlsx con un "
            "tamaño máximo de 10 MB."
        ),
        widget=forms.ClearableFileInput(
            attrs={
                "class": "form-control",
                "accept": (
                    ".xlsx,"
                    "application/vnd.openxmlformats-"
                    "officedocument.spreadsheetml.sheet"
                ),
            }
        ),
    )

    def clean_excel_file(self):
        uploaded_file = self.cleaned_data.get(
            "excel_file"
        )

        if uploaded_file is None:
            raise forms.ValidationError(
                "Debe seleccionar un archivo Excel."
            )

        extension = Path(
            uploaded_file.name
        ).suffix.lower()

        if extension != ".xlsx":
            raise forms.ValidationError(
                "El archivo debe tener extensión .xlsx."
            )

        maximum_size = (
            10 * 1024 * 1024
        )

        if uploaded_file.size > maximum_size:
            raise forms.ValidationError(
                "El archivo supera el tamaño máximo "
                "permitido de 10 MB."
            )

        if uploaded_file.size == 0:
            raise forms.ValidationError(
                "El archivo seleccionado está vacío."
            )

        initial_position = uploaded_file.tell()

        try:
            file_signature = uploaded_file.read(
                4
            )

        finally:
            uploaded_file.seek(
                initial_position
            )

        if file_signature[:2] != b"PK":
            raise forms.ValidationError(
                "El archivo no parece ser un "
                "Excel .xlsx válido."
            )

        return uploaded_file
