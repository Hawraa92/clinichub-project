/* File: static/js/doctor/doctor_dashboard.js
   Doctor Dashboard JS (Improved)
   ✅ Digital clock
   ✅ Weekly chart (Chart.js) using CSS vars from .dashboard-container
   ✅ Dark mode-aware chart styling
   ✅ Single tooltip instance (mouse + keyboard)
*/

(() => {
  "use strict";

  document.addEventListener("DOMContentLoaded", () => {
    initDigitalClock();
    initWeeklyChart();
    initTooltips();
  });

  // ==========================
  // Digital Clock
  // ==========================
  function initDigitalClock() {
    const clockElem = document.getElementById("digital-clock");
    const dateElem = document.getElementById("digital-date");

    if (!clockElem && !dateElem) return;

    const updateClock = () => {
      const now = new Date();

      // Time
      const hours = String(now.getHours()).padStart(2, "0");
      const minutes = String(now.getMinutes()).padStart(2, "0");
      const seconds = String(now.getSeconds()).padStart(2, "0");
      if (clockElem) clockElem.textContent = `${hours}:${minutes}:${seconds}`;

      // Date
      if (dateElem) {
        const options = { weekday: "long", year: "numeric", month: "long", day: "numeric" };
        dateElem.textContent = now.toLocaleDateString("en-US", options);
      }
    };

    updateClock();
    setInterval(updateClock, 1000);
  }

  // ==========================
  // Chart.js - Weekly Appointments
  // ==========================
  function initWeeklyChart() {
    const chartDataElement = document.getElementById("chart-data");
    const chartCanvas = document.getElementById("patientsWeekChart");

    if (!chartDataElement || !chartCanvas) return;
    if (typeof Chart === "undefined") {
      console.warn("Chart.js is not loaded.");
      return;
    }

    let parsed;
    try {
      parsed = JSON.parse(chartDataElement.textContent || "{}");
    } catch (err) {
      console.error("Invalid chart JSON:", err);
      return;
    }

    const labels = Array.isArray(parsed.labels) ? parsed.labels : [];
    const data = Array.isArray(parsed.data) ? parsed.data : [];
    if (!labels.length || !data.length) return;

    // IMPORTANT: CSS vars are scoped under .dashboard-container (not :root)
    const scopeEl =
      chartCanvas.closest(".dashboard-container") ||
      document.querySelector(".dashboard-container") ||
      document.documentElement;

    const cssVar = (name, fallback) => {
      const v = getComputedStyle(scopeEl).getPropertyValue(name).trim();
      return v || fallback;
    };

    const paletteBase = [
      cssVar("--secondary", "#FFB4A2"),
      cssVar("--accent", "#A2D2FF"),
      cssVar("--primary-light", "#B8E0F9"),
      "#FFAFCC",
      "#CDB4DB",
      "#FFC8DD",
      "#B8E0D2",
      cssVar("--primary", "#8ECAE6"),
    ];
    const colors = labels.map((_, i) => paletteBase[i % paletteBase.length]);

    const isDark = () =>
      window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches;

    const themeStyles = () => {
      if (isDark()) {
        return {
          tick: "rgba(255,255,255,0.75)",
          gridY: "rgba(255,255,255,0.08)",
          tipBg: "rgba(15, 23, 42, 0.95)",
          tipTitle: "rgba(255,255,255,0.92)",
          tipBody: "rgba(255,255,255,0.80)",
          tipBorder: "rgba(255,255,255,0.10)",
        };
      }
      return {
        tick: "#666",
        gridY: "rgba(0, 0, 0, 0.05)",
        tipBg: "rgba(255, 255, 255, 0.95)",
        tipTitle: "#333",
        tipBody: "#555",
        tipBorder: "#ddd",
      };
    };

    const ctx = chartCanvas.getContext("2d");
    if (!ctx) return;

    // Destroy old chart if any (safety)
    if (chartCanvas._chartInstance) {
      try { chartCanvas._chartInstance.destroy(); } catch (_) {}
      chartCanvas._chartInstance = null;
    }

    const styles = themeStyles();

    const instance = new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: "Appointments",
            data,
            backgroundColor: colors,
            borderRadius: 8,
            borderSkipped: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: styles.tipBg,
            titleColor: styles.tipTitle,
            bodyColor: styles.tipBody,
            borderColor: styles.tipBorder,
            borderWidth: 1,
            padding: 12,
            callbacks: {
              label: (c) => {
                const n = c.parsed.y ?? 0;
                return ` ${n} ${n === 1 ? "appointment" : "appointments"}`;
              },
            },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { color: styles.tick },
          },
          y: {
            beginAtZero: true,
            grid: { color: styles.gridY },
            ticks: { color: styles.tick, stepSize: 1, precision: 0 },
          },
        },
        animation: {
          duration: prefersReducedMotion() ? 0 : 1200,
          easing: "easeOutQuart",
        },
      },
    });

    chartCanvas._chartInstance = instance;

    // Live update on theme change (optional but nice)
    if (window.matchMedia) {
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      const onThemeChange = () => {
        if (!chartCanvas._chartInstance) return;
        const st = themeStyles();

        const opt = chartCanvas._chartInstance.options;
        opt.scales.x.ticks.color = st.tick;
        opt.scales.y.ticks.color = st.tick;
        opt.scales.y.grid.color = st.gridY;

        opt.plugins.tooltip.backgroundColor = st.tipBg;
        opt.plugins.tooltip.titleColor = st.tipTitle;
        opt.plugins.tooltip.bodyColor = st.tipBody;
        opt.plugins.tooltip.borderColor = st.tipBorder;

        chartCanvas._chartInstance.update();
      };

      // addEventListener is modern, fallback to onchange for older
      if (mq.addEventListener) mq.addEventListener("change", onThemeChange);
      else mq.onchange = onThemeChange;
    }
  }

  function prefersReducedMotion() {
    return (
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );
  }

  // ==========================
  // Tooltips (single instance)
  // ==========================
  function initTooltips() {
    const targets = document.querySelectorAll("[data-tooltip]");
    if (!targets.length) return;

    let tooltipEl = null;
    let active = null;
    let raf = null;

    const ensureTooltip = () => {
      if (tooltipEl) return tooltipEl;
      tooltipEl = document.createElement("div");
      tooltipEl.className = "tooltip";
      tooltipEl.setAttribute("role", "tooltip");
      tooltipEl.setAttribute("aria-hidden", "true");
      document.body.appendChild(tooltipEl);
      return tooltipEl;
    };

    const clamp = (v, min, max) => Math.max(min, Math.min(max, v));

    const positionTooltip = (target) => {
      if (!tooltipEl || !target) return;

      const margin = 10;
      const rect = target.getBoundingClientRect();

      // Measure tooltip size
      const tw = tooltipEl.offsetWidth;
      const th = tooltipEl.offsetHeight;

      let top = rect.top - th - margin;
      let left = rect.left + rect.width / 2 - tw / 2;

      // Keep inside viewport
      left = clamp(left, 8, window.innerWidth - tw - 8);

      // If not enough top space, place under element
      if (top < 8) {
        top = rect.bottom + margin;
      }

      tooltipEl.style.top = `${top}px`;
      tooltipEl.style.left = `${left}px`;
    };

    const show = (target) => {
      const text = target.getAttribute("data-tooltip");
      if (!text) return;

      active = target;
      const el = ensureTooltip();
      el.textContent = text;
      el.setAttribute("aria-hidden", "false");
      el.classList.add("show");

      positionTooltip(target);
    };

    const hide = () => {
      if (!tooltipEl) return;
      tooltipEl.classList.remove("show");
      tooltipEl.setAttribute("aria-hidden", "true");
      active = null;
    };

    const schedulePosition = () => {
      if (!active) return;
      if (raf) cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => positionTooltip(active));
    };

    targets.forEach((el) => {
      // Mouse
      el.addEventListener("mouseenter", () => show(el));
      el.addEventListener("mouseleave", hide);
      el.addEventListener("mousemove", schedulePosition);

      // Keyboard accessibility
      el.addEventListener("focusin", () => show(el));
      el.addEventListener("focusout", hide);
    });

    window.addEventListener("scroll", schedulePosition, { passive: true });
    window.addEventListener("resize", schedulePosition);
  }
})();
