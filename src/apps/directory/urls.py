from django.urls import path

from .views import directory_employee_search_api, directory_home_view, identity_search_api, identity_resolve_api


app_name = "directory"

urlpatterns = [
    path("api/identities/search/", identity_search_api, name="identity_search_api"),
    path("api/identities/resolve/", identity_resolve_api, name="identity_resolve_api"),
    path("", directory_home_view, name="home"),
    path(
        "api/employees/search/",
        directory_employee_search_api,
        name="employee_search_api",
    ),
]
