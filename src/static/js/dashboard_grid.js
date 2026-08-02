/* ==========================================================
   DASHBOARD INTERACTIVO Y PREFERENCIAS POR USUARIO
   NOVADESK PRO — SPRINT 19.5
   ========================================================== */

   document.addEventListener("DOMContentLoaded", function () {
    "use strict";

    /* ======================================================
       ELEMENTOS PRINCIPALES
       ====================================================== */

    const dashboardGridElement = document.querySelector(
        ".dashboard-grid"
    );

    const preferenceConfig = document.getElementById(
        "dashboardPreferenceConfig"
    );

    if (
        !dashboardGridElement
        || !preferenceConfig
        || typeof GridStack === "undefined"
    ) {
        return;
    }

    const saveUrl = preferenceConfig.dataset.saveUrl;
    const resetUrl = preferenceConfig.dataset.resetUrl;

    const editButton = document.getElementById(
        "dashboardEditButton"
    );

    const saveButton = document.getElementById(
        "dashboardSaveButton"
    );

    const resetButton = document.getElementById(
        "dashboardResetButton"
    );

    const chartSelectors = document.querySelectorAll(
        "[data-chart-selector]"
    );

    let isSaving = false;


    /* ======================================================
       LEER JSON GENERADO POR DJANGO
       ====================================================== */

    const readJsonData = function (
        elementId,
        defaultValue
    ) {
        const element = document.getElementById(
            elementId
        );

        if (!element) {
            return defaultValue;
        }

        try {
            return JSON.parse(
                element.textContent
            );

        } catch (error) {
            console.error(
                "No fue posible leer:",
                elementId,
                error
            );

            return defaultValue;
        }
    };


    const savedDashboardLayout = readJsonData(
        "saved-dashboard-layout",
        []
    );

    const savedDashboardChartTypes = readJsonData(
        "saved-dashboard-chart-types",
        {}
    );


    /* ======================================================
       OBTENER TOKEN CSRF DE DJANGO
       ====================================================== */

    const getCookie = function (cookieName) {
        let cookieValue = null;

        if (
            document.cookie
            && document.cookie !== ""
        ) {
            const cookies = document.cookie.split(";");

            for (
                let index = 0;
                index < cookies.length;
                index += 1
            ) {
                const cookie = cookies[index].trim();

                if (
                    cookie.substring(
                        0,
                        cookieName.length + 1
                    ) === cookieName + "="
                ) {
                    cookieValue = decodeURIComponent(
                        cookie.substring(
                            cookieName.length + 1
                        )
                    );

                    break;
                }
            }
        }

        return cookieValue;
    };


    const csrfToken = getCookie(
        "csrftoken"
    );


    /* ======================================================
       INICIALIZAR GRIDSTACK
       ====================================================== */

    const grid = GridStack.init(
        {
            column: 12,
            cellHeight: 82,
            // GridStack aplica este margen a ambos widgets contiguos.
            // 9.5 px por lado producen una separación visible de 19 px (5 mm).
            margin: 9.5,
            float: false,
            animate: true,

            handle: ".dashboard-widget-handle",

            resizable: {
                handles: "e,se,s,sw,w",
            },
        },
        dashboardGridElement
    );


    /* ======================================================
       CAMBIAR CONTENIDO DE BOTONES
       ====================================================== */

    const setButtonContent = function (
        button,
        iconClass,
        text
    ) {
        if (!button) {
            return;
        }

        button.innerHTML = (
            '<i class="bi '
            + iconClass
            + '"></i> '
            + text
        );
    };


    const restoreSaveButton = function () {
        setButtonContent(
            saveButton,
            "bi-floppy",
            "Guardar"
        );
    };


    const showSaveSuccess = function () {
        if (!saveButton) {
            return;
        }

        setButtonContent(
            saveButton,
            "bi-check-circle",
            "Diseño guardado"
        );

        window.setTimeout(
            restoreSaveButton,
            1800
        );
    };


    /* ======================================================
       REDIMENSIONAR LOS GRÁFICOS
       ====================================================== */

    const resizeDashboardCharts = function () {
        window.setTimeout(
            function () {
                if (
                    window.NovaDeskCharts
                    && typeof (
                        window.NovaDeskCharts.resizeAll
                    ) === "function"
                ) {
                    window.NovaDeskCharts.resizeAll();
                    return;
                }

                if (
                    typeof Chart !== "undefined"
                    && Chart.instances
                ) {
                    Object.values(
                        Chart.instances
                    ).forEach(
                        function (chart) {
                            if (chart) {
                                chart.resize();
                            }
                        }
                    );
                }
            },
            160
        );
    };


        /* ======================================================
   ACTIVAR O DESACTIVAR EL MODO DE PERSONALIZACIÓN
   ====================================================== */

const setEditingMode = function (enabled) {

    grid.enableMove(enabled);
    grid.enableResize(enabled);

    dashboardGridElement.classList.toggle(
        "dashboard-grid-editing",
        enabled
    );

    if (editButton) {
        editButton.hidden = enabled;
    }

    if (saveButton) {
        saveButton.hidden = !enabled;
        saveButton.disabled = false;
    }

    if (resetButton) {
        resetButton.hidden = !enabled;
        resetButton.disabled = false;
    }

    chartSelectors.forEach(function (selector) {
        selector.disabled = !enabled;
    });

    resizeDashboardCharts();

};


    /* ======================================================
       APLICAR TIPO DE GRÁFICO
       ====================================================== */

    const applyChartType = function (
        canvasId,
        chartType
    ) {
        document.dispatchEvent(
            new CustomEvent(
                "novadesk:chart-type-change",
                {
                    detail: {
                        canvasId: canvasId,
                        chartType: chartType,
                    },
                }
            )
        );
    };


    /* ======================================================
       OBTENER LOS TIPOS ELEGIDOS ACTUALMENTE
       ====================================================== */

    const collectChartTypes = function () {
        const chartTypes = {};

        chartSelectors.forEach(
            function (selector) {
                const canvasId = (
                    selector.dataset.chartTarget
                );

                if (
                    canvasId
                    && selector.value
                ) {
                    chartTypes[canvasId] = (
                        selector.value
                    );
                }
            }
        );

        return chartTypes;
    };


    /* ======================================================
       RESTAURAR TIPOS DE GRÁFICOS GUARDADOS
       ====================================================== */

    const loadSavedChartTypes = function () {
        if (
            !savedDashboardChartTypes
            || typeof savedDashboardChartTypes !== "object"
        ) {
            return;
        }

        chartSelectors.forEach(
            function (selector) {
                const canvasId = (
                    selector.dataset.chartTarget
                );

                const savedType = (
                    savedDashboardChartTypes[
                        canvasId
                    ]
                );

                if (!savedType) {
                    return;
                }

                const optionExists = Array.from(
                    selector.options
                ).some(
                    function (option) {
                        return (
                            option.value === savedType
                        );
                    }
                );

                if (!optionExists) {
                    return;
                }

                selector.value = savedType;

                applyChartType(
                    canvasId,
                    savedType
                );
            }
        );
    };


    /* ======================================================
       CARGAR DISTRIBUCIÓN GUARDADA
       ====================================================== */

    const loadSavedLayout = function () {
        if (
            !Array.isArray(
                savedDashboardLayout
            )
            || savedDashboardLayout.length === 0
        ) {
            return;
        }

        try {
            grid.load(
                savedDashboardLayout,
                false
            );

        } catch (error) {
            console.error(
                "No fue posible cargar el diseño guardado.",
                error
            );
        }
    };


    /* ======================================================
       GUARDAR DISTRIBUCIÓN Y GRÁFICOS
       ====================================================== */

    const saveDashboardPreference = async function () {
        if (isSaving) {
            return;
        }

        isSaving = true;

        if (saveButton) {
            saveButton.disabled = true;

            setButtonContent(
                saveButton,
                "bi-hourglass-split",
                "Guardando..."
            );
        }

        if (resetButton) {
            resetButton.disabled = true;
        }

        const layout = grid.save(
            false,
            false
        );

        const chartTypes = collectChartTypes();

        try {
            const response = await fetch(
                saveUrl,
                {
                    method: "POST",

                    headers: {
                        "Content-Type": (
                            "application/json"
                        ),
                        "X-CSRFToken": csrfToken,
                        "X-Requested-With": (
                            "XMLHttpRequest"
                        ),
                    },

                    credentials: "same-origin",

                    body: JSON.stringify(
                        {
                            layout: layout,
                            chart_types: chartTypes,
                        }
                    ),
                }
            );

            const result = await response.json();

            if (
                !response.ok
                || !result.success
            ) {
                throw new Error(
                    result.message
                    || "No fue posible guardar el diseño."
                );
            }

            setEditingMode(false);
            showSaveSuccess();
            resizeDashboardCharts();

        } catch (error) {
            console.error(
                "Error al guardar el dashboard:",
                error
            );

            window.alert(
                "No se pudo guardar el diseño. "
                + error.message
            );

            restoreSaveButton();

        } finally {
            isSaving = false;

            if (saveButton) {
                saveButton.disabled = false;
            }

            if (resetButton) {
                resetButton.disabled = false;
            }
        }
    };


    /* ======================================================
       RESTAURAR EL DISEÑO ORIGINAL
       ====================================================== */

    const resetDashboardPreference = async function () {
        const confirmed = window.confirm(
            "¿Desea restaurar el diseño y los tipos "
            + "de gráfico originales?"
        );

        if (!confirmed) {
            return;
        }

        if (resetButton) {
            resetButton.disabled = true;

            setButtonContent(
                resetButton,
                "bi-hourglass-split",
                "Restaurando..."
            );
        }

        if (saveButton) {
            saveButton.disabled = true;
        }

        try {
            const response = await fetch(
                resetUrl,
                {
                    method: "POST",

                    headers: {
                        "X-CSRFToken": csrfToken,
                        "X-Requested-With": (
                            "XMLHttpRequest"
                        ),
                    },

                    credentials: "same-origin",
                }
            );

            const result = await response.json();

            if (
                !response.ok
                || !result.success
            ) {
                throw new Error(
                    result.message
                    || "No fue posible restaurar el diseño."
                );
            }

            localStorage.removeItem(
                "novadesk_dashboard_layout_v1"
            );

            localStorage.removeItem(
                "novadesk_dashboard_chart_types_v1"
            );

            window.location.reload();

        } catch (error) {
            console.error(
                "Error al restaurar el dashboard:",
                error
            );

            window.alert(
                "No se pudo restaurar el dashboard. "
                + error.message
            );

            if (resetButton) {
                resetButton.disabled = false;

                setButtonContent(
                    resetButton,
                    "bi-arrow-counterclockwise",
                    "Restaurar"
                );
            }

            if (saveButton) {
                saveButton.disabled = false;
                restoreSaveButton();
            }
        }
    };


    /* ======================================================
       EVENTOS DE BOTONES
       ====================================================== */

    if (editButton) {
        editButton.addEventListener(
            "click",
            function () {
                setEditingMode(true);
            }
        );
    }


    if (saveButton) {
        saveButton.addEventListener(
            "click",
            saveDashboardPreference
        );
    }


    if (resetButton) {
        resetButton.addEventListener(
            "click",
            resetDashboardPreference
        );
    }


    /* ======================================================
       EVENTOS DE SELECTORES DE GRÁFICOS
       ====================================================== */

    chartSelectors.forEach(
        function (selector) {
            selector.addEventListener(
                "change",
                function () {
                    const canvasId = (
                        selector.dataset.chartTarget
                    );

                    const chartType = (
                        selector.value
                    );

                    applyChartType(
                        canvasId,
                        chartType
                    );

                    resizeDashboardCharts();
                }
            );
        }
    );


    /* ======================================================
       EVENTOS DE GRIDSTACK
       ====================================================== */

    grid.on(
        "change resizestop dragstop",
        function () {
            resizeDashboardCharts();
        }
    );


    /* ======================================================
       ESTADO INICIAL
       ====================================================== */

    loadSavedLayout();

    setEditingMode(false);

    window.setTimeout(
        function () {
            loadSavedChartTypes();
            resizeDashboardCharts();
        },
        300
    );
});
