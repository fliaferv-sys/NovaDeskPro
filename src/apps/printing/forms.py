from django import forms

from apps.inventory.models import StockProduct

from .models import Consumable
from .reconciliation import normalize_reference_code


def find_stock_product_candidates(reference_code):
    """Return exact normalized matches without changing stored references."""
    normalized_code = normalize_reference_code(reference_code)
    if not normalized_code:
        return []
    return [
        product
        for product in StockProduct.objects.order_by("reference_code", "pk")
        if normalize_reference_code(product.reference_code) == normalized_code
    ]


class ConsumableAdminForm(forms.ModelForm):
    create_stock_product = forms.BooleanField(
        required=False,
        label="Crear producto de stock en Inventory",
        help_text=(
            "Crea y vincula un producto activo, con unidad Unidad y stock cero, "
            "usando el nombre, código, fabricante y modelo del consumible."
        ),
    )

    class Meta:
        model = Consumable
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        stock_product = cleaned_data.get("stock_product")
        create_stock_product = cleaned_data.get("create_stock_product")

        if stock_product and create_stock_product:
            self.add_error(
                "create_stock_product",
                "Seleccione un producto existente o cree uno nuevo, no ambos.",
            )
            return cleaned_data

        if create_stock_product:
            candidates = find_stock_product_candidates(
                cleaned_data.get("reference_code")
            )
            if len(candidates) == 1:
                self.add_error(
                    "create_stock_product",
                    (
                        "Ya existe un producto con el mismo código normalizado: "
                        f"{candidates[0]}. Selecciónelo explícitamente."
                    ),
                )
            elif len(candidates) > 1:
                self.add_error(
                    "create_stock_product",
                    (
                        "Hay varios productos con el mismo código normalizado. "
                        "Revise y seleccione uno explícitamente."
                    ),
                )

        return cleaned_data
