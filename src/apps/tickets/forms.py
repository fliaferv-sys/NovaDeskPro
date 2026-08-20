# ==========================================================
# FORMULARIOS
# MÓDULO TICKETS
# ==========================================================

from django import forms
from .validators import (
    validate_attachment_extension,
    validate_attachment_size,
)
from .file_security import validate_attachment_signature

from apps.accounts.models import (
    TechnicianWorkday,
    User,
)

from apps.core.models import Department
from apps.inventory.models import Asset
from .models import (
    AuthorizationDocument,
    SystemAccessRequest,
    Ticket,
    TicketAttachment,
    TicketComment,
    
)

# ==========================================================
# FORMULARIO DE TICKETS
# ==========================================================

class TicketForm(forms.ModelForm):

    class Meta:
        model = Ticket

        fields = [
            "asset",
            "printing_device",
            "title",
            "description",
            "priority",
            "category",
        ]

        widgets = {
            "asset": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),
            "printing_device": forms.Select(attrs={"class": "form-control"}),
            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Título del problema",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 5,
                    "placeholder": "Describe el problema...",
                }
            ),
            "priority": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),
            "category": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),
        }

        labels = {
            "asset": "Equipo relacionado",
            "printing_device": "Equipo de impresión tercerizado",
            "title": "Título",
            "description": "Descripción del problema",
            "priority": "Prioridad",
            "category": "Categoría",
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)

        super().__init__(*args, **kwargs)

        self.fields["asset"].required = False
        self.fields["asset"].empty_label = "Sin equipo relacionado"

        if user is not None:
            assets = Asset.objects.filter(
                assigned_user=user
            ).order_by("internal_code")

            self.fields["asset"].queryset = assets

            if assets.count() == 1 and not self.instance.pk:
                self.fields["asset"].initial = assets.first()
        else:
            self.fields["asset"].queryset = Asset.objects.none()

        self.fields["printing_device"].required = False
        self.fields["printing_device"].empty_label = (
            "Sin equipo de impresión relacionado"
        )
        self.fields["printing_device"].queryset = self.fields[
            "printing_device"
        ].queryset.filter(is_active=True, is_outsourced=True)

        self.fields["title"].required = True
        self.fields["description"].required = True
        self.fields["priority"].required = True
        self.fields["category"].required = True

# ==========================================================
# FORMULARIO DE SOLICITUDES DE ACCESO A SISTEMAS
# ALTA, BAJA, MODIFICACIÓN Y PERMISOS
# ==========================================================

class SystemAccessRequestForm(forms.ModelForm):

    SYSTEM_CHOICES = [
        ("", "Seleccione un sistema"),
        ("CORREO_WINDOWS", "Correo y Windows"),
        ("SAP", "SAP"),
        ("GESTOR_EXPEDIENTES", "Gestor de Expedientes"),
        ("AUTOSERVICIO_RRHH", "Autoservicio RR. HH."),
        ("FUELFACS", "FuelFacs"),
        ("GESTION_JURIDICA", "Gestión Jurídica"),
        ("FLOTA", "Flota"),
        ("CADENAS", "Cadenas"),
        ("OPENKM", "OpenKM"),
        ("PAGINA_WEB", "Página web de Petropar"),
    ]

    requested_system = forms.ChoiceField(
        choices=SYSTEM_CHOICES,
        label="Sistema solicitado",
        widget=forms.Select(
            attrs={
                "class": "form-control",
            }
        ),
    )

    class Meta:
        model = SystemAccessRequest

        fields = [
            "requested_system",
            "operation",
            "affected_employee",
            "employee_number",
            "affected_document_number",
            "requested_email",
            "employee_department",
            "employee_position",
            "requested_permissions",
            "justification",
            "authorizing_director",
            "observations",
        ]

        widgets = {
            "operation": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),
            "affected_employee": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Nombre y apellido del funcionario",
                }
            ),
            "employee_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Número de legajo",
                }
            ),
            "affected_document_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Numero de cedula sin puntos",
                }
            ),
            "requested_email": forms.EmailInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "correo@institucion.gov.py",
                }
            ),
            "employee_department": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Departamento o dependencia",
                }
            ),
            "employee_position": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Cargo del funcionario",
                }
            ),
            "requested_permissions": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": (
                        "Describa los permisos, roles o accesos "
                        "que se solicitan"
                    ),
                }
            ),
            "justification": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Justifique la necesidad de la solicitud",
                }
            ),
            "authorizing_director": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Nombre del director autorizante",
                }
            ),
            "observations": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Observaciones adicionales",
                }
            ),
        }

        labels = {
            "operation": "Tipo de operación",
            "affected_employee": "Funcionario afectado",
            "employee_number": "Legajo",
            "affected_document_number": "Numero de cedula",
            "requested_email": "Correo solicitado",
            "employee_department": "Departamento del funcionario",
            "employee_position": "Cargo",
            "requested_permissions": "Permisos solicitados",
            "justification": "Justificación",
            "authorizing_director": "Director autorizante",
            "observations": "Observaciones",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["requested_system"].required = True
        self.fields["operation"].required = True
        self.fields["affected_employee"].required = True
        self.fields["employee_number"].required = True
        self.fields["affected_document_number"].required = True
        self.fields["requested_email"].required = False
        self.fields["employee_department"].required = True
        self.fields["employee_position"].required = False
        self.fields["requested_permissions"].required = False
        self.fields["justification"].required = True
        self.fields["authorizing_director"].required = True
        self.fields["observations"].required = False

    def clean(self):
        cleaned_data = super().clean()

        operation = cleaned_data.get("operation")
        requested_permissions = cleaned_data.get(
            "requested_permissions",
            "",
        ).strip()

        if (
            operation
            == SystemAccessRequest.RequestOperation.PERMISSION_CHANGE
            and not requested_permissions
        ):
            self.add_error(
                "requested_permissions",
                (
                    "Debe indicar los permisos que desea asignar "
                    "o modificar."
                ),
            )

        return cleaned_data


# ==========================================================
# FORMULARIO DE DOCUMENTO DE AUTORIZACIÓN
# FORMULARIO FIRMADO
# ==========================================================

class AuthorizationDocumentForm(forms.ModelForm):

    identity_file = forms.FileField(
        label="Fotocopia de cedula",
        error_messages={
            "required": "Debe adjuntar la fotocopia de cedula.",
        },
        widget=forms.ClearableFileInput(
            attrs={
                "class": "form-control",
                "accept": ".pdf,.jpg,.jpeg,.png",
            }
        ),
    )

    class Meta:
        model = AuthorizationDocument

        fields = [
            "file",
        ]

        widgets = {
            "file": forms.ClearableFileInput(
                attrs={
                    "class": "form-control",
                    "accept": ".pdf,.jpg,.jpeg,.png",
                }
            ),
        }

        labels = {
            "file": "Planilla oficial firmada (PDF)",
        }

        error_messages = {
            "file": {
                "required": (
                    "Debe adjuntar el PDF con la planilla oficial firmada."
                ),
            },
        }

    @staticmethod
    def _validate_uploaded_file(uploaded_file, label):
        if not uploaded_file:
            raise forms.ValidationError(f"Debe adjuntar {label}.")

        allowed_extensions = (".pdf", ".jpg", ".jpeg", ".png")
        if not uploaded_file.name.lower().endswith(allowed_extensions):
            raise forms.ValidationError(
                f"{label.capitalize()} debe estar en formato PDF, JPG o PNG."
            )
        if uploaded_file.size > 10 * 1024 * 1024:
            raise forms.ValidationError(
                f"{label.capitalize()} no puede superar los 10 MB."
            )
        return uploaded_file

    def clean_file(self):
        uploaded_file = self.cleaned_data.get("file")
        uploaded_file = self._validate_uploaded_file(
            uploaded_file, "el formulario firmado"
        )
        if not uploaded_file.name.lower().endswith(".pdf"):
            raise forms.ValidationError(
                "La planilla oficial firmada debe adjuntarse en formato PDF."
            )
        return uploaded_file

    def clean_identity_file(self):
        return self._validate_uploaded_file(
            self.cleaned_data.get("identity_file"),
            "la fotocopia de cedula",
        )


class CorreoWindowsDocumentForm(forms.Form):
    """Documentos oficiales requeridos para un alta de Correo y Windows."""

    form_01 = forms.FileField(
        label="FORMULARIO 01 firmado",
        widget=forms.ClearableFileInput(
            attrs={"class": "form-control", "accept": ".pdf"}
        ),
    )
    form_02 = forms.FileField(
        label="FORMULARIO 02 firmado",
        widget=forms.ClearableFileInput(
            attrs={"class": "form-control", "accept": ".pdf"}
        ),
    )
    form_03 = forms.FileField(
        label="FORMULARIO 03 firmado",
        widget=forms.ClearableFileInput(
            attrs={"class": "form-control", "accept": ".pdf"}
        ),
    )
    identity_file = forms.FileField(
        label="Fotocopia de cedula",
        widget=forms.ClearableFileInput(
            attrs={"class": "form-control", "accept": ".pdf"}
        ),
    )

    def clean(self):
        cleaned_data = super().clean()
        labels = {
            "form_01": "FORMULARIO 01 firmado",
            "form_02": "FORMULARIO 02 firmado",
            "form_03": "FORMULARIO 03 firmado",
            "identity_file": "fotocopia de cedula",
        }
        for field_name, label in labels.items():
            uploaded_file = cleaned_data.get(field_name)
            if not uploaded_file:
                continue
            if not uploaded_file.name.lower().endswith(".pdf"):
                self.add_error(
                    field_name,
                    f"{label} debe estar en formato PDF.",
                )
            elif uploaded_file.size > 10 * 1024 * 1024:
                self.add_error(
                    field_name,
                    f"{label} no puede superar los 10 MB.",
                )
        return cleaned_data


class GestionExpedientesDocumentForm(forms.Form):
    """Documentos requeridos para el alta en Gestion de Expedientes."""

    request_form = forms.FileField(
        label="Formulario de Gestión de Expedientes firmado",
        widget=forms.ClearableFileInput(
            attrs={"class": "form-control", "accept": ".pdf"}
        ),
    )
    identity_file = forms.FileField(
        label="Fotocopia de cedula",
        widget=forms.ClearableFileInput(
            attrs={"class": "form-control", "accept": ".pdf"}
        ),
    )

    def clean(self):
        cleaned_data = super().clean()
        labels = {
            "request_form": "El formulario de Gestión de Expedientes firmado",
            "identity_file": "La fotocopia de cedula",
        }
        for field_name, label in labels.items():
            uploaded_file = cleaned_data.get(field_name)
            if not uploaded_file:
                continue
            if not uploaded_file.name.lower().endswith(".pdf"):
                self.add_error(
                    field_name,
                    f"{label} debe estar en formato PDF.",
                )
            elif uploaded_file.size > 10 * 1024 * 1024:
                self.add_error(
                    field_name,
                    f"{label} no puede superar los 10 MB.",
                )
        return cleaned_data

# ==========================================================
# FORMULARIO DE COMENTARIOS
# ==========================================================

class TicketCommentForm(forms.ModelForm):

    class Meta:

        model = TicketComment

        fields = [
            "message",
        ]

        widgets = {

            "message": forms.Textarea(

                attrs={

                    "class": "form-control",

                    "rows": 3,

                    "placeholder": "Escribe un comentario para el técnico o el solicitante...",

                }

            )

        }

# ==========================================================
# FORMULARIO DE ARCHIVOS ADJUNTOS
# ==========================================================

class TicketAttachmentForm(forms.ModelForm):

    class Meta:

        model = TicketAttachment

        fields = [
            "file",
        ]

        widgets = {

            "file": forms.ClearableFileInput(
                attrs={
                    "class": "form-control",
                }
            ),

        }

    def clean_file(self):

        uploaded_file = self.cleaned_data["file"]

        validate_attachment_extension(uploaded_file)
        validate_attachment_size(uploaded_file)
        validate_attachment_signature(uploaded_file)

        return uploaded_file
# ==========================================================
# FORMULARIO DE ASIGNACIÓN DE TÉCNICO
# SPRINT 10
# ==========================================================

class TicketAssignForm(forms.ModelForm):

    class Meta:

        model = Ticket

        fields = [
            "assigned_to",
            "status",
        ]

        widgets = {

            "assigned_to": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),

            "status": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),

        }

    def __init__(self, *args, department=None, **kwargs):

        super().__init__(*args, **kwargs)

        technicians = User.objects.filter(
            role=User.Role.TECHNICIAN,
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )


        if department is not None:
            technicians = technicians.filter(department=department)

        self.fields["assigned_to"].queryset = (
            technicians
            .distinct()
            .order_by("first_name", "last_name")
        )

        self.fields["assigned_to"].empty_label = (
            "Seleccione un técnico"
        )

class TicketTransferForm(forms.Form):
    destination_department = forms.ModelChoiceField(
        queryset=Department.objects.none(),
        label="Área o departamento destino",
        empty_label="Seleccione el área destino",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    reason = forms.CharField(
        label="Motivo de la derivación",
        min_length=5,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Explique por qué se deriva este ticket.",
            }
        ),
    )

    def __init__(self, *args, current_department=None, **kwargs):
        super().__init__(*args, **kwargs)
        departments = Department.objects.filter(is_active=True)
        if current_department is not None:
            departments = departments.exclude(pk=current_department.pk)
        self.fields["destination_department"].queryset = departments.order_by(
            "order", "name"
        )
