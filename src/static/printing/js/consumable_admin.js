(function () {
    "use strict";

    function candidateEndpoint() {
        const marker = "/admin/printing/consumable/";
        const markerIndex = window.location.pathname.indexOf(marker);
        if (markerIndex === -1) return null;
        return (
            window.location.pathname.slice(0, markerIndex) +
            marker +
            "stock-product-candidates/"
        );
    }

    function ensureStatusElement(referenceInput) {
        let status = document.getElementById("stock-product-candidate-status");
        if (!status) {
            status = document.createElement("div");
            status.id = "stock-product-candidate-status";
            status.className = "help";
            status.style.marginTop = "8px";
            referenceInput.closest(".form-row").appendChild(status);
        }
        return status;
    }

    async function updateCandidates() {
        const referenceInput = document.getElementById("id_reference_code");
        const endpoint = candidateEndpoint();
        if (!referenceInput || !endpoint) return;

        const status = ensureStatusElement(referenceInput);
        const referenceCode = referenceInput.value.trim();
        if (!referenceCode) {
            status.textContent = "";
            return;
        }

        const response = await fetch(
            endpoint + "?reference_code=" + encodeURIComponent(referenceCode),
            {headers: {"X-Requested-With": "XMLHttpRequest"}}
        );
        if (!response.ok) return;
        const data = await response.json();

        if (data.count === 1) {
            status.textContent =
                "Candidato exacto disponible: " + data.candidates[0].label +
                ". Selecciónelo explícitamente en Producto de stock.";
        } else if (data.count > 1) {
            status.textContent =
                "Hay múltiples coincidencias exactas normalizadas; no se seleccionará ninguna automáticamente.";
        } else {
            status.textContent =
                "No existe un producto con este código. Puede marcar Crear producto de stock en Inventory.";
        }
    }

    document.addEventListener("DOMContentLoaded", function () {
        const referenceInput = document.getElementById("id_reference_code");
        if (!referenceInput) return;
        referenceInput.addEventListener("change", updateCandidates);
        referenceInput.addEventListener("blur", updateCandidates);
        updateCandidates();
    });
}());
