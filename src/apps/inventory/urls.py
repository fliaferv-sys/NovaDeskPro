from django.urls import path

from .import_views import (
    asset_import_template_view,
    asset_import_view,
)
from .views import (
    asset_create_view,
    asset_detail_view,
    asset_list_view,
    asset_update_view,
    technical_history_create_view,
    my_asset_list,  # ✅ YA ESTÁ IMPORTADO
)


app_name = "inventory"


urlpatterns = [
    path(
        "",
        asset_list_view,
        name="asset_list",
    ),
    path('my-assets/', my_asset_list, name='my_asset_list'),  # ✅ CORREGIDO (sin views.)

    path(
        "nuevo/",
        asset_create_view,
        name="asset_create",
    ),
    path(
        "importar/",
        asset_import_view,
        name="asset_import",
    ),
    path(
        "importar/plantilla/",
        asset_import_template_view,
        name="asset_import_template",
    ),
    path(
        "<uuid:pk>/",
        asset_detail_view,
        name="asset_detail",
    ),
    path(
        "<uuid:pk>/editar/",
        asset_update_view,
        name="asset_update",
    ),
    path(
        "<uuid:asset_pk>/intervenciones/nueva/",
        technical_history_create_view,
        name="technical_history_create",
    ),
    
]