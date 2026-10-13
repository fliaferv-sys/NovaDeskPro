from django import forms


class IPLookupForm(forms.Form):
    ip = forms.GenericIPAddressField(protocol="IPv4", label="Direccion IPv4",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "192.0.2.1", "autocomplete": "off"}))
