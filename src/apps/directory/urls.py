from django.urls import path

from .views import directory_employee_search_api, directory_home_view


app_name = "directory"

urlpatterns = [
    path("", directory_home_view, name="home"),
    path(
        "api/employees/search/",
        directory_employee_search_api,
        name="employee_search_api",
    ),
]
