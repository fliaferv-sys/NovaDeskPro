/* ==========================================================
   GRÁFICOS INTERACTIVOS DEL DASHBOARD
   NOVADESK PRO — SPRINT 18
   ========================================================== */

   document.addEventListener("DOMContentLoaded", function () {

    if (typeof Chart === "undefined") {
        return;
    }


    /* ======================================================
       UTILIDADES
       ====================================================== */

    const readJsonData = function (elementId) {

        const element = document.getElementById(
            elementId
        );

        if (!element) {
            return [];
        }

        try {
            return JSON.parse(
                element.textContent
            );

        } catch (error) {
            return [];
        }

    };


    const chartInstances = {};


    const destroyChart = function (canvasId) {

        if (chartInstances[canvasId]) {

            chartInstances[canvasId].destroy();

            delete chartInstances[
                canvasId
            ];

        }

    };


    const createChart = function (
        canvasId,
        configuration
    ) {

        const canvas = document.getElementById(
            canvasId
        );

        if (!canvas) {
            return;
        }

        destroyChart(
            canvasId
        );

        chartInstances[canvasId] = new Chart(
            canvas,
            configuration
        );

    };


    const resizeAllCharts = function () {

        window.setTimeout(
            function () {

                Object.values(
                    chartInstances
                ).forEach(
                    function (chart) {

                        if (chart) {
                            chart.resize();
                        }

                    }
                );

            },
            150
        );

    };


    /* ======================================================
       DATOS DEL SERVIDOR
       ====================================================== */

    const dashboardData = {

        technicianLabels: readJsonData(
            "technician-workload-labels"
        ),

        technicianPending: readJsonData(
            "technician-pending-values"
        ),

        technicianClosed: readJsonData(
            "technician-closed-values"
        ),

        ticketStatusLabels: readJsonData(
            "ticket-status-labels"
        ),

        ticketStatusValues: readJsonData(
            "ticket-status-values"
        ),

        assetStatusLabels: readJsonData(
            "asset-status-labels"
        ),

        assetStatusValues: readJsonData(
            "asset-status-values"
        ),

        ticketMonthLabels: readJsonData(
            "ticket-month-labels"
        ),

        ticketMonthValues: readJsonData(
            "ticket-month-values"
        ),

        departmentLabels: readJsonData(
            "department-labels"
        ),

        departmentValues: readJsonData(
            "department-values"
        ),

    };


    /* ======================================================
       CONFIGURACIÓN GENERAL
       ====================================================== */

    const commonLegendOptions = {

        position: "bottom",

        labels: {

            usePointStyle: true,

            pointStyle: "circle",

            padding: 16,

            font: {
                size: 12,
            },

        },

    };


    const categoryColors = [

        "#2563eb",
        "#f59e0b",
        "#16a34a",
        "#dc2626",
        "#7c3aed",
        "#0891b2",
        "#db2777",
        "#64748b",

    ];


    const createNumericScale = function () {

        return {

            beginAtZero: true,

            ticks: {
                precision: 0,
            },

            grid: {
                color: "#e2e8f0",
            },

        };

    };


    /* ======================================================
       CARGA DE TRABAJO POR TÉCNICO
       ====================================================== */

    const renderTechnicianWorkloadChart = function (
        requestedType
    ) {

        const horizontal = (
            requestedType === "bar-horizontal"
        );

        const chartType = "bar";

        createChart(
            "technicianWorkloadChart",
            {

                type: chartType,

                data: {

                    labels: (
                        dashboardData
                        .technicianLabels
                    ),

                    datasets: [

                        {

                            label: "Tickets pendientes",

                            data: (
                                dashboardData
                                .technicianPending
                            ),

                            backgroundColor: "#f59e0b",

                            borderRadius: 7,

                            maxBarThickness: 30,

                        },

                        {

                            label: "Tickets cerrados",

                            data: (
                                dashboardData
                                .technicianClosed
                            ),

                            backgroundColor: "#16a34a",

                            borderRadius: 7,

                            maxBarThickness: 30,

                        },

                    ],

                },

                options: {

                    indexAxis: (
                        horizontal
                            ? "y"
                            : "x"
                    ),

                    responsive: true,

                    maintainAspectRatio: false,

                    interaction: {

                        mode: "index",

                        intersect: false,

                    },

                    plugins: {

                        legend: (
                            commonLegendOptions
                        ),

                        tooltip: {

                            callbacks: {

                                footer: function (
                                    items
                                ) {

                                    const total = (
                                        items.reduce(
                                            function (
                                                sum,
                                                item
                                            ) {

                                                return (
                                                    sum
                                                    + Number(
                                                        item.raw
                                                    )
                                                );

                                            },
                                            0
                                        )
                                    );

                                    if (total === 0) {

                                        return (
                                            "Sin actividad "
                                            + "registrada"
                                        );

                                    }

                                    return (
                                        "Total registrado: "
                                        + total
                                    );

                                },

                            },

                        },

                    },

                    scales: horizontal
                        ? {

                            x: createNumericScale(),

                            y: {

                                grid: {
                                    display: false,
                                },

                            },

                        }
                        : {

                            x: {

                                grid: {
                                    display: false,
                                },

                            },

                            y: createNumericScale(),

                        },

                },

            }
        );

    };


    /* ======================================================
       GRÁFICO CATEGÓRICO
       DONA, TORTA, POLAR O BARRAS
       ====================================================== */

    const renderCategoryChart = function (
        canvasId,
        requestedType,
        labels,
        values,
        datasetLabel,
        defaultType
    ) {

        let chartType = requestedType || defaultType;

        let horizontal = false;


        if (chartType === "bar-horizontal") {

            chartType = "bar";

            horizontal = true;

        }


        const isCircular = [

            "doughnut",
            "pie",
            "polarArea",

        ].includes(
            chartType
        );


        const dataset = {

            label: datasetLabel,

            data: values,

            backgroundColor: isCircular
                ? categoryColors
                : "#2563eb",

            borderWidth: 0,

            borderRadius: (
                chartType === "bar"
                    ? 7
                    : 0
            ),

            maxBarThickness: 42,

        };


        createChart(
            canvasId,
            {

                type: chartType,

                data: {

                    labels: labels,

                    datasets: [
                        dataset,
                    ],

                },

                options: {

                    indexAxis: horizontal
                        ? "y"
                        : "x",

                    responsive: true,

                    maintainAspectRatio: false,

                    cutout: (
                        chartType === "doughnut"
                            ? "68%"
                            : undefined
                    ),

                    plugins: {

                        legend: isCircular
                            ? commonLegendOptions
                            : {
                                display: false,
                            },

                    },

                    scales: isCircular
                        ? {}
                        : horizontal
                            ? {

                                x: createNumericScale(),

                                y: {

                                    grid: {
                                        display: false,
                                    },

                                },

                            }
                            : {

                                x: {

                                    grid: {
                                        display: false,
                                    },

                                },

                                y: createNumericScale(),

                            },

                },

            }
        );

    };


    /* ======================================================
       TICKETS POR ESTADO
       ====================================================== */

    const renderTicketStatusChart = function (
        chartType
    ) {

        renderCategoryChart(

            "ticketStatusChart",

            chartType,

            dashboardData.ticketStatusLabels,

            dashboardData.ticketStatusValues,

            "Tickets",

            "doughnut"

        );

    };


    /* ======================================================
       ESTADO DEL INVENTARIO
       ====================================================== */

    const renderAssetStatusChart = function (
        chartType
    ) {

        renderCategoryChart(

            "assetStatusChart",

            chartType,

            dashboardData.assetStatusLabels,

            dashboardData.assetStatusValues,

            "Activos",

            "doughnut"

        );

    };


    /* ======================================================
       ACTIVOS POR DEPARTAMENTO
       ====================================================== */

    const renderAssetsByDepartmentChart = function (
        chartType
    ) {

        renderCategoryChart(

            "assetsByDepartmentChart",

            chartType,

            dashboardData.departmentLabels,

            dashboardData.departmentValues,

            "Activos",

            "bar-horizontal"

        );

    };


    /* ======================================================
       TICKETS POR MES
       ====================================================== */

    const renderTicketsByMonthChart = function (
        requestedType
    ) {

        let chartType = (
            requestedType || "line"
        );

        let horizontal = false;


        if (chartType === "bar-horizontal") {

            chartType = "bar";

            horizontal = true;

        }


        const isLine = (
            chartType === "line"
        );


        createChart(
            "ticketsByMonthChart",
            {

                type: chartType,

                data: {

                    labels: (
                        dashboardData
                        .ticketMonthLabels
                    ),

                    datasets: [

                        {

                            label: "Tickets",

                            data: (
                                dashboardData
                                .ticketMonthValues
                            ),

                            borderColor: "#2563eb",

                            backgroundColor: isLine
                                ? "rgba(37, 99, 235, 0.12)"
                                : "#2563eb",

                            borderWidth: isLine
                                ? 3
                                : 0,

                            fill: isLine,

                            tension: isLine
                                ? 0.35
                                : 0,

                            pointRadius: isLine
                                ? 4
                                : 0,

                            pointHoverRadius: isLine
                                ? 6
                                : 0,

                            borderRadius: isLine
                                ? 0
                                : 7,

                            maxBarThickness: 42,

                        },

                    ],

                },

                options: {

                    indexAxis: horizontal
                        ? "y"
                        : "x",

                    responsive: true,

                    maintainAspectRatio: false,

                    plugins: {

                        legend: {
                            display: false,
                        },

                    },

                    scales: horizontal
                        ? {

                            x: createNumericScale(),

                            y: {

                                grid: {
                                    display: false,
                                },

                            },

                        }
                        : {

                            x: {

                                grid: {
                                    display: false,
                                },

                            },

                            y: createNumericScale(),

                        },

                },

            }
        );

    };


    /* ======================================================
       TIPOS ORIGINALES
       ====================================================== */

    const defaultChartTypes = {

        technicianWorkloadChart:
            "bar-horizontal",

        ticketStatusChart:
            "doughnut",

        assetStatusChart:
            "doughnut",

        ticketsByMonthChart:
            "line",

        assetsByDepartmentChart:
            "bar-horizontal",

    };


    const renderChart = function (
        canvasId,
        chartType
    ) {

        switch (canvasId) {

            case "technicianWorkloadChart":

                renderTechnicianWorkloadChart(
                    chartType
                );

                break;


            case "ticketStatusChart":

                renderTicketStatusChart(
                    chartType
                );

                break;


            case "assetStatusChart":

                renderAssetStatusChart(
                    chartType
                );

                break;


            case "ticketsByMonthChart":

                renderTicketsByMonthChart(
                    chartType
                );

                break;


            case "assetsByDepartmentChart":

                renderAssetsByDepartmentChart(
                    chartType
                );

                break;

        }

    };


    /* ======================================================
       CREAR LOS GRÁFICOS INICIALES
       ====================================================== */

    Object.entries(
        defaultChartTypes
    ).forEach(
        function (entry) {

            const canvasId = entry[0];

            const chartType = entry[1];

            renderChart(
                canvasId,
                chartType
            );

        }
    );


    /* ======================================================
       ESCUCHAR CAMBIOS SOLICITADOS POR dashboard_grid.js
       ====================================================== */

    document.addEventListener(
        "novadesk:chart-type-change",
        function (event) {

            if (
                !event.detail
                || !event.detail.canvasId
                || !event.detail.chartType
            ) {
                return;
            }

            renderChart(

                event.detail.canvasId,

                event.detail.chartType

            );

            resizeAllCharts();

        }
    );


    /* ======================================================
       AJUSTES POR CAMBIO DE TAMAÑO
       ====================================================== */

    window.addEventListener(
        "resize",
        resizeAllCharts
    );


    window.NovaDeskCharts = {

        instances: chartInstances,

        renderChart: renderChart,

        resizeAll: resizeAllCharts,

    };

});