// static/js/appointments/secretary_dashboard.js
document.addEventListener("DOMContentLoaded", () => {
  // ==========================
  // Element References
  // ==========================
  const clockElem       = document.getElementById("digital-clock");
  const dateElem        = document.getElementById("digital-date");
  const chartDataScript = document.getElementById("chart-data");
  const chartCanvas     = document.getElementById("patientsWeekChart");

  const bell            = document.getElementById("notificationBell");
  const dropdown        = document.getElementById("notificationDropdown");
  const list            = document.getElementById("notificationList");
  const countEl         = document.getElementById("notificationCount");

  // Smooth scroll "Call Next" from sidebar
  const navCallNext = document.getElementById("navCallNext");
  navCallNext?.addEventListener("click", (e) => {
    e.preventDefault();
    document.getElementById("queueControlHeading")
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  // ==========================
  // Digital Clock & Date
  // ==========================
  function updateClock() {
    const now = new Date();
    const two = (n) => (n < 10 ? "0" + n : String(n));
    const h = two(now.getHours());
    const m = two(now.getMinutes());
    const s = two(now.getSeconds());
    if (clockElem) clockElem.textContent = `${h}:${m}:${s}`;

    if (dateElem) {
      const opts = { weekday: "long", year: "numeric", month: "long", day: "numeric" };
      dateElem.textContent = now.toLocaleDateString("en-US", opts);
    }
  }
  updateClock();
  setInterval(updateClock, 1000);

  // ==========================
  // Chart.js – Weekly Overview
  // ==========================
  if (chartDataScript && chartCanvas && window.Chart) {
    try {
      const chartData = JSON.parse(chartDataScript.textContent || "{}");
      const ctx = chartCanvas.getContext("2d");

      const pastelColors = ["#FFB4A2","#A2D2FF","#BDE0FE","#FFAFCC","#CDB4DB","#FFC8DD","#B8E0D2"];

      new Chart(ctx, {
        type: "bar",
        data: {
          labels: chartData.labels || [],
          datasets: [{
            label: "Patients",
            data: chartData.data || [],
            backgroundColor: pastelColors,
            borderRadius: 8,
            borderSkipped: false
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: "rgba(255, 255, 255, 0.9)",
              titleColor: "#333",
              bodyColor: "#555",
              borderColor: "#ddd",
              borderWidth: 1,
              padding: 12,
              callbacks: { label: (ctx) => ` ${ctx.parsed.y} patients` }
            }
          },
          scales: {
            x: { grid: { display: false }, ticks: { color: "#666" } },
            y: {
              beginAtZero: true,
              grid: { color: "rgba(0, 0, 0, 0.05)" },
              ticks: { color: "#666", stepSize: 1, precision: 0 }
            }
          },
          animation: { duration: 1200, easing: "easeOutQuart" }
        }
      });
    } catch (err) {
      console.error("Error initializing weekly chart:", err);
    }
  }

  // ==========================
  // Notification System
  // ==========================
  let pollController = null;
  let pollTimer      = null;

  let pollIntervalMs   = 4000;
  const MIN_INTERVAL   = 3000;
  const MAX_INTERVAL   = 20000;
  const BACKOFF_FACTOR = 1.6;

  function toggleDropdown() {
    if (!dropdown || !bell) return;
    const isOpen = dropdown.classList.toggle("open");
    // ✅ extra compatibility (if CSS uses .show)
    dropdown.classList.toggle("show", isOpen);
    bell.setAttribute("aria-expanded", String(isOpen));

    if (isOpen) document.addEventListener("click", closeDropdownIfClickOutside);
    else document.removeEventListener("click", closeDropdownIfClickOutside);
  }

  function closeDropdownIfClickOutside(e) {
    if (!dropdown || !bell) return;
    if (!dropdown.contains(e.target) && !bell.contains(e.target)) {
      dropdown.classList.remove("open");
      dropdown.classList.remove("show");
      bell.setAttribute("aria-expanded", "false");
      document.removeEventListener("click", closeDropdownIfClickOutside);
    }
  }

  function formatLocal(raw) {
    if (!raw) return { date: "", time: "" };

    let d = null;
    if (raw.includes("T")) d = new Date(raw);
    else {
      const [datePart, timePart = "00:00"] = raw.split(" ");
      const [year, month, day] = (datePart || "").split("-").map(Number);
      const [hour, minute] = timePart.split(":").map(Number);
      if (year && month && day) d = new Date(year, month - 1, day, hour || 0, minute || 0, 0);
    }

    if (!d || isNaN(d.getTime())) return { date: raw, time: "" };

    const hours = d.getHours();
    const minutes = d.getMinutes().toString().padStart(2, "0");
    const ampm = hours >= 12 ? "PM" : "AM";
    const hour12 = (hours % 12) || 12;

    const dateOptions = { weekday: "short", day: "2-digit", month: "short", year: "numeric" };
    return { time: `${hour12}:${minutes} ${ampm}`, date: d.toLocaleDateString("en-US", dateOptions) };
  }

  function renderNoNotifications(message) {
    if (!list) return;
    list.innerHTML = `<div class="no-notifications">${message}</div>`;
  }

  function setCount(count) {
    if (!countEl) return;
    const c = Number(count) || 0;
    countEl.textContent = String(c);
    countEl.style.display = c > 0 ? "flex" : "none";
  }

  function safeJsonParse(text) {
    try {
      return text ? JSON.parse(text) : {};
    } catch {
      return {};
    }
  }

  async function fetchNotifications(signal) {
    if (!bell || !list || !countEl) return;

    const apiUrl = bell.dataset.notificationUrl;
    if (!apiUrl) return;

    try {
      // ✅ CRITICAL: include session cookies + accept JSON
      const resp = await fetch(apiUrl, {
        method: "GET",
        signal,
        credentials: "same-origin",
        headers: { "Accept": "application/json" },
        cache: "no-store",
      });

      // Read text first to handle HTML (login redirect) gracefully
      const text = await resp.text();
      const data = safeJsonParse(text);

      if (!resp.ok || (data && data.success === false)) {
        throw new Error(data?.error || `HTTP ${resp.status}`);
      }

      const items = data.notifications || data.booking_requests || [];

      list.innerHTML = "";

      if (!items.length) {
        renderNoNotifications("No new booking requests.");
        setCount(0);
      } else {
        const count = data.count != null ? data.count : items.length;
        setCount(count);

        items.forEach((req) => {
          const container = document.createElement("div");
          container.className = "notification-list-item";

          const rawTime = req.requested_time_iso || req.requested_time_display || req.created_at || "";
          const local = formatLocal(rawTime);

          const title = req.title || "New Booking Request";
          const patientName = req.full_name || req.patient_name || "";
          const doctorName = req.requested_doctor || req.doctor_name || "";

          container.innerHTML = `
            <div class="notification-header">
              <strong>${title}</strong>
              <small>${local.date}${local.time ? " @ " + local.time : ""}</small>
            </div>
            <div class="notification-details">
              ${patientName ? `<span>Patient:</span> ${patientName}<br>` : ""}
              ${doctorName ? `<span>Doctor:</span> Dr. ${doctorName}` : ""}
            </div>
          `;
          list.appendChild(container);
        });
      }

      // success => reduce interval (down to MIN_INTERVAL)
      pollIntervalMs = Math.max(MIN_INTERVAL, Math.floor(pollIntervalMs / BACKOFF_FACTOR));
    } catch (err) {
      console.error("Notification fetch error:", err);
      if (!list.innerHTML.trim()) renderNoNotifications("Error loading notifications.");
      // backoff on failure
      pollIntervalMs = Math.min(MAX_INTERVAL, Math.floor(pollIntervalMs * BACKOFF_FACTOR));
    } finally {
      scheduleNextPoll();
    }
  }

  function scheduleNextPoll() {
    if (document.hidden) return;

    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = setTimeout(() => {
      if (pollController) pollController.abort();
      pollController = new AbortController();
      fetchNotifications(pollController.signal);
    }, pollIntervalMs);
  }

  function startPolling() {
    if (!bell || !list || !countEl) return;
    if (pollController) pollController.abort();
    if (pollTimer) clearTimeout(pollTimer);

    pollIntervalMs = MIN_INTERVAL;
    pollController = new AbortController();
    fetchNotifications(pollController.signal);
  }

  if (bell && dropdown && list && countEl) {
    bell.addEventListener("click", (e) => { e.preventDefault(); toggleDropdown(); });
    bell.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleDropdown(); }
      if (e.key === "Escape") {
        dropdown.classList.remove("open");
        dropdown.classList.remove("show");
        bell.setAttribute("aria-expanded", "false");
      }
    });

    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        if (pollController) pollController.abort();
        if (pollTimer) clearTimeout(pollTimer);
      } else {
        startPolling();
      }
    });

    startPolling();
  }

  // ==========================
  // ✅ Queue Call Logic
  // ==========================
  const qcRoot = document.getElementById("queueControl");
  if (qcRoot) {
    const apiUrl = qcRoot.dataset.queueApiUrl || "";
    const callNextUrl = qcRoot.dataset.callNextUrl || "";
    const csrfToken = qcRoot.dataset.csrfToken || "";

    const elDoctor = document.getElementById("qcDoctorName");
    const elNext   = document.getElementById("qcNextNumber");
    const elWait   = document.getElementById("qcWaiting");
    const elStatus = document.getElementById("qcStatus");
    const btnCall  = document.getElementById("qcCallBtn");
    const btnRef   = document.getElementById("qcRefreshBtn");
    const btnBeep  = document.getElementById("qcBeepBtn");

    let qcTimer = null;
    let currentDoctorName = null;

    function setStatus(msg){ if (elStatus) elStatus.textContent = msg || ""; }

    function toNumberMaybe(v){
      if (typeof v === "number") return v;
      if (typeof v === "string") {
        const n = parseInt(v, 10);
        return Number.isFinite(n) ? n : 0;
      }
      if (v && typeof v === "object") {
        const n = v.waiting ?? v.count ?? v.total ?? 0;
        return toNumberMaybe(n);
      }
      return 0;
    }

    function normalizeNext(v){
      if (v === null || v === undefined) return "—";
      if (typeof v === "string" || typeof v === "number") return String(v);
      if (v && typeof v === "object") return String(v.queue_number ?? v.number ?? v.next ?? "—");
      return "—";
    }

    function beep(){
      try{
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = "sine";
        osc.frequency.value = 880;
        gain.gain.value = 0.08;
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start();
        setTimeout(() => { osc.stop(); ctx.close(); }, 160);
      } catch(e){}
    }

    async function refreshQueue(){
      if (!apiUrl) return;
      setStatus("Updating…");

      try{
        // ✅ include cookies for staff-protected JSON
        const res = await fetch(apiUrl, { cache: "no-store", credentials: "same-origin" });
        const text = await res.text();
        const data = safeJsonParse(text);

        // queue endpoints return {success: true, queues: [...]}
        if (!res.ok || (data && data.success === false)) {
          throw new Error(data?.error || ("HTTP " + res.status));
        }

        const queues = Array.isArray(data.queues) ? data.queues : [];
        const first = queues[0] || null;

        if (!first) {
          currentDoctorName = null;
          if (elDoctor) elDoctor.textContent = "No queue data";
          if (elNext) elNext.textContent = "—";
          if (elWait) elWait.textContent = "0";
          if (btnCall) btnCall.disabled = true;
          setStatus("No appointments found for today.");
          return;
        }

        currentDoctorName = first.doctor_name || null;
        if (elDoctor) elDoctor.textContent = first.doctor_name || "Doctor";
        if (elNext) elNext.textContent = normalizeNext(first.next_queue);
        if (elWait) elWait.textContent = String(toNumberMaybe(first.waiting));

        if (btnCall) btnCall.disabled = !callNextUrl;
        setStatus(callNextUrl ? "Ready." : "Call Next endpoint not configured yet.");
      } catch(err){
        console.error(err);
        setStatus("Failed to load queue data.");
      }
    }

    function startQueuePolling(){
      if (qcTimer) clearInterval(qcTimer);
      refreshQueue();
      qcTimer = setInterval(() => {
        if (!document.hidden) refreshQueue();
      }, 6000);
    }

    btnRef?.addEventListener("click", refreshQueue);
    btnBeep?.addEventListener("click", beep);

    btnCall?.addEventListener("click", async () => {
      if (!callNextUrl) {
        setStatus("Call Next endpoint not configured yet.");
        return;
      }

      btnCall.disabled = true;
      setStatus("Calling next…");

      try{
        const res = await fetch(callNextUrl, {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken
          },
          body: JSON.stringify({ doctor_name: currentDoctorName })
        });

        if (!res.ok) {
          const t = await res.text();
          throw new Error(t || ("HTTP " + res.status));
        }

        beep();
        setStatus("Called. Updating…");
        await refreshQueue();
      } catch(err){
        console.error(err);
        setStatus("Failed to call next. Check backend permissions/endpoint.");
      } finally {
        // Re-enable after attempt
        if (btnCall) btnCall.disabled = !callNextUrl;
      }
    });

    document.addEventListener("visibilitychange", () => {
      if (document.hidden) return;
      refreshQueue();
    });

    startQueuePolling();
  }
});