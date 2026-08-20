from django import forms

from apps.inventory.models import StockBalance, StockProduct

from .models import Consumable, ConsumableCompatibility
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.stock_product_id:
            self.initial["minimum_stock"] = self.instance.stock_product.minimum_stock
            self.fields["minimum_stock"].help_text = (
                "Vinculado con Inventory: al guardar, este valor actualiza el "
                "stock mínimo del producto de stock asociado."
            )
        else:
            self.fields["minimum_stock"].help_text = (
                "Se mantiene en Printing mientras no exista un producto de stock vinculado."
            )

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


class PrintingTicketStockUsageForm(forms.Form):
    compatibility = forms.ModelChoiceField(
        queryset=ConsumableCompatibility.objects.none(),
        label="Consumible compatible",
    )
    stock_balance = forms.ModelChoiceField(
        queryset=StockBalance.objects.none(),
        label="Origen del stock",
    )
    quantity = forms.IntegerField(label="Cantidad", min_value=1)
    observation = forms.CharField(
        label="Observación",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, printing_device, **kwargs):
        super().__init__(*args, **kwargs)
        self.printing_device = printing_device
        compatibilities = (
            ConsumableCompatibility.objects.filter(
                printing_device=printing_device,
                is_active=True,
                consumable__is_active=True,
                consumable__stock_product__is_active=True,
                consumable__stock_product__balances__quantity__gt=0,
            )
            .select_related("consumable__stock_product")
            .distinct()
            .order_by("consumable__name", "consumable__reference_code")
        )
        product_ids = compatibilities.values_list(
            "consumable__stock_product_id", flat=True
        )
        balances = (
            StockBalance.objects.filter(
                product_id__in=product_ids,
                quantity__gt=0,
                branch__is_active=True,
                organizational_location__is_active=True,
            )
            .select_related("product", "branch", "organizational_location")
            .order_by("branch__name", "organizational_location__name", "product__name")
        )
        self.fields["compatibility"].queryset = compatibilities
        self.fields["stock_balance"].queryset = balances
        self.fields["compatibility"].label_from_instance = lambda item: (
            f"{item.consumable.reference_code} - {item.consumable.name}"
        )
        self.fields["stock_balance"].label_from_instance = lambda balance: (
            f"{balance.product.reference_code} - {balance.product.name} | "
            f"{balance.branch.name} / {balance.organizational_location.full_path} "
            f"(disponible: {balance.quantity})"
        )

        if not self.is_bound and compatibilities.count() == 1:
            compatibility = compatibilities.first()
            self.initial["compatibility"] = compatibility.pk
            local_balances = balances.filter(
                product=compatibility.consumable.stock_product,
                branch=printing_device.effective_branch,
            )
            if local_balances.count() == 1:
                self.initial["stock_balance"] = local_balances.first().pk

    def clean(self):
        cleaned_data = super().clean()
        compatibility = cleaned_data.get("compatibility")
        balance = cleaned_data.get("stock_balance")
        quantity = cleaned_data.get("quantity")

        if compatibility:
            consumable = compatibility.consumable
            if compatibility.printing_device_id != self.printing_device.pk:
                self.add_error("compatibility", "El consumible no corresponde a esta impresora.")
            if not compatibility.is_active or not consumable.is_active:
                self.add_error("compatibility", "El consumible compatible debe estar activo.")
            if not consumable.stock_product_id or not consumable.stock_product.is_active:
                self.add_error(
                    "compatibility",
                    "El consumible debe tener un producto de stock activo vinculado.",
                )
            elif balance and balance.product_id != consumable.stock_product_id:
                self.add_error(
                    "stock_balance",
                    "El origen seleccionado no corresponde al consumible.",
                )

        if balance:
            if balance.organizational_location.branch_id != balance.branch_id:
                self.add_error("stock_balance", "La ubicación no pertenece a la sede indicada.")
            if quantity and balance.quantity < quantity:
                self.add_error("quantity", "Stock insuficiente para registrar el consumo.")

        return cleaned_data
