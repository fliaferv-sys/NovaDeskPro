# ==========================================================
# FORMULARIOS
# MÓDULO ENTREGAS Y CUSTODIA
# ==========================================================

from django import forms
from django.utils import timezone

from apps.accounts.models import User
from apps.directory.identity_services import (
    InstitutionalIdentityError,
    resolve_institutional_identity,
    resolve_identity_for_user,
)
from apps.inventory.models import Asset

from .models import (
    AssetCustodyMovement,
    DeliveryBatch,
    DeliveryBatchDocument,
    DeliveryDocument,
)


class InstitutionalUserSelect(forms.Select):
    def create_option(
        self,
        name,
        value,
        label,
        selected,
        index,
        subindex=None,
        attrs=None,
    ):
        option = super().create_option(
            name,
            value,
            label,
            selected,
            index,
            subindex=subindex,
            attrs=attrs,
        )
        instance = getattr(value, "instance", None)
        if instance is not None:
            option["attrs"]["data-email"] = instance.email or ""
            option["attrs"]["data-id-personal"] = instance.id_personal or ""
        return option


def _resolve_recipient_identity(cleaned_data):
    recipient_id_personal = cleaned_data.get("recipient_id_personal")
    recipient_email = cleaned_data.get("recipient_email") or ""
    if isinstance(recipient_email, str):
        recipient_email = recipient_email.strip()

    if recipient_id_personal is None and not recipient_email:
        return None

    try:
        identity = resolve_institutional_identity(
            id_personal=recipient_id_personal,
            email=recipient_email,
        )
    except InstitutionalIdentityError as exc:
        raise forms.ValidationError(
            "No fue posible consultar el Directorio Institucional. "
            "Intente nuevamente."
        ) from exc

    if identity is None:
        raise forms.ValidationError(
            "No fue posible validar el receptor institucional seleccionado."
        )

    return identity


def _apply_recipient_identity(cleaned_data, identity):
    cleaned_data["recipient_id_personal"] = identity["id_personal"]
    cleaned_data["recipient_name"] = identity["name"]
    cleaned_data["recipient_email"] = identity["email"]
    cleaned_data["recipient_source"] = identity["source"]
    cleaned_data["recipient_employee_number"] = identity["employee_number"]
    cleaned_data["recipient_position"] = identity["position"]

    recipient = None
    if identity["id_personal"]:
        recipient = User.objects.filter(
            id_personal=identity["id_personal"],
            is_active=True,
        ).first()

    if recipient is None and identity["email"]:
        recipient = User.objects.filter(
            email__iexact=identity["email"],
            is_active=True,
        ).first()

    cleaned_data["recipient"] = recipient


def _apply_delivery_responsible_identity(cleaned_data, delivery_responsible):
    if delivery_responsible is None:
        return

    identity = resolve_identity_for_user(delivery_responsible)
    if identity is None:
        return

    employee_number = identity.get("employee_number")
    if employee_number:
        cleaned_data["origin_employee_number"] = employee_number

    position = identity.get("position")
    if position:
        cleaned_data["origin_position"] = position


class AssetCustodyMovementForm(forms.ModelForm):
    institutional_recipient = forms.CharField(
        required=False,
        label="Receptor institucional",
        widget=forms.TextInput(
            attrs={
                "class": "form-control institutional-recipient-search",
                "autocomplete": "off",
                "placeholder": "Buscar por nombre, correo, usuario o legajo",
            }
        ),
    )

    class Meta:
        model = AssetCustodyMovement

        fields = [
            "asset",
            "movement_type",
            "status",
            "previous_custodian",
            "recipient_id_personal",
            "recipient_name",
            "recipient_email",
            "recipient_source",
            "recipient",
            "recipient_employee_number",
            "recipient_position",
            "recipient_area",
            "recipient_unit",
            "recipient_section",
            "delivery_responsible",
            "authorizing_director",
            "department",
            "destination_branch",
            "location",
            "movement_date",
            "accessories",
            "asset_condition",
            "observations",
            "director_signature",
            "responsible_signature",
            "recipient_signature",
            "signed_document",
        ]

        widgets = {
            "asset": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),

            "movement_type": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),

            "status": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),

            "previous_custodian": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),

            "recipient_id_personal": forms.HiddenInput(),
            "recipient_name": forms.HiddenInput(),
            "recipient_email": forms.HiddenInput(),
            "recipient_source": forms.HiddenInput(),
            "recipient": forms.HiddenInput(),

            "recipient_employee_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Número de legajo",
                }
            ),

            "recipient_position": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Cargo del funcionario receptor",
                }
            ),

            "recipient_area": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Área del funcionario receptor",
                }
            ),

            "recipient_unit": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Unidad organizacional",
                }
            ),

            "recipient_section": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Sección del funcionario receptor",
                }
            ),

            "delivery_responsible": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),

            "authorizing_director": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),

            "department": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Departamento o dependencia",
                }
            ),

            "destination_branch": forms.Select(attrs={"class": "form-control"}),

            "location": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ubicación física del equipo",
                }
            ),

            "movement_date": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M",
                attrs={
                    "class": "form-control",
                    "type": "datetime-local",
                }
            ),

            "accessories": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": (
                        "Ej.: cargador, mouse, teclado, bolso, "
                        "cable HDMI..."
                    ),
                }
            ),

            "asset_condition": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": (
                        "Describa el estado físico y funcional "
                        "del equipo."
                    ),
                }
            ),

            "observations": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Observaciones adicionales",
                }
            ),

            "director_signature": forms.ClearableFileInput(
                attrs={
                    "class": "form-control",
                    "accept": "image/*",
                }
            ),

            "responsible_signature": forms.ClearableFileInput(
                attrs={
                    "class": "form-control",
                    "accept": "image/*",
                }
            ),

            "recipient_signature": forms.ClearableFileInput(
                attrs={
                    "class": "form-control",
                    "accept": "image/*",
                }
            ),

            "signed_document": forms.ClearableFileInput(
                attrs={
                    "class": "form-control",
                    "accept": ".pdf,image/*",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        current_user = kwargs.pop("current_user", None)

        super().__init__(*args, **kwargs)

        active_users = User.objects.filter(
            is_active=True
        ).order_by(
            "first_name",
            "last_name",
            "email",
        )

        self.fields["previous_custodian"].queryset = active_users
        self.fields["recipient"].queryset = active_users
        self.fields["delivery_responsible"].queryset = active_users
        self.fields["authorizing_director"].queryset = active_users

        self.fields["previous_custodian"].required = False
        self.fields["recipient"].required = False
        self.fields["authorizing_director"].required = False

        self.fields["previous_custodian"].empty_label = (
            "Sin custodio anterior"
        )

        self.fields["recipient"].empty_label = (
            "Sin receptor"
        )

        self.fields["authorizing_director"].empty_label = (
            "Sin director asignado"
        )

        if self.instance.pk and self.instance.recipient_name:
            self.initial["institutional_recipient"] = self.instance.recipient_name

        self.fields["asset"].queryset = Asset.objects.order_by(
            "internal_code"
        )

        self.fields["asset"].required = False

        if current_user is not None:
            self.fields["delivery_responsible"].initial = current_user

        if not self.is_bound and not self.instance.pk:
            self.initial["movement_date"] = (
                timezone.localtime().strftime(
                    "%Y-%m-%dT%H:%M"
                )
            )

        elif self.instance.pk and self.instance.movement_date:
            local_date = timezone.localtime(
                self.instance.movement_date
            )

            self.initial["movement_date"] = (
                local_date.strftime(
                    "%Y-%m-%dT%H:%M"
                )
            )

    def clean(self):
        cleaned_data = super().clean()

        movement_type = cleaned_data.get("movement_type")
        previous_custodian = cleaned_data.get(
            "previous_custodian"
        )
        recipient = cleaned_data.get("recipient")
        recipient_identity = None

        delivery_types = {
            AssetCustodyMovement.MovementType.DELIVERY,
            AssetCustodyMovement.MovementType.REASSIGNMENT,
            AssetCustodyMovement.MovementType.RESERVATION,
        }

        if movement_type in delivery_types:
            if (
                cleaned_data.get("recipient_id_personal") is None
                and not (cleaned_data.get("recipient_email") or "").strip()
            ):
                self.add_error(
                    "institutional_recipient",
                    "Debe seleccionar el receptor institucional.",
                )
            else:
                try:
                    recipient_identity = _resolve_recipient_identity(cleaned_data)
                except forms.ValidationError as exc:
                    self.add_error("institutional_recipient", exc)
                else:
                    if recipient_identity is not None:
                        _apply_recipient_identity(cleaned_data, recipient_identity)
                        recipient = cleaned_data.get("recipient")

        if (
            movement_type
            == AssetCustodyMovement.MovementType.RETURN
            and not previous_custodian
        ):
            self.add_error(
                "previous_custodian",
                "Debe indicar quién devuelve el equipo.",
            )

        if (
            movement_type == AssetCustodyMovement.MovementType.REASSIGNMENT
            and previous_custodian
        ):
            duplicate_recipient = bool(
                recipient and previous_custodian == recipient
            )
            if recipient is None and recipient_identity is not None:
                identity_id = recipient_identity["id_personal"]
                identity_email = (recipient_identity["email"] or "").strip()
                previous_email = (previous_custodian.email or "").strip()
                duplicate_recipient = bool(
                    identity_id is not None
                    and previous_custodian.id_personal == identity_id
                ) or bool(
                    identity_email
                    and previous_email
                    and identity_email.casefold() == previous_email.casefold()
                )

            if duplicate_recipient:
                self.add_error(
                    "institutional_recipient",
                    (
                        "En una reasignación, el custodio anterior "
                        "y el nuevo receptor deben ser distintos."
                    ),
                )

        return cleaned_data


class DeliveryBatchForm(forms.ModelForm):
    """
    Formulario para crear o editar un acta agrupada.

    El campo ``assets`` permite seleccionar uno o varios activos.
    Los movimientos individuales se crearán posteriormente desde la vista,
    conservando la trazabilidad propia de cada activo.
    """

    assets = forms.ModelMultipleChoiceField(
        queryset=Asset.objects.none(),
        required=True,
        label="Activos incluidos",
        help_text=(
            "Seleccione uno o varios activos que pertenecerán "
            "a la misma acta de entrega."
        ),
        widget=forms.SelectMultiple(
            attrs={
                "class": "form-control",
                "size": 12,
            }
        ),
    )
    institutional_recipient = forms.CharField(
        required=False,
        label="Receptor institucional",
        widget=forms.TextInput(
            attrs={
                "class": "form-control institutional-recipient-search",
                "autocomplete": "off",
                "placeholder": "Buscar por nombre, correo, usuario o legajo",
            }
        ),
    )

    class Meta:
        model = DeliveryBatch

        fields = [
            "assets",
            "delivery_responsible",
            "authorizing_director",
            "origin_unit",
            "origin_department",
            "origin_area",
            "origin_section",
            "origin_position",
            "origin_employee_number",
            "recipient_id_personal",
            "recipient_name",
            "recipient_email",
            "recipient_source",
            "recipient",
            "recipient_employee_number",
            "recipient_position",
            "recipient_unit",
            "recipient_area",
            "recipient_section",
            "destination_branch",
            "department",
            "location",
            "delivery_date",
            "observations",
        ]

        widgets = {
            "recipient_id_personal": forms.HiddenInput(),
            "recipient_name": forms.HiddenInput(),
            "recipient_email": forms.HiddenInput(),
            "recipient_source": forms.HiddenInput(),
            "recipient": forms.HiddenInput(),
            "recipient_employee_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Número de legajo del receptor",
                }
            ),
            "recipient_position": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Cargo del receptor",
                }
            ),
            "recipient_area": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Área del receptor",
                }
            ),
            "recipient_unit": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Unidad del receptor",
                }
            ),
            "recipient_section": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Sección del receptor",
                }
            ),
            "delivery_responsible": InstitutionalUserSelect(
                attrs={
                    "class": "form-control",
                }
            ),
            "authorizing_director": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),
            "origin_unit": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Unidad de origen",
                }
            ),
            "origin_department": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Departamento de origen",
                }
            ),
            "origin_area": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Área de origen",
                }
            ),
            "origin_section": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Sección de origen",
                }
            ),
            "origin_position": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Cargo del responsable de entrega",
                }
            ),
            "origin_employee_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Legajo del responsable de entrega",
                }
            ),
            "department": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Departamento de destino",
                }
            ),
            "destination_branch": forms.Select(attrs={"class": "form-control"}),
            "location": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ubicación física de destino",
                }
            ),
            "delivery_date": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M",
                attrs={
                    "class": "form-control",
                    "type": "datetime-local",
                }
            ),
            "observations": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Observaciones generales del acta",
                }
            ),
            "director_signature": forms.ClearableFileInput(
                attrs={
                    "class": "form-control",
                    "accept": "image/*",
                }
            ),
            "responsible_signature": forms.ClearableFileInput(
                attrs={
                    "class": "form-control",
                    "accept": "image/*",
                }
            ),
            "recipient_signature": forms.ClearableFileInput(
                attrs={
                    "class": "form-control",
                    "accept": "image/*",
                }
            ),
            "signed_document": forms.ClearableFileInput(
                attrs={
                    "class": "form-control",
                    "accept": ".pdf,image/*",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        current_user = kwargs.pop("current_user", None)
        staged_asset_ids = kwargs.pop("staged_asset_ids", [])

        super().__init__(*args, **kwargs)

        active_users = User.objects.filter(
            is_active=True
        ).order_by(
            "first_name",
            "last_name",
            "email",
        )

        self.fields["recipient"].queryset = active_users
        self.fields["recipient"].required = False
        self.fields["delivery_responsible"].queryset = active_users
        self.fields["authorizing_director"].queryset = active_users

        self.fields["authorizing_director"].required = True
        self.fields["authorizing_director"].empty_label = (
            "Seleccione el Director DTI"
        )

        if self.instance.pk and self.instance.recipient_name:
            self.initial["institutional_recipient"] = self.instance.recipient_name

        active_movement_statuses = [
            AssetCustodyMovement.MovementStatus.IN_DELIVERY_PROCESS,
            AssetCustodyMovement.MovementStatus.PREPARED,
            AssetCustodyMovement.MovementStatus.PENDING_SIGNATURE,
        ]
        available_assets = Asset.objects.exclude(
            custody_movements__status__in=active_movement_statuses
        )
        staged_assets = Asset.objects.filter(pk__in=staged_asset_ids)
        self.fields["assets"].queryset = (
            (available_assets | staged_assets)
            .select_related("acquisition_batch")
            .distinct()
            .order_by("asset_type", "brand", "model", "internal_code")
        )

        if self.instance.pk:
            self.fields["assets"].initial = (
                self.instance.movements.values_list(
                    "asset_id",
                    flat=True,
                )
            )

        if current_user is not None:
            self.fields["delivery_responsible"].initial = current_user

        if not self.is_bound and not self.instance.pk:
            self.initial["delivery_date"] = (
                timezone.localtime().strftime(
                    "%Y-%m-%dT%H:%M"
                )
            )

        elif self.instance.pk and self.instance.delivery_date:
            local_date = timezone.localtime(
                self.instance.delivery_date
            )

            self.initial["delivery_date"] = (
                local_date.strftime(
                    "%Y-%m-%dT%H:%M"
                )
            )

    def clean_assets(self):
        assets = self.cleaned_data.get("assets")

        if not assets:
            raise forms.ValidationError(
                "Debe seleccionar al menos un activo."
            )

        incomplete = []
        for asset in assets:
            missing = []
            if not asset.brand:
                missing.append("marca")
            if not asset.model:
                missing.append("modelo")
            if not asset.patrimonial_code:
                missing.append("patrimonio")
            if not asset.serial_number:
                missing.append("número de serie")
            if not asset.acquisition_batch_id:
                missing.append("lote")
            elif asset.acquisition_batch.status not in {
                asset.acquisition_batch.Status.VALIDATED,
                asset.acquisition_batch.Status.CLOSED,
            }:
                missing.append("lote validado")
            elif not asset.acquisition_batch.audit_documents.filter(verified=True).exists():
                missing.append("documentación del lote verificada")
            elif not asset.acquisition_batch.quantity_matches:
                missing.append("cantidad del lote conciliada")
            if missing:
                incomplete.append(f"{asset.internal_code}: {', '.join(missing)}")

        if incomplete:
            raise forms.ValidationError(
                "No se pueden enviar equipos incompletos: " + "; ".join(incomplete)
            )

        return assets

    def clean(self):
        cleaned_data = super().clean()

        delivery_responsible = cleaned_data.get(
            "delivery_responsible"
        )

        if (
            cleaned_data.get("recipient_id_personal") is None
            and not (cleaned_data.get("recipient_email") or "").strip()
        ):
            self.add_error(
                "institutional_recipient",
                "Debe seleccionar el funcionario receptor.",
            )
        else:
            try:
                recipient_identity = _resolve_recipient_identity(cleaned_data)
            except forms.ValidationError as exc:
                self.add_error("institutional_recipient", exc)
            else:
                if recipient_identity is not None:
                    _apply_recipient_identity(cleaned_data, recipient_identity)

        if not delivery_responsible:
            self.add_error(
                "delivery_responsible",
                "Debe seleccionar el responsable de entrega.",
            )
        else:
            try:
                _apply_delivery_responsible_identity(
                    cleaned_data,
                    delivery_responsible,
                )
            except InstitutionalIdentityError:
                pass

        if not cleaned_data.get("authorizing_director"):
            self.add_error(
                "authorizing_director",
                "Debe seleccionar el Director DTI que autorizará la entrega.",
            )

        for field_name, message in {
            "destination_branch": "Debe seleccionar la sede de destino.",
            "department": "Debe registrar el departamento de destino.",
            "location": "Debe registrar la ubicación de destino.",
        }.items():
            if not cleaned_data.get(field_name):
                self.add_error(field_name, message)

        return cleaned_data


class DeliveryDocumentForm(forms.ModelForm):

    class Meta:
        model = DeliveryDocument

        fields = [
            "document_type",
            "file",
            "observations",
        ]

        widgets = {
            "document_type": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),

            "file": forms.ClearableFileInput(
                attrs={
                    "class": "form-control",
                    "accept": ".pdf,.jpg,.jpeg,.png",
                }
            ),

            "observations": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": (
                        "Observación opcional del documento"
                    ),
                }
            ),
        }

    def clean_file(self):
        uploaded_file = self.cleaned_data.get("file")

        if not uploaded_file:
            return uploaded_file

        allowed_extensions = {
            "pdf",
            "jpg",
            "jpeg",
            "png",
        }

        file_name = uploaded_file.name.lower()

        if "." not in file_name:
            raise forms.ValidationError(
                "El archivo debe tener una extensión válida."
            )

        extension = file_name.rsplit(".", 1)[-1]

        if extension not in allowed_extensions:
            raise forms.ValidationError(
                "Solo se permiten archivos PDF, JPG, JPEG o PNG."
            )

        maximum_size = 10 * 1024 * 1024

        if uploaded_file.size > maximum_size:
            raise forms.ValidationError(
                "El archivo no puede superar los 10 MB."
            )

        return uploaded_file


class DeliveryBatchDocumentForm(forms.ModelForm):
    class Meta:
        model = DeliveryBatchDocument
        fields = ["document_type", "file", "observations", "signatures_verified"]
        widgets = {
            "document_type": forms.Select(attrs={"class": "form-control"}),
            "file": forms.ClearableFileInput(
                attrs={"class": "form-control", "accept": ".pdf,.jpg,.jpeg,.png"}
            ),
            "observations": forms.TextInput(attrs={"class": "form-control"}),
            "signatures_verified": forms.CheckboxInput(),
        }

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("document_type") in {
            DeliveryBatchDocument.DocumentType.INTERNAL_DELIVERY,
            DeliveryBatchDocument.DocumentType.PATRIMONIAL_MOVEMENT,
        } and not cleaned_data.get("signatures_verified"):
            self.add_error(
                "signatures_verified",
                "Debe confirmar que verificó las firmas del documento.",
            )
        return cleaned_data
