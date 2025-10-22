document.addEventListener("DOMContentLoaded", () => {
  // Elements
  const sidebar = document.querySelector(".sidebar");
  const backdrop = document.querySelector(".sidebar-backdrop");
  const toggleBtn = document.querySelector(".sidebar-toggle");
  const clockElem = document.getElementById("digital-clock");
  const dateElem = document.getElementById("digital-date");

  // ==============================
  // Sidebar (mobile) — accessible
  // ==============================
  const openSidebar = () => {
    if (!sidebar) return;
    sidebar.classList.add("is-open");
    if (backdrop) backdrop.classList.add("is-visible");
    if (toggleBtn) toggleBtn.setAttribute("aria-expanded", "true");
    document.body.style.overflow = "hidden";
  };
  const closeSidebar = () => {
    if (!sidebar) return;
    sidebar.classList.remove("is-open");
    if (backdrop) backdrop.classList.remove("is-visible");
    if (toggleBtn) toggleBtn.setAttribute("aria-expanded", "false");
    document.body.style.overflow = "";
  };
  if (toggleBtn) toggleBtn.addEventListener("click", () => {
    const isOpen = sidebar?.classList.contains("is-open");
    isOpen ? closeSidebar() : openSidebar();
  });
  if (backdrop) backdrop.addEventListener("click", closeSidebar);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSidebar(); });

  // Smooth scroll for in-page links (e.g., My Appointments)
  document.querySelectorAll('a[href^="#"]').forEach(a => {
    a.addEventListener("click", (e) => {
      const target = document.querySelector(a.getAttribute("href"));
      if (target) {
        e.preventDefault();
        target.scrollIntoView({ behavior: "smooth", block: "start" });
        closeSidebar();
      }
    });
  });

  // ==============================
  // Digital Clock & Date
  // ==============================
  const updateClock = () => {
    const now = new Date();
    const two = (n) => (n < 10 ? "0" + n : String(n));
    if (clockElem) clockElem.textContent = `${two(now.getHours())}:${two(now.getMinutes())}`;
    if (dateElem) {
      const opts = { weekday: "long", year: "numeric", month: "long", day: "numeric" };
      dateElem.textContent = now.toLocaleDateString(undefined, opts);
    }
  };
  updateClock();
  // Align updates to the next minute boundary
  setTimeout(() => {
    updateClock();
    setInterval(updateClock, 60 * 1000);
  }, (60 - new Date().getSeconds()) * 1000);

  // ==============================
  // Card micro-interactions
  // ==============================
  document.querySelectorAll(".card").forEach(card => {
    card.addEventListener("mouseenter", () => { card.style.transform = "translateY(-2px)"; });
    card.addEventListener("mouseleave", () => { card.style.transform = "translateY(0)"; });
  });

  // Health Metric hover
  document.querySelectorAll(".metric-item").forEach(item => {
    item.addEventListener("mouseenter", () => { item.style.transform = "translateY(-2px)"; });
    item.addEventListener("mouseleave", () => { item.style.transform = "translateY(0)"; });
  });

  // Appointment click (placeholder)
  document.querySelectorAll(".appointment-item").forEach(item => {
    item.addEventListener("click", () => { item.classList.toggle("active"); });
  });
});
