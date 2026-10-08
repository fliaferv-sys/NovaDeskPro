from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.core.exceptions import ValidationError
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST

from .identity_policies import (
    authorize_identity_context, account_form_values, serialize_identity,
    issue_identity_reference, validate_identity_reference,
)
from .identity_services import search_common_identities

from apps.directory.identity_services import (
    InstitutionalIdentityError,
    build_institutional_kpis,
    get_institutional_directory,
    search_institutional_identities,
)
from apps.directory.services import DirectoryDatabaseError

@login_required
def directory_employee_search_api(request):
    query = request.GET.get("q", "").strip()
    if len(query) < 2:
        return JsonResponse({"employees": []})

    try:
        directory_employees = search_institutional_identities(
            query,
            limit=20,
        )
    except InstitutionalIdentityError:
        return JsonResponse(
            {
                "employees": [],
                "error": "No fue posible consultar el Directorio Institucional.",
            },
            status=503,
        )

    employees = [
        {
            "source": employee["source"],
            "id_personal": employee["id_personal"],
            "employee_number": employee["employee_number"],
            "name": employee["name"],
            "first_name": employee["first_name"],
            "last_name": employee["last_name"],
            "location": employee["location"],
            "phone": employee["phone"],
            "email": employee["email"],
            "status": employee["status"],
            "employment_type": employee["employment_type"],
            "position": employee["position"],
            "username": employee["username"],
            "is_active": employee["is_active"],
            "organizational_unit": employee.get("organizational_unit"),
            "organizational_path": employee.get("organizational_path", []),
	    "photo_url": employee.get("photo_url", ""),
        }
        for employee in directory_employees
    ]
    return JsonResponse({"employees": employees})


@login_required
def directory_home_view(request):
    search_query = request.GET.get("q", "").strip()
    context = {
        "employees": [],
        "search_query": search_query,
    }

    try:
        directory = get_institutional_directory()
        context["directory_kpis"] = build_institutional_kpis(directory)
        if search_query:
            context["employees"] = search_institutional_identities(
                search_query,
                limit=100,
            )
        else:
            context["employees"] = directory
    except (DirectoryDatabaseError, InstitutionalIdentityError):
        context["employees"] = []
        context["directory_error"] = (
            "No fue posible consultar el Directorio Institucional "
            "en este momento."
        )

    return render(request, "directory/home.html", context)


@login_required
@never_cache
@require_POST
@sensitive_post_parameters("q", "reference")
def identity_search_api(request):
    try:
        payload = _identity_request_payload(request)
        policy = authorize_identity_context(request, payload.get("context"), payload.get("object_id", ""))
        result = search_common_identities(payload.get("q", ""), payload.get("field", "email"))
    except (ValueError, TypeError):
        return JsonResponse({"status": "invalid"}, status=400)
    candidates = [serialize_identity(request, policy, item, summary=True) for item in result["identities"]]
    data = {"status": "candidates" if candidates else "not_found", "candidates": candidates, "incomplete": result["incomplete"]}
    if result["exact_unique"]:
        # Resolve once more before returning an automatic match.
        selected = result["exact_identity"]
        reference = issue_identity_reference(request, policy, selected)
        try:
            selected = validate_identity_reference(request, policy, reference)
        except ValidationError:
            data["incomplete"] = True
        else:
            data.update(status="resolved", identity=serialize_identity(request, policy, selected), values=account_form_values(selected))
    if data["incomplete"] and not candidates:
        data["status"] = "unavailable"
    return JsonResponse(data, status=503 if data["status"] == "unavailable" else 200)


@login_required
@never_cache
@require_POST
@sensitive_post_parameters("reference")
def identity_resolve_api(request):
    try:
        payload = _identity_request_payload(request)
        policy = authorize_identity_context(request, payload.get("context"), payload.get("object_id", ""))
        identity = validate_identity_reference(request, policy, payload.get("reference", ""))
    except (ValueError, TypeError):
        return JsonResponse({"status": "invalid"}, status=400)
    except ValidationError:
        return JsonResponse({"status": "invalid_selection"}, status=409)
    return JsonResponse({"status": "resolved", "identity": serialize_identity(request, policy, identity), "values": account_form_values(identity)})


def _identity_request_payload(request):
    import json
    if len(request.body) > 8192:
        raise ValueError("Request too large")
    payload = json.loads(request.body)
    if not isinstance(payload, dict) or set(payload) - {"context", "object_id", "q", "field", "reference"}:
        raise ValueError("Invalid identity request")
    if any(not isinstance(value, str) for value in payload.values()):
        raise ValueError("Invalid identity parameters")
    return payload
