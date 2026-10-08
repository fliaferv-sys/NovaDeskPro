from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render

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
