from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from apps.accounts.access import roles_required
from .forms import IPLookupForm
from .ip_lookup import lookup_ip, IPLookupError


@login_required
@roles_required("ADMIN", "TECHNICIAN")
@never_cache
@require_GET
def ip_lookup_view(request):
    form = IPLookupForm(request.GET if "ip" in request.GET else None)
    result, error = None, ""
    if form.is_bound and form.is_valid():
        try:
            result = lookup_ip(form.cleaned_data["ip"])
        except IPLookupError as exc:
            error = str(exc)
    response = render(request, "integrations/ip_lookup.html", {"form": form, "result": result, "lookup_error": error})
    response["Referrer-Policy"] = "same-origin"
    return response
