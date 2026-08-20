# ==========================================================
# FORMULARIOS
# MÓDULO INVENTARIO
# NOVADESK PRO
# ==========================================================

from pathlib import Path

from django import forms
from django.db import models
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.models import Branch

from .models import (
    Asset,
    AssetTechnicalHistory,
    AcquisitionBatch,
    OrganizationalLocation,
    StockCategory,
    StockEntryDocument,
    StockEntryLine,
    StockEntryOperation,
    StockDelivery,
    StockDeliveryLine,
    TicketStockUsage,
    TicketStockUsageLine,
    StockMovement,
    StockProduct,
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
            "ram_gb",
            "disk_type",
            "storage_capacity_gb",
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

            "ram_gb": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "0.01",
                    "step": "0.01",
                }
            ),

            "disk_type": forms.Select(attrs={"class": "form-control"}),

            "storage_capacity_gb": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "0.01",
                    "step": "0.01",
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

        self.fields["acquisition_batch"].queryset = (
            AcquisitionBatch.objects.order_by("-date", "code")
        )

        for field_name in (
            "brand",
            "model",
            "patrimonial_code",
            "serial_number",
            "acquisition_batch",
        ):
            self.fields[field_name].required = True

        self.fields["assigned_user"].queryset = (
            User.objects
            .filter(
                is_active=True,
                approval_status=User.ApprovalStatus.APPROVED,
            )
            .select_related("branch")
            .order_by("first_name", "last_name")
        )
        self.fields["assigned_user"].empty_label = "Sin usuario asignado"

        self.fields["branch"].queryset = (
            self.fields["branch"].queryset
            .filter(is_active=True)
            .order_by("name")
        )
        self.fields["branch"].empty_label = "Seleccione una sede"

        active_locations = (
            OrganizationalLocation.objects
            .filter(
                is_active=True,
                branch__is_active=True,
            )
            .select_related("branch", "parent")
            .order_by("branch__name", "name")
        )

        selected_branch_id = None

        if self.is_bound:
            selected_branch_id = self.data.get("branch")
        elif (
            self.instance
            and self.instance.pk
            and self.instance.branch_id
        ):
            selected_branch_id = self.instance.branch_id

        if selected_branch_id:
            active_locations = active_locations.filter(
                branch_id=selected_branch_id
            )

        self.fields["physical_location"].queryset = active_locations

        self.fields["assigned_user"].help_text = (
            "Persona responsable o custodio del equipo."
        )
        self.fields["branch"].help_text = (
            "Sede donde se encuentra físicamente el equipo."
        )
        self.fields["physical_location"].help_text = (
            "Edificio, piso, oficina, depósito, sala técnica "
            "o sector dentro de la sede."
        )
        self.fields["department"].help_text = (
            "Departamento responsable o área donde se utiliza el equipo."
        )
        self.fields["location"].help_text = (
            "Referencia adicional: rack, mesa, puesto o sector."
        )

    def clean_mac_address(self):
        mac_address = (
            self.cleaned_data.get("mac_address", "")
            .strip()
            .upper()
        )

        if not mac_address:
            return ""

        mac_address = mac_address.replace("-", ":")
        parts = mac_address.split(":")

        if (
            len(parts) != 6
            or any(len(part) != 2 for part in parts)
        ):
            raise forms.ValidationError(
                "Ingrese una dirección MAC válida. "
                "Ejemplo: 00:1A:2B:3C:4D:5E."
            )

        try:
            int("".join(parts), 16)
        except ValueError as exc:
            raise forms.ValidationError(
                "La dirección MAC contiene caracteres inválidos."
            ) from exc

        return ":".join(parts)

    def clean(self):
        cleaned_data = super().clean()

        branch = cleaned_data.get("branch")
        physical_location = cleaned_data.get("physical_location")
        purchase_date = cleaned_data.get("purchase_date")
        warranty_expiration = cleaned_data.get("warranty_expiration")

        for field_name, label in {
            "brand": "La marca",
            "model": "El modelo",
            "patrimonial_code": "El patrimonio",
            "serial_number": "El número de serie",
            "acquisition_batch": "El lote",
        }.items():
            if not cleaned_data.get(field_name):
                self.add_error(
                    field_name,
                    f"{label} es obligatorio para registrar el equipo.",
                )

        if physical_location and not branch:
            self.add_error(
                "branch",
                "Debe seleccionar la sede correspondiente "
                "a la ubicación física.",
            )

        if (
            branch
            and physical_location
            and physical_location.branch_id != branch.pk
        ):
            self.add_error(
                "physical_location",
                "La ubicación seleccionada no pertenece "
                "a la sede indicada.",
            )

        if (
            purchase_date
            and warranty_expiration
            and warranty_expiration < purchase_date
        ):
            self.add_error(
                "warranty_expiration",
                "La fecha de vencimiento de garantía "
                "no puede ser anterior a la compra.",
            )

        return cleaned_data


class StockCategoryForm(forms.ModelForm):
    class Meta:
        model = StockCategory
        fields = ["name", "code", "description", "is_active"]


class StockProductForm(forms.ModelForm):
    class Meta:
        model = StockProduct
        fields = [
            "name",
            "reference_code",
            "category",
            "brand",
            "model",
            "description",
            "unit_of_measure",
            "minimum_stock",
            "is_active",
            "default_location",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = StockCategory.objects.filter(
            is_active=True
        )
        if self.instance.pk and self.instance.category_id:
            self.fields["category"].queryset = StockCategory.objects.filter(
                models.Q(is_active=True) | models.Q(pk=self.instance.category_id)
            )
        self.fields["default_location"].queryset = (
            OrganizationalLocation.objects.filter(is_active=True).select_related(
                "branch"
            )
        )


class StockOperationForm(forms.Form):
    product = forms.ModelChoiceField(
        queryset=StockProduct.objects.filter(is_active=True),
        label="Producto",
    )
    branch = forms.ModelChoiceField(
        queryset=Branch.objects.filter(is_active=True),
        label="Sede",
    )
    organizational_location = OrganizationalLocationChoiceField(
        queryset=OrganizationalLocation.objects.filter(is_active=True).select_related(
            "branch"
        ),
        label="Ubicación",
    )
    quantity = forms.IntegerField(label="Cantidad", min_value=1)
    reason = forms.ChoiceField(label="Motivo")
    observation = forms.CharField(
        label="Observación", required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    document_reference = forms.CharField(
        label="Referencia documental", max_length=100, required=False
    )

    allowed_reasons = frozenset()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        labels = dict(StockMovement.Reason.choices)
        self.fields["reason"].choices = [
            (value, labels[value]) for value in self.allowed_reasons
        ]

    def clean(self):
        cleaned_data = super().clean()
        branch = cleaned_data.get("branch")
        location = cleaned_data.get("organizational_location")
        if branch and location and location.branch_id != branch.pk:
            self.add_error(
                "organizational_location",
                "La ubicación no pertenece a la sede seleccionada.",
            )
        return cleaned_data


class StockEntryForm(StockOperationForm):
    allowed_reasons = (
        StockMovement.Reason.PURCHASE,
        StockMovement.Reason.RETURN,
        StockMovement.Reason.POSITIVE_ADJUSTMENT,
        StockMovement.Reason.INITIAL_ENTRY,
        StockMovement.Reason.OTHER,
    )


class StockExitForm(StockOperationForm):
    allowed_reasons = (
        StockMovement.Reason.DELIVERY,
        StockMovement.Reason.CONSUMPTION,
        StockMovement.Reason.REPAIR,
        StockMovement.Reason.WRITE_OFF,
        StockMovement.Reason.NEGATIVE_ADJUSTMENT,
        StockMovement.Reason.OTHER,
    )


class StockTransferForm(forms.Form):
    product = forms.ModelChoiceField(
        queryset=StockProduct.objects.filter(is_active=True), label="Producto"
    )
    source_branch = forms.ModelChoiceField(
        queryset=Branch.objects.filter(is_active=True), label="Sede de origen"
    )
    source_location = OrganizationalLocationChoiceField(
        queryset=OrganizationalLocation.objects.filter(is_active=True).select_related(
            "branch"
        ),
        label="Ubicación de origen",
    )
    destination_branch = forms.ModelChoiceField(
        queryset=Branch.objects.filter(is_active=True), label="Sede de destino"
    )
    destination_location = OrganizationalLocationChoiceField(
        queryset=OrganizationalLocation.objects.filter(is_active=True).select_related(
            "branch"
        ),
        label="Ubicación de destino",
    )
    quantity = forms.IntegerField(label="Cantidad", min_value=1)
    observation = forms.CharField(
        label="Observación", required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    document_reference = forms.CharField(
        label="Referencia documental", max_length=100, required=False
    )

    def clean(self):
        cleaned_data = super().clean()
        pairs = (
            ("source_branch", "source_location"),
            ("destination_branch", "destination_location"),
        )
        for branch_field, location_field in pairs:
            branch = cleaned_data.get(branch_field)
            location = cleaned_data.get(location_field)
            if branch and location and location.branch_id != branch.pk:
                self.add_error(
                    location_field,
                    "La ubicación no pertenece a la sede seleccionada.",
                )
        source_branch = cleaned_data.get("source_branch")
        source_location = cleaned_data.get("source_location")
        destination_branch = cleaned_data.get("destination_branch")
        destination_location = cleaned_data.get("destination_location")
        if (
            source_branch
            and source_location
            and destination_branch
            and destination_location
            and source_branch.pk == destination_branch.pk
            and source_location.pk == destination_location.pk
        ):
            self.add_error(
                "destination_location",
                "La ubicación de destino debe ser diferente al origen.",
            )
        return cleaned_data


class StockEntryOperationForm(forms.ModelForm):
    class Meta:
        model = StockEntryOperation
        fields = [
            "reason", "entry_date", "supplier", "invoice_number",
            "purchase_order_number", "delivery_note_number",
            "external_reference", "observations",
        ]
        widgets = {"entry_date": forms.DateInput(attrs={"type": "date"}), "observations": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        labels = dict(StockMovement.Reason.choices)
        self.fields["reason"].choices = [
            (value, labels[value]) for value in StockEntryOperation.ENTRY_REASONS
        ]


class StockEntryLineForm(forms.ModelForm):
    class Meta:
        model = StockEntryLine
        fields = ["product", "branch", "organizational_location", "quantity", "observation"]
        widgets = {"observation": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = StockProduct.objects.filter(is_active=True)
        self.fields["branch"].queryset = Branch.objects.filter(is_active=True)
        self.fields["organizational_location"].queryset = OrganizationalLocation.objects.filter(is_active=True, branch__is_active=True).select_related("branch")


class StockEntryDocumentForm(forms.ModelForm):
    ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx", ".xls", ".xlsx"}

    class Meta:
        model = StockEntryDocument
        fields = ["document_type", "file", "description", "observation"]
        widgets = {"observation": forms.Textarea(attrs={"rows": 2})}

    def clean_file(self):
        uploaded_file = self.cleaned_data.get("file")
        if not uploaded_file or uploaded_file.size == 0:
            raise forms.ValidationError("Debe seleccionar un archivo no vacío.")
        if Path(uploaded_file.name).suffix.lower() not in self.ALLOWED_EXTENSIONS:
            raise forms.ValidationError("El tipo de archivo no está permitido.")
        if uploaded_file.size > 10 * 1024 * 1024:
            raise forms.ValidationError("El archivo supera el tamaño máximo de 10 MB.")
        return uploaded_file


class StockDeliveryForm(forms.ModelForm):
    class Meta:
        model = StockDelivery
        fields = ["recipient", "department", "branch", "location", "delivery_responsible", "authorized_by", "delivery_date", "observations"]
        widgets = {"delivery_date": forms.DateInput(attrs={"type": "date"}), "observations": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ("recipient", "delivery_responsible", "authorized_by"):
            self.fields[field].queryset = User.objects.filter(is_active=True).order_by("first_name", "last_name", "username")
        self.fields["branch"].queryset = Branch.objects.filter(is_active=True)
        self.fields["location"].queryset = OrganizationalLocation.objects.filter(is_active=True, branch__is_active=True).select_related("branch")


class StockDeliveryLineForm(forms.ModelForm):
    class Meta:
        model = StockDeliveryLine
        fields = ["product", "source_branch", "source_location", "quantity"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = StockProduct.objects.filter(is_active=True)
        self.fields["source_branch"].queryset = Branch.objects.filter(is_active=True)
        self.fields["source_location"].queryset = OrganizationalLocation.objects.filter(is_active=True, branch__is_active=True).select_related("branch")


class StockDeliverySignedDocumentForm(forms.ModelForm):
    class Meta:
        model = StockDelivery
        fields = ["signed_document", "signed_document_verified"]

    def clean_signed_document(self):
        uploaded_file = self.cleaned_data.get("signed_document")
        if not uploaded_file or uploaded_file.size == 0:
            raise forms.ValidationError("Debe seleccionar un archivo no vacío.")
        if Path(uploaded_file.name).suffix.lower() not in {".pdf", ".jpg", ".jpeg", ".png"}:
            raise forms.ValidationError("Solo se permiten archivos PDF, JPG, JPEG o PNG.")
        if uploaded_file.size > 10 * 1024 * 1024:
            raise forms.ValidationError("El archivo no puede superar los 10 MB.")
        return uploaded_file


class TicketStockUsageForm(forms.ModelForm):
    class Meta:
        model = TicketStockUsage
        fields = ["ticket", "observation"]
        widgets = {"observation": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ticket"].queryset = (
            self.fields["ticket"]
            .queryset
            .select_related("requester", "assigned_to")
            .order_by("-created_at")
        )


class TicketStockUsageLineForm(forms.ModelForm):
    class Meta:
        model = TicketStockUsageLine
        fields = [
            "product",
            "source_branch",
            "source_location",
            "quantity",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["product"].queryset = (
            StockProduct.objects
            .filter(
                is_active=True,
                balances__quantity__gt=0,
            )
            .distinct()
        )

        self.fields["source_branch"].queryset = (
            Branch.objects
            .filter(
                is_active=True,
                stock_balances__quantity__gt=0,
            )
            .distinct()
        )

        self.fields["source_location"].queryset = (
            OrganizationalLocation.objects
            .filter(
                is_active=True,
                stock_balances__quantity__gt=0,
            )
            .select_related("branch")
            .distinct()
        )

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
