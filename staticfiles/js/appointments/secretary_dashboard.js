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

  // Polling control
  let pollController = null;
  let pollIntervalMs = 4000;          // Base interval
  const MIN_INTERVAL = 3000;
  const MAX_INTERVAL = 20000;
  const BACKOFF_FACTOR = 1.6;

  // ==========================
  // Digital Clock & Date
  // ==========================
  function updateClock() {
    const now = new Date();
    const two = n => (n < 10 ? "0" + n : String(n));
    const h = two(now.getHours());
    const m = two(now.getMinutes());
    const s = two(now.getSeconds());
    if (clockElem) clockElem.textContent = `${h}:${m}:${s}`;

    if (dateElem) {
      const opts = {
        weekday: "long",
        year: "numeric",
        month: "long",
        day: "numeric"
      };
      dateElem.textContent = now.toLocaleDateString("en-US", opts);
    }
  }
  updateClock();
  setInterval(updateClock, 1000);

  // ==========================
  // Chart.js – Weekly Overview
  // ==========================
  if (chartDataScript && chartCanvas) {
    try {
      const chartData = JSON.parse(chartDataScript.textContent);
      const ctx = chartCanvas.getContext("2d");
      
      // Pastel color palette for bars
      const pastelColors = [
        '#FFB4A2', '#A2D2FF', '#BDE0FE', '#FFAFCC', 
        '#CDB4DB', '#FFC8DD', '#B8E0D2', '#A2D2FF'
      ];
      
      new Chart(ctx, {
        type: "bar",
        data: {
          labels: chartData.labels,
          datasets: [{
            label: "Patients",
            data: chartData.data,
            backgroundColor: pastelColors,
            borderRadius: 8,
            borderSkipped: false,
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: 'rgba(255, 255, 255, 0.9)',
              titleColor: '#333',
              bodyColor: '#555',
              borderColor: '#ddd',
              borderWidth: 1,
              padding: 12,
              callbacks: {
                label: ctx => ` ${ctx.parsed.y} patients`
              }
            }
          },
          scales: {
            x: { 
              grid: { display: false },
              ticks: { color: '#666' }
            },
            y: {
              beginAtZero: true,
              grid: { color: "rgba(0, 0, 0, 0.05)" },
              ticks: { 
                color: '#666',
                stepSize: 1,
                precision: 0
              }
            }
          },
          animation: {
            duration: 1200,
            easing: "easeOutQuart"
          }
        }
      });
    } catch (err) {
      console.error("Error initializing weekly chart:", err);
    }
  }

  // ==========================
  // Notification System
  // ==========================
  function toggleDropdown() {
    const isOpen = dropdown.classList.toggle("open");
    bell.setAttribute("aria-expanded", String(isOpen));
    
    // Close dropdown when clicking outside
    if (isOpen) {
      document.addEventListener("click", closeDropdownIfClickOutside);
    } else {
      document.removeEventListener("click", closeDropdownIfClickOutside);
    }
  }

  function closeDropdownIfClickOutside(e) {
    if (!dropdown.contains(e.target) && !bell.contains(e.target)) {
      dropdown.classList.remove("open");
      bell.setAttribute("aria-expanded", "false");
      document.removeEventListener("click", closeDropdownIfClickOutside);
    }
  }

  if (bell && dropdown && list && countEl) {
    bell.addEventListener("click", toggleDropdown);
    
    bell.addEventListener("keydown", e => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        toggleDropdown();
      }
      if (e.key === "Escape") {
        dropdown.classList.remove("open");
        bell.setAttribute("aria-expanded", "false");
      }
    });

    function formatLocal(dateIso) {
      const d = new Date(dateIso);
      if (isNaN(d)) return { date: "Invalid date", time: "--:--" };
      const hours = d.getHours();
      const minutes = d.getMinutes().toString().padStart(2, "0");
      const ampm = hours >= 12 ? "PM" : "AM";
      const hour12 = (hours % 12) || 12;
      const dateOptions = { 
        weekday: 'short', 
        day: '2-digit', 
        month: 'short', 
        year: 'numeric' 
      };
      return {
        time: `${hour12}:${minutes} ${ampm}`,
        date: d.toLocaleDateString('en-US', dateOptions)
      };
    }

    async function fetchNotifications(signal) {
      const apiUrl = bell.dataset.notificationUrl;
      const csrfToken = bell.dataset.csrfToken;
      if (!apiUrl || !csrfToken) {
        console.warn("Missing notification API url or CSRF token.");
        return;
      }
      try {
        const resp = await fetch(apiUrl, {
            headers: { "X-CSRFToken": csrfToken },
            signal
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        const requests = data.booking_requests || [];

        list.innerHTML = "";
        if (requests.length === 0) {
          list.innerHTML = '<div class="no-notifications">No new booking requests.</div>';
          countEl.textContent = "0";
        } else {
            countEl.textContent = String(data.count || requests.length);
            requests.forEach(req => {
              const li = document.createElement("div");
              li.className = "notification-list-item";

              const local = formatLocal(req.requested_time_iso || req.requested_time_display);
              li.innerHTML = `
                <div class="notification-header">
                  <strong>New Booking Request</strong>
                  <small>${local.date} @ ${local.time}</small>
                </div>
                <div class="notification-details">
                  <span>Patient:</span> ${req.full_name}<br>
                  <span>Doctor:</span> Dr. ${req.requested_doctor}
                </div>
              `;
              list.appendChild(li);
            });
        }
        // Success: reset interval if backoff had increased
        pollIntervalMs = Math.max(MIN_INTERVAL, Math.floor(pollIntervalMs / BACKOFF_FACTOR));
      } catch (err) {
        console.error("Notification fetch error:", err);
        // On failure show an error message if empty
        if (!list.innerHTML.trim()) {
          list.innerHTML = '<div class="no-notifications">Error loading notifications.</div>';
        }
        // Backoff
        pollIntervalMs = Math.min(MAX_INTERVAL, Math.floor(pollIntervalMs * BACKOFF_FACTOR));
      } finally {
        scheduleNextPoll();
      }
    }

    function scheduleNextPoll() {
      if (document.hidden) return; // Will resume when tab visible
      pollController = new AbortController();
      setTimeout(() => {
        // Avoid scheduling if already aborted due to visibility change.
        if (!pollController.signal.aborted) {
          fetchNotifications(pollController.signal);
        }
      }, pollIntervalMs);
    }

    function startPolling() {
      if (pollController) pollController.abort();
      pollIntervalMs = MIN_INTERVAL;
      fetchNotifications(new AbortController().signal); // immediate
    }

    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        if (pollController) pollController.abort();
      } else {
        startPolling();
      }
    });

    // Initial
    startPolling();
  }
});