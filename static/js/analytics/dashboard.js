(function () {
    "use strict";

    const dataElement = document.getElementById(
        "analytics-chart-data"
    );

    if (!dataElement) {
        return;
    }

    if (typeof window.Chart === "undefined") {
        document.querySelectorAll(
            ".chart-stage"
        ).forEach(function (stage) {
            stage.innerHTML = (
                '<div class="chart-error">' +
                "تعذر تحميل مكتبة الرسوم البيانية." +
                "</div>"
            );
        });

        return;
    }

    let chartData;

    try {
        chartData = JSON.parse(
            dataElement.textContent
        );
    } catch (error) {
        return;
    }

    const moneyFormatter = new Intl.NumberFormat(
        "ar-IQ",
        {
            maximumFractionDigits: 0
        }
    );

    const chartInstances = [];

    function themeColors() {
        const darkMode = (
            document.documentElement.getAttribute(
                "data-theme"
            ) === "dark"
        );

        return {
            blue: "#2878ff",
            green: "#13a874",
            orange: "#e59a18",
            red: "#e65361",
            violet: "#7658e8",

            text: darkMode
                ? "#91ac9b"
                : "#718096",

            strongText: darkMode
                ? "#e8f5ed"
                : "#172033",

            grid: darkMode
                ? "rgba(126, 170, 142, 0.13)"
                : "rgba(113, 128, 150, 0.13)",

            tooltip: darkMode
                ? "#e8f5ed"
                : "#172033",

            tooltipText: darkMode
                ? "#172033"
                : "#ffffff"
        };
    }

    function tooltipOptions(colors) {
        return {
            rtl: true,
            textDirection: "rtl",
            backgroundColor: colors.tooltip,
            titleColor: colors.tooltipText,
            bodyColor: colors.tooltipText,
            padding: 12,
            cornerRadius: 10,
            displayColors: true
        };
    }

    function cartesianScales(
        colors,
        options
    ) {
        const settings = options || {};

        return {
            x: {
                stacked: Boolean(
                    settings.stacked
                ),

                grid: {
                    display: false
                },

                border: {
                    display: false
                },

                ticks: {
                    color: colors.text,
                    maxRotation: 0,
                    autoSkip: true,
                    maxTicksLimit: 10,

                    font: {
                        size: 10,
                        weight: "600"
                    }
                }
            },

            y: {
                stacked: Boolean(
                    settings.stacked
                ),

                beginAtZero: true,

                border: {
                    display: false
                },

                grid: {
                    color: colors.grid
                },

                ticks: {
                    color: colors.text,

                    precision: settings.money
                        ? undefined
                        : 0,

                    callback: settings.money
                        ? function (value) {
                            return moneyFormatter.format(
                                value
                            );
                        }
                        : undefined,

                    font: {
                        size: 10,
                        weight: "600"
                    }
                }
            }
        };
    }

    function legendOptions() {
        return {
            position: "bottom",
            rtl: true,

            labels: {
                usePointStyle: true,
                boxWidth: 9,
                padding: 17
            }
        };
    }

    function destroyCharts() {
        while (chartInstances.length) {
            const chart = chartInstances.pop();
            chart.destroy();
        }
    }

    const centerTextPlugin = {
        id: "analyticsCenterText",

        afterDraw: function (chart) {
            if (chart.config.type !== "doughnut") {
                return;
            }

            const chartArea = chart.chartArea;

            if (!chartArea) {
                return;
            }

            const values = (
                chart.data.datasets[0].data || []
            );

            const total = values.reduce(
                function (sum, value) {
                    return sum + Number(
                        value || 0
                    );
                },
                0
            );

            const colors = themeColors();

            const centerX = (
                chartArea.left + chartArea.right
            ) / 2;

            const centerY = (
                chartArea.top + chartArea.bottom
            ) / 2;

            chart.ctx.save();
            chart.ctx.textAlign = "center";
            chart.ctx.textBaseline = "middle";

            chart.ctx.fillStyle = (
                colors.strongText
            );

            chart.ctx.font = (
                "900 25px Arial"
            );

            chart.ctx.fillText(
                moneyFormatter.format(total),
                centerX,
                centerY - 8
            );

            chart.ctx.fillStyle = colors.text;
            chart.ctx.font = "700 11px Arial";

            chart.ctx.fillText(
                "إجمالي المواعيد",
                centerX,
                centerY + 18
            );

            chart.ctx.restore();
        }
    };

    function renderAppointmentsChart(
        colors
    ) {
        const canvas = document.getElementById(
            "appointmentsTrendChart"
        );

        if (!canvas) {
            return;
        }

        const chart = new Chart(
            canvas,
            {
                type: "line",

                data: {
                    labels: (
                        chartData.appointments.labels
                    ),

                    datasets: [
                        {
                            label: "إجمالي المواعيد",
                            data: (
                                chartData.appointments.total
                            ),
                            borderColor: colors.blue,
                            backgroundColor: (
                                "rgba(40, 120, 255, 0.13)"
                            ),
                            borderWidth: 2.5,
                            fill: true,
                            tension: 0.35,
                            pointRadius: 0,
                            pointHoverRadius: 5
                        },
                        {
                            label: "مكتملة",
                            data: (
                                chartData.appointments.completed
                            ),
                            borderColor: colors.green,
                            backgroundColor: "transparent",
                            borderWidth: 2,
                            tension: 0.35,
                            pointRadius: 0,
                            pointHoverRadius: 5
                        },
                        {
                            label: "معلقة",
                            data: (
                                chartData.appointments.pending
                            ),
                            borderColor: colors.orange,
                            backgroundColor: "transparent",
                            borderWidth: 1.8,
                            borderDash: [5, 5],
                            tension: 0.35,
                            pointRadius: 0,
                            pointHoverRadius: 5
                        },
                        {
                            label: "ملغاة",
                            data: (
                                chartData.appointments.cancelled
                            ),
                            borderColor: colors.red,
                            backgroundColor: "transparent",
                            borderWidth: 1.8,
                            borderDash: [3, 4],
                            tension: 0.35,
                            pointRadius: 0,
                            pointHoverRadius: 5
                        }
                    ]
                },

                options: {
                    responsive: true,
                    maintainAspectRatio: false,

                    interaction: {
                        mode: "index",
                        intersect: false
                    },

                    plugins: {
                        legend: legendOptions(),

                        tooltip: tooltipOptions(
                            colors
                        )
                    },

                    scales: cartesianScales(
                        colors
                    )
                }
            }
        );

        chartInstances.push(chart);
    }

    function renderStatusChart(colors) {
        const canvas = document.getElementById(
            "statusDistributionChart"
        );

        if (!canvas) {
            return;
        }

        const chart = new Chart(
            canvas,
            {
                type: "doughnut",

                data: {
                    labels: chartData.status.labels,

                    datasets: [
                        {
                            data: (
                                chartData.status.values
                            ),

                            backgroundColor: [
                                colors.green,
                                colors.orange,
                                colors.red
                            ],

                            borderWidth: 0,
                            hoverOffset: 5
                        }
                    ]
                },

                plugins: [
                    centerTextPlugin
                ],

                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: "70%",

                    plugins: {
                        legend: legendOptions(),

                        tooltip: tooltipOptions(
                            colors
                        )
                    }
                }
            }
        );

        chartInstances.push(chart);
    }

    function renderBranchChart(colors) {
        const canvas = document.getElementById(
            "branchComparisonChart"
        );

        if (!canvas) {
            return;
        }

        const chart = new Chart(
            canvas,
            {
                type: "bar",

                data: {
                    labels: (
                        chartData.branches.labels
                    ),

                    datasets: [
                        {
                            label: "مكتملة",
                            data: (
                                chartData.branches.completed
                            ),
                            backgroundColor: colors.green,
                            borderRadius: 5,
                            borderSkipped: false
                        },
                        {
                            label: "معلقة",
                            data: (
                                chartData.branches.pending
                            ),
                            backgroundColor: colors.orange,
                            borderRadius: 5,
                            borderSkipped: false
                        },
                        {
                            label: "ملغاة",
                            data: (
                                chartData.branches.cancelled
                            ),
                            backgroundColor: colors.red,
                            borderRadius: 5,
                            borderSkipped: false
                        }
                    ]
                },

                options: {
                    responsive: true,
                    maintainAspectRatio: false,

                    plugins: {
                        legend: legendOptions(),

                        tooltip: tooltipOptions(
                            colors
                        )
                    },

                    scales: cartesianScales(
                        colors,
                        {
                            stacked: true
                        }
                    )
                }
            }
        );

        chartInstances.push(chart);
    }

    function renderRevenueChart(colors) {
        const canvas = document.getElementById(
            "revenueTrendChart"
        );

        if (!canvas) {
            return;
        }

        const revenueTooltip = (
            tooltipOptions(colors)
        );

        revenueTooltip.callbacks = {
            label: function (context) {
                return (
                    "الإيرادات: " +
                    moneyFormatter.format(
                        context.parsed.y
                    ) +
                    " د.ع"
                );
            }
        };

        const chart = new Chart(
            canvas,
            {
                type: "bar",

                data: {
                    labels: (
                        chartData.revenue.labels
                    ),

                    datasets: [
                        {
                            label: "الإيرادات",
                            data: (
                                chartData.revenue.values
                            ),
                            backgroundColor: (
                                "rgba(118, 88, 232, 0.82)"
                            ),
                            borderColor: colors.violet,
                            borderWidth: 1,
                            borderRadius: 6,
                            borderSkipped: false,
                            maxBarThickness: 25
                        }
                    ]
                },

                options: {
                    responsive: true,
                    maintainAspectRatio: false,

                    interaction: {
                        mode: "index",
                        intersect: false
                    },

                    plugins: {
                        legend: {
                            display: false
                        },

                        tooltip: revenueTooltip
                    },

                    scales: cartesianScales(
                        colors,
                        {
                            money: true
                        }
                    )
                }
            }
        );

        chartInstances.push(chart);
    }

    function renderCharts() {
        destroyCharts();

        const colors = themeColors();

        Chart.defaults.font.family = (
            "Arial, Tahoma, sans-serif"
        );

        Chart.defaults.color = colors.text;

        renderAppointmentsChart(colors);
        renderStatusChart(colors);
        renderBranchChart(colors);
        renderRevenueChart(colors);
    }

    renderCharts();

    const themeObserver = new MutationObserver(
        function (changes) {
            const themeChanged = changes.some(
                function (change) {
                    return (
                        change.attributeName ===
                        "data-theme"
                    );
                }
            );

            if (themeChanged) {
                renderCharts();
            }
        }
    );

    themeObserver.observe(
        document.documentElement,
        {
            attributes: true,
            attributeFilter: [
                "data-theme"
            ]
        }
    );
})();