document.addEventListener("DOMContentLoaded", () => {
  const sidebar = document.querySelector(".sidebar");
  const backdrop = document.querySelector(".sidebar-backdrop");
  const toggleBtn = document.querySelector(".sidebar-toggle");

  const clockElem = document.getElementById("digital-clock");
  const dateElem = document.getElementById("digital-date");

  const openSidebar = () => {
    if (!sidebar) return;
    sidebar.classList.add("is-open");
    backdrop?.classList.add("is-visible");
    toggleBtn?.setAttribute("aria-expanded", "true");
    document.body.style.overflow = "hidden";
  };

  const closeSidebar = () => {
    if (!sidebar) return;
    sidebar.classList.remove("is-open");
    backdrop?.classList.remove("is-visible");
    toggleBtn?.setAttribute("aria-expanded", "false");
    document.body.style.overflow = "";
  };

  toggleBtn?.addEventListener("click", () => {
    const isOpen = sidebar?.classList.contains("is-open");
    isOpen ? closeSidebar() : openSidebar();
  });

  backdrop?.addEventListener("click", closeSidebar);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeSidebar();
  });

  // Digital Clock & Date
  const two = (n) => (n < 10 ? "0" + n : String(n));

  const updateClock = () => {
    const now = new Date();
    if (clockElem) clockElem.textContent = `${two(now.getHours())}:${two(now.getMinutes())}:${two(now.getSeconds())}`;
    if (dateElem) {
      const opts = { weekday: "long", year: "numeric", month: "long", day: "numeric" };
      dateElem.textContent = now.toLocaleDateString(undefined, opts);
    }
  };

  updateClock();
  setInterval(updateClock, 1000);

  // Appointment select
  const toggleAppointment = (el) => el.classList.toggle("is-active");

  document.querySelectorAll(".appointment-item").forEach((item) => {
    item.addEventListener("click", () => toggleAppointment(item));
    item.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        toggleAppointment(item);
      }
    });
  });
});
