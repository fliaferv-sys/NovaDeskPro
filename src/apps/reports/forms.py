from django import forms

from apps.accounts.models import Branch, User
from apps.core.models import Department
from apps.tickets.models import Ticket


class BaseDateReportFilterForm(forms.Form):
    date_from = forms.DateField(
        required=False,
        label="Fecha desde",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    date_to = forms.DateField(
        required=False,
        label="Fecha hasta",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )

    def clean(self):
        cleaned = super().clean()
        date_from = cleaned.get("date_from")
        date_to = cleaned.get("date_to")
        if date_from and date_to and date_from > date_to:
            raise forms.ValidationError("La fecha desde no puede ser posterior a la fecha hasta.")
        return cleaned


class TicketReportFilterForm(BaseDateReportFilterForm):
    department = forms.ModelChoiceField(
        Department.objects.none(), required=False, label="Departamento",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    technician = forms.ModelChoiceField(
        User.objects.none(), required=False, label="Técnico",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    status = forms.ChoiceField(
        required=False, label="Estado",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    branch = forms.ModelChoiceField(
        Branch.objects.none(), required=False, label="Sede",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.filter(is_active=True)
        self.fields["technician"].queryset = User.objects.filter(
            role=User.Role.TECHNICIAN, is_active=True
        ).order_by("first_name", "last_name", "username")
        self.fields["status"].choices = [("", "Todos")] + list(Ticket.Status.choices)
        self.fields["branch"].queryset = Branch.objects.filter(is_active=True)


class InventoryReportFilterForm(BaseDateReportFilterForm):
    department = forms.ModelChoiceField(
        Department.objects.none(), required=False, label="Departamento",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    branch = forms.ModelChoiceField(
        Branch.objects.none(), required=False, label="Sede",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.filter(is_active=True)
        self.fields["branch"].queryset = Branch.objects.filter(is_active=True)


class PrintingReportFilterForm(BaseDateReportFilterForm):
    ACTIVE_CHOICES = (("", "Todos"), ("true", "Activos"), ("false", "Inactivos"))

    branch = forms.ModelChoiceField(
        Branch.objects.none(), required=False, label="Sede de equipos",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    active = forms.ChoiceField(
        required=False, choices=ACTIVE_CHOICES, label="Estado",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["branch"].queryset = Branch.objects.filter(is_active=True)
