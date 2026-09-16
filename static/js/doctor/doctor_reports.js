// File: static/js/doctor/doctor_reports.js
(function () {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const state = {
    charts: { status: null, daily: null, monthly: null },
  };

  function safeJsonFromScript(id, fallback) {
    const el = document.getElementById(id);
    if (!el) return fallback;
    try {
      return JSON.parse(el.textContent || "null");
    } catch (e) {
      return fallback;
    }
  }

  function readBoolAttr(el, name) {
    const v = el ? (el.getAttribute(name) || "") : "";
    return v === "1" || v === "true";
  }

  function toNum(x) {
    const n = Number(x);
    return Number.isFinite(n) ? n : 0;
  }

  function isPlainObject(x) {
    return !!x && typeof x === "object" && !Array.isArray(x);
  }

  // ---------------------------------------------------------
  // ✅ NORMALIZERS (support both dict-shape and array-shape)
  // ---------------------------------------------------------
  function normalizeStatus(raw) {
    // Accept:
    // 1) {labels:[...], data:[...]}
    // 2) {completed:1, pending:2, cancelled:0}
    // 3) [{status:'completed', count:..}]
    const defaultLabels = ["Completed", "Pending", "Cancelled"];

    if (!raw) return { labels: defaultLabels, data: [0, 0, 0] };

    if (Array.isArray(raw)) {
      const map = { completed: 0, pending: 0, cancelled: 0 };
      raw.forEach((r) => {
        const k = String(r.status || r.key || "").toLowerCase();
        if (k in map) map[k] = toNum(r.count ?? r.value ?? 0);
      });
      return { labels: defaultLabels, data: [map.completed, map.pending, map.cancelled] };
    }

    if (isPlainObject(raw) && Array.isArray(raw.labels) && Array.isArray(raw.data)) {
      return { labels: raw.labels, data: raw.data.map(toNum) };
    }

    if (isPlainObject(raw)) {
      const completed = toNum(raw.completed ?? raw.Completed ?? 0);
      const pending = toNum(raw.pending ?? raw.Pending ?? 0);
      const cancelled = toNum(raw.cancelled ?? raw.Cancelled ?? 0);
      return { labels: defaultLabels, data: [completed, pending, cancelled] };
    }

    return { labels: defaultLabels, data: [0, 0, 0] };
  }

  function normalizeDaily(raw) {
    // Accept:
    // 1) {labels:[], appointments:[], revenue:[]}
    // 2) [{day, count, revenue}] OR [{date, appointments, revenue}]
    if (!raw) return { labels: [], appointments: [], revenue: [] };

    if (Array.isArray(raw)) {
      const labels = raw.map((r) => r.day || r.date || r.label || "");
      const appointments = raw.map((r) => toNum(r.count ?? r.appointments ?? r.total ?? 0));
      const revenue = raw.map((r) => toNum(r.revenue ?? r.amount ?? r.iqd ?? 0));
      return { labels, appointments, revenue };
    }

    if (isPlainObject(raw)) {
      const labels = raw.labels || raw.days || [];
      const appointments = raw.appointments || raw.counts || raw.data || [];
      const revenue = raw.revenue || raw.revenues || [];
      return {
        labels: Array.isArray(labels) ? labels : [],
        appointments: (Array.isArray(appointments) ? appointments : []).map(toNum),
        revenue: (Array.isArray(revenue) ? revenue : []).map(toNum),
      };
    }

    return { labels: [], appointments: [], revenue: [] };
  }

  function normalizeMonthly(raw) {
    // Accept:
    // 1) {labels:[], revenue:[]}
    // 2) [{month, revenue, expenses, profit}]
    if (!raw) return { labels: [], revenue: [], expenses: [], profit: [] };

    if (Array.isArray(raw)) {
      const labels = raw.map((r) => r.month || r.label || r.m || "");
      const revenue = raw.map((r) => toNum(r.revenue ?? r.amount ?? r.iqd ?? 0));
      const expenses = raw.map((r) => toNum(r.expenses ?? 0));
      const profit = raw.map((r) => toNum(r.profit ?? 0));
      return { labels, revenue, expenses, profit };
    }

    if (isPlainObject(raw)) {
      const labels = raw.labels || [];
      const revenue = raw.revenue || raw.revenues || raw.data || [];
      return {
        labels: Array.isArray(labels) ? labels : [],
        revenue: (Array.isArray(revenue) ? revenue : []).map(toNum),
        expenses: [],
        profit: [],
      };
    }

    return { labels: [], revenue: [], expenses: [], profit: [] };
  }

  // ---------------------------------------------------------
  // UI helpers
  // ---------------------------------------------------------
  function togglePeriodInputs(periodValue) {
    const isCustom = periodValue === "custom";
    const isMonth = periodValue === "month";
    const isYear = periodValue === "year";

    const startInput = document.getElementById("startInput");
    const endInput = document.getElementById("endInput");
    const monthSelect = document.getElementById("monthSelect");
    const yearInput = document.getElementById("yearInput");

    if (startInput) startInput.disabled = !isCustom;
    if (endInput) endInput.disabled = !isCustom;

    if (monthSelect) monthSelect.disabled = !isMonth;
    if (yearInput) yearInput.disabled = !(isMonth || isYear);
  }

  function initPeriodFilters() {
    const periodSelect = document.getElementById("periodSelect");
    if (!periodSelect) return;

    togglePeriodInputs(periodSelect.value || "month");

    periodSelect.addEventListener("change", function () {
      const val = this.value || "month";
      togglePeriodInputs(val);

      if (val !== "custom") {
        const form = document.getElementById("reportsForm");
        if (form) setTimeout(() => form.submit(), 250);
      }
    });
  }

  function buildParamsFromForm(form) {
    const params = new URLSearchParams();
    if (!form) return params;

    const formData = new FormData(form);
    for (const [k, v] of formData.entries()) {
      const val = String(v ?? "").trim();
      if (val) params.set(k, val);
      else params.delete(k);
    }
    return params;
  }

  function initExportButtons() {
    const form = document.getElementById("reportsForm");
    const wrap = $(".export-dropdown");
    if (!form || !wrap) return;

    const exportBase = wrap.getAttribute("data-export-base") || "";
    const pdfBase = wrap.getAttribute("data-pdf-base") || "";

    $$("a[data-export]").forEach((a) => {
      a.addEventListener("click", function (e) {
        e.preventDefault();
        const fmt = this.getAttribute("data-export") || "csv";
        if (!exportBase) return;

        const params = buildParamsFromForm(form);
        params.set("format", fmt);
        window.location.href = `${exportBase}?${params.toString()}`;
      });
    });

    const pdfLink = $('a[data-action="download-pdf"]');
    if (pdfLink && pdfBase) {
      pdfLink.addEventListener("click", function (e) {
        e.preventDefault();
        const params = buildParamsFromForm(form);
        window.location.href = `${pdfBase}?${params.toString()}`;
      });
    }
  }

  function chartDestroy(chartInstance) {
    try {
      if (chartInstance && typeof chartInstance.destroy === "function") chartInstance.destroy();
    } catch (e) {}
  }

  // ---------------------------------------------------------
  // ✅ CHARTS
  // ---------------------------------------------------------
  function renderStatusChart(statusRaw) {
    const canvas = document.getElementById("statusChart");
    if (!canvas || !window.Chart) return;

    chartDestroy(state.charts.status);
    state.charts.status = null;

    const ctx = canvas.getContext("2d");
    const status = normalizeStatus(statusRaw);

    if (!status.labels.length) return;

    const colors = { Completed: "#10b981", Pending: "#f59e0b", Cancelled: "#ef4444" };
    const backgroundColors = status.labels.map((lbl) => colors[lbl] || "#6c757d");

    state.charts.status = new Chart(ctx, {
      type: "doughnut",
      data: {
        labels: status.labels,
        datasets: [{ data: status.data, backgroundColor: backgroundColors, borderWidth: 0, borderRadius: 6, spacing: 2 }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "70%",
        plugins: {
          legend: { position: "bottom", labels: { padding: 16, usePointStyle: true, pointStyle: "circle", font: { size: 12 } } },
          tooltip: { backgroundColor: "#0f172a", padding: 12, cornerRadius: 6 },
        },
      },
    });
  }

  function renderDailyChart(dailyRaw, hasMoney) {
    const canvas = document.getElementById("dailyChart");
    if (!canvas || !window.Chart) return;

    chartDestroy(state.charts.daily);
    state.charts.daily = null;

    const ctx = canvas.getContext("2d");
    const daily = normalizeDaily(dailyRaw);

    if (!daily.labels.length) return;

    const showRevenue = !!(hasMoney && daily.revenue.some((v) => toNum(v) > 0));

    const datasets = [
      {
        label: "Appointments",
        data: daily.appointments,
        backgroundColor: "#4361ee",
        borderRadius: 4,
        borderSkipped: false,
      },
    ];

    if (showRevenue) {
      datasets.push({
        label: "Revenue (IQD)",
        data: daily.revenue,
        type: "line",
        borderColor: "#10b981",
        backgroundColor: "rgba(16, 185, 129, 0.12)",
        borderWidth: 2,
        tension: 0.4,
        fill: true,
        yAxisID: "y1",
      });
    }

    const scales = {
      y: {
        beginAtZero: true,
        grid: { drawBorder: false },
        ticks: { callback: (value) => (Number.isInteger(value) ? value : "") },
      },
    };

    if (showRevenue) {
      scales.y1 = {
        beginAtZero: true,
        position: "right",
        grid: { drawOnChartArea: false },
        ticks: { callback: (value) => Number(value || 0).toLocaleString() + " IQD" },
      };
    }

    state.charts.daily = new Chart(ctx, {
      type: "bar",
      data: { labels: daily.labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales,
        plugins: {
          legend: { position: "top" },
          tooltip: {
            backgroundColor: "#0f172a",
            callbacks: {
              label: (context) => {
                const label = context.dataset.label || "";
                const y = context.parsed.y;
                if (label.includes("Revenue")) return `${label}: ${Number(y || 0).toLocaleString()} IQD`;
                return `${label}: ${y}`;
              },
            },
          },
        },
      },
    });
  }

  function renderMonthlyChart(monthlyRaw, hasMoney, hasExpenses) {
    const canvas = document.getElementById("monthlyChart");
    if (!canvas || !window.Chart) return;

    chartDestroy(state.charts.monthly);
    state.charts.monthly = null;

    const ctx = canvas.getContext("2d");
    const m = normalizeMonthly(monthlyRaw);

    if (!m.labels.length) return;

    const showExpenses = !!(hasMoney && hasExpenses && m.expenses && m.expenses.some((v) => toNum(v) > 0));

    const datasets = [{ label: "Revenue", data: m.revenue, backgroundColor: "#4361ee", borderRadius: 4 }];

    if (showExpenses) {
      datasets.push({ label: "Expenses", data: m.expenses, backgroundColor: "#ef4444", borderRadius: 4 });
      datasets.push({ label: "Profit", data: m.profit, type: "line", borderColor: "#10b981", borderWidth: 3, tension: 0.4, fill: false });
    }

    state.charts.monthly = new Chart(ctx, {
      type: "bar",
      data: { labels: m.labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: {
            beginAtZero: true,
            grid: { drawBorder: false },
            ticks: { callback: (value) => Number(value || 0).toLocaleString() + " IQD" },
          },
        },
        plugins: {
          legend: { position: "top" },
          tooltip: { callbacks: { label: (context) => `${context.dataset.label}: ${Number(context.parsed.y || 0).toLocaleString()} IQD` } },
        },
      },
    });
  }

  function initCharts() {
    const wrap = $(".reports-container");
    const hasMoney = readBoolAttr(wrap, "data-has-money");
    const hasExpenses = readBoolAttr(wrap, "data-has-expenses");

    const statusRaw = safeJsonFromScript("status-breakdown", null);
    const dailyRaw = safeJsonFromScript("daily-data", null);
    const monthlyRaw = safeJsonFromScript("monthly-data", null);

    renderStatusChart(statusRaw);
    renderDailyChart(dailyRaw, hasMoney);

    if (document.getElementById("monthlyChart")) {
      renderMonthlyChart(monthlyRaw, hasMoney, hasExpenses);
    }
  }

  function swapChartsForPrint(makeImages) {
    const canvases = $$("canvas");
    canvases.forEach((cv) => {
      const parent = cv ? cv.parentElement : null;
      if (!cv || !parent) return;

      const existing = parent.querySelector(`img[data-from-canvas="${cv.id}"]`);

      if (makeImages) {
        if (existing) return;
        try {
          const img = document.createElement("img");
          img.setAttribute("data-from-canvas", cv.id);
          img.alt = cv.getAttribute("aria-label") || "Chart";
          img.style.maxWidth = "100%";
          img.style.height = "auto";
          img.src = cv.toDataURL("image/png", 1.0);
          cv.style.display = "none";
          parent.appendChild(img);
        } catch (e) {}
      } else {
        if (existing) existing.remove();
        cv.style.display = "";
      }
    });
  }

  function initPrintFunctionality() {
    const printBtn = $('[data-action="print-pdf"]');
    if (!printBtn) return;

    printBtn.addEventListener("click", function (e) {
      e.preventDefault();
      swapChartsForPrint(true);
      setTimeout(() => window.print(), 60);
    });

    window.addEventListener("beforeprint", () => swapChartsForPrint(true));
    window.addEventListener("afterprint", () => swapChartsForPrint(false));
  }

  // ✅ View Details (Modal)
  function initAppointmentDetails() {
    const modalEl = document.getElementById("appointmentDetailsModal");
    if (!modalEl) return;

    const hasBootstrapModal = !!(window.bootstrap && typeof window.bootstrap.Modal === "function");
    const modalInstance = hasBootstrapModal ? new window.bootstrap.Modal(modalEl) : null;

    const el = {
      id: document.getElementById("mApptId"),
      patient: document.getElementById("mPatient"),
      phone: document.getElementById("mPhone"),
      date: document.getElementById("mDate"),
      time: document.getElementById("mTime"),
      status: document.getElementById("mStatus"),
      amount: document.getElementById("mAmount"),
    };

    function setText(node, value) {
      if (!node) return;
      node.textContent = (value && String(value).trim()) ? value : "—";
    }

    $$('[data-action="view-details"]').forEach((btn) => {
      btn.addEventListener("click", function () {
        const d = this.dataset || {};

        setText(el.id, d.apptId ? `#${d.apptId}` : "—");
        setText(el.patient, d.patient);
        setText(el.phone, d.phone);
        setText(el.date, d.date);
        setText(el.time, d.time);
        setText(el.status, d.status);
        if (el.amount) setText(el.amount, d.amount ? `${d.amount} IQD` : "—");

        if (modalInstance) modalInstance.show();
        else {
          alert(
            `Appointment ${d.apptId}\n` +
            `Patient: ${d.patient || "—"}\n` +
            `Phone: ${d.phone || "—"}\n` +
            `Date: ${d.date || "—"}\n` +
            `Time: ${d.time || "—"}\n` +
            `Status: ${d.status || "—"}\n` +
            (d.amount ? `Amount: ${d.amount} IQD` : "")
          );
        }
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initPeriodFilters();
    initCharts();
    initExportButtons();
    initPrintFunctionality();
    initAppointmentDetails();

    const doctorSelect = document.getElementById("doctorSelect");
    const form = document.getElementById("reportsForm");
    if (doctorSelect && form) {
      doctorSelect.addEventListener("change", () => form.submit());
    }
  });
})();
