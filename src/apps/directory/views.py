from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .services import DirectoryDatabaseError, search_directory_employees


@login_required
def directory_home_view(request):
    search_query = request.GET.get("q", "").strip()
    context = {
        "employees": [],
        "search_query": search_query,
    }

    try:
        context["employees"] = search_directory_employees(
            search_query,
            limit=100,
        )
    except DirectoryDatabaseError:
        context["directory_error"] = (
            "No fue posible consultar el Directorio Institucional "
            "en este momento."
        )

    return render(request, "directory/home.html", context)
