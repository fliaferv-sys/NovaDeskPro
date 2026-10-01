from django.urls import path

from .views import directory_home_view


app_name = "directory"

urlpatterns = [
    path("", directory_home_view, name="home"),
]
