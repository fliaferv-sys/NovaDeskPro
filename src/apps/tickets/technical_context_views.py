from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from django import forms
from django.core.validators import RegexValidator

from apps.accounts.access import roles_required
from apps.integrations.technical_context import resolve_technical_context


class ContextQueryForm(forms.Form):
    ip = forms.GenericIPAddressField(protocol="IPv4", required=False)
    hostname = forms.CharField(max_length=150, required=False, validators=[RegexValidator(r"^[A-Za-z0-9._-]+$")])
    username = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False)


@login_required
@roles_required("ADMIN", "TECHNICIAN")
@never_cache
@require_GET
def ticket_technical_context(request):
    form = ContextQueryForm(request.GET)
    if not form.is_valid():
        return JsonResponse({"error": "Datos de consulta invalidos."}, status=400)
    try:
        return JsonResponse(resolve_technical_context(requester=request.user, **form.cleaned_data))
    except Exception:
        return JsonResponse({"error": "Contexto tecnico no disponible. Puede continuar manualmente."}, status=503)
