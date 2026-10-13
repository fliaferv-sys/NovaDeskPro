from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from django import forms
from django.core.validators import RegexValidator

from apps.accounts.access import roles_required
from apps.integrations.technical_context import resolve_technical_context
from .context_snapshot import review_token


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
    if not form.cleaned_data.get("ip") and not form.cleaned_data.get("hostname"):
        return JsonResponse({"error": "Ingrese IP o hostname."}, status=400)
    try:
        query = {key: form.cleaned_data[key] for key in ("ip", "hostname")}
        context = resolve_technical_context(requester=request.user, **query)
        context["review_token"] = review_token(context, request.user, query)
        return JsonResponse(context)
    except Exception:
        return JsonResponse({"error": "Contexto tecnico no disponible. Puede continuar manualmente."}, status=503)
