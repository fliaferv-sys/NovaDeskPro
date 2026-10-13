from django.urls import path
from .views import ip_lookup_view

app_name = "integrations"
urlpatterns = [path("ip/", ip_lookup_view, name="ip_lookup")]
