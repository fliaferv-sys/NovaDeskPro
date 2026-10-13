from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from django import forms
from django.core.validators import RegexValidator

from apps.accounts.access import roles_required
from apps.integrations.technical_context import resolve_technical_context
from .context_snapshot import review_token
from apps.integrations.automatic_context import resolve_automatic_context, automatic_selection
from django.core.cache import cache


class ContextQueryForm(forms.Form):
    ip = forms.GenericIPAddressField(protocol="IPv4", required=False)
    hostname = forms.CharField(max_length=150, required=False, validators=[RegexValidator(r"^[A-Za-z0-9._-]+$")])
    username = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False)


@login_required
@roles_required("ADMIN", "TECHNICIAN", "CLIENT")
@never_cache
@require_GET
def ticket_automatic_context(request):
    # Per-account cache contains only the already-whitelisted resolver result.
    key = f"ticket-auto-context-v1:{request.user.pk}"
    try:
        context = cache.get(key)
        if context is None:
            context = resolve_automatic_context(request.user)
            cache.set(key, context, 60)
        context = {**context}
        selected = automatic_selection(context)
        context["review_token"] = review_token(context, request.user, {"automatic": True})
        context["automatic_selection"] = selected
        if request.user.role == "CLIENT" and not request.user.is_superuser:
            device = context["devices"][0] if selected else None
            return JsonResponse({"requester": context.get("requester"), "device_name": device["data"].get("name") if device else None,
                                 "review_token": context["review_token"], "automatic_selection": selected})
        return JsonResponse(context)
    except Exception:
        return JsonResponse({"devices": [], "automatic_selection": None})


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
