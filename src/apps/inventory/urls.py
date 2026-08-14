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
    stock_category_create_view,
    stock_category_list_view,
    stock_category_update_view,
    stock_entry_view,
    stock_exit_view,
    stock_movement_list_view,
    stock_product_create_view,
    stock_product_detail_view,
    stock_product_list_view,
    stock_product_update_view,
    stock_transfer_view,
)


app_name = "inventory"


urlpatterns = [
    path("stock/", stock_product_list_view, name="stock_product_list"),
    path("stock/productos/nuevo/", stock_product_create_view, name="stock_product_create"),
    path("stock/productos/<uuid:pk>/", stock_product_detail_view, name="stock_product_detail"),
    path("stock/productos/<uuid:pk>/editar/", stock_product_update_view, name="stock_product_update"),
    path("stock/categorias/", stock_category_list_view, name="stock_category_list"),
    path("stock/categorias/nueva/", stock_category_create_view, name="stock_category_create"),
    path("stock/categorias/<uuid:pk>/editar/", stock_category_update_view, name="stock_category_update"),
    path("stock/entrada/", stock_entry_view, name="stock_entry"),
    path("stock/salida/", stock_exit_view, name="stock_exit"),
    path("stock/transferencia/", stock_transfer_view, name="stock_transfer"),
    path("stock/movimientos/", stock_movement_list_view, name="stock_movement_list"),
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
