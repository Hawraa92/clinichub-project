// File: appointments/static/js/appointments/create_appointment.js

document.addEventListener("DOMContentLoaded", () => {
  // =========================
  // Flatpickr (Appointment time)
  // =========================
  const dtInputs = document.querySelectorAll(".datetimepicker");
  const fpInstances = [];

  if (dtInputs.length && typeof flatpickr !== "undefined") {
    dtInputs.forEach((input) => {
      const fp = flatpickr(input, {
        enableTime: true,
        allowInput: true,
        time_24hr: false,

        // ✅ يرسل للسيرفر بصيغة ثابتة (Django datetime-local)
        dateFormat: "Y-m-d\\TH:i",

        // ✅ عرض للمستخدم بصيغة واضحة (عراقية)
        altInput: true,
        altFormat: "d/m/Y, h:i K",
        altInputClass: "form-control",

        // ✅ تمنع اختيار أيام قبل اليوم
        minDate: "today",

        // ✅ خليها دقيقة بدقيقة (بدل 15)
        minuteIncrement: 1,

        // ✅ إذا اختار "اليوم" خلي أقل وقت من الآن + دقيقة
        onChange: function (selectedDates) {
          if (!selectedDates || !selectedDates[0]) return;

          const sel = selectedDates[0];
          const now = new Date();

          const sameDay =
            sel.getFullYear() === now.getFullYear() &&
            sel.getMonth() === now.getMonth() &&
            sel.getDate() === now.getDate();

          if (sameDay) {
            const min = new Date(now.getTime() + 60 * 1000); // الآن + دقيقة
            this.set("minTime", `${min.getHours()}:${String(min.getMinutes()).padStart(2, "0")}`);
          } else {
            this.set("minTime", null);
          }
        },
      });

      fpInstances.push({ input, fp });
    });
  }

  // Focus first invalid field (if any)
  const firstInvalid = document.querySelector(".is-invalid");
  if (firstInvalid) firstInvalid.focus();

  // =========================
  // Busy state on submit + force ISO value
  // =========================
  const form = document.getElementById("createApptForm");
  const btn = document.getElementById("submitBtn");

  if (form && btn) {
    form.addEventListener("submit", () => {
      // ✅ تأكيد نهائي: نخلي value هو اللي ينرسل بصيغة ISO
      fpInstances.forEach(({ input, fp }) => {
        const d = fp.selectedDates && fp.selectedDates[0];
        if (d) input.value = fp.formatDate(d, "Y-m-d\\TH:i");
      });

      btn.disabled = true;
      btn.classList.add("is-busy");
      btn.innerHTML =
        '<span class="spinner-border spinner-border-sm me-2"></span>Saving...';
    });
  }

  // =========================
  // Status badge (if exists)
  // =========================
  const statusEl = document.querySelector('[name="status"]');
  const badge = document.getElementById("statusBadge");

  if (statusEl && badge) {
    const refreshBadge = () => {
      const opt = statusEl.options[statusEl.selectedIndex];
      const label = opt ? (opt.text || "").trim() : "";
      badge.textContent = label ? "Default: " + label : "Default: —";
    };
    statusEl.addEventListener("change", refreshBadge);
    refreshBadge();
  }

  // =========================
  // Quick Patient Modal
  // =========================
  const modal = document.getElementById("qp-modal");
  const openBtn = document.querySelector(".qp-open-modal");
  const errorBox = document.getElementById("qp-error");

  function openModal() {
    if (!modal) return;
    modal.setAttribute("aria-hidden", "false");
    modal.setAttribute("aria-modal", "true");
    modal.style.display = "block";
    document.body.classList.add("qp-modal-open");
  }

  function closeModal() {
    if (!modal) return;
    modal.setAttribute("aria-hidden", "true");
    modal.setAttribute("aria-modal", "false");
    modal.style.display = "none";
    document.body.classList.remove("qp-modal-open");
    if (errorBox) {
      errorBox.style.display = "none";
      errorBox.textContent = "";
    }
  }

  if (openBtn) openBtn.addEventListener("click", openModal);

  if (modal) {
    modal.addEventListener("click", (e) => {
      if (e.target && e.target.matches("[data-close]")) closeModal();
    });
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModal();
  });

  // Create patient via fetch
  const saveBtn = document.getElementById("qp-save-btn");
  const qpForm = document.getElementById("quickPatientForm");

  function getCSRFToken() {
    const el = (qpForm || document).querySelector('input[name="csrfmiddlewaretoken"]');
    return el ? el.value : "";
  }

  async function submitQuickPatient() {
    if (!qpForm || !saveBtn) return;

    const url = qpForm.getAttribute("data-url");
    if (!url) return;

    saveBtn.disabled = true;
    saveBtn.innerHTML =
      '<span class="spinner-border spinner-border-sm me-2"></span>Saving...';

    try {
      const formData = new FormData(qpForm);
      const res = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "X-CSRFToken": getCSRFToken(),
          "X-Requested-With": "XMLHttpRequest",
        },
        body: formData,
      });

      let data = {};
      try {
        data = await res.json();
      } catch (_) {
        data = {};
      }

      if (!res.ok || !data.success) {
        throw new Error(data.error || "Failed to create patient.");
      }

      const select = document.querySelector('[name="patient"]');
      if (select) {
        const label = data.full_name || "Patient #" + data.id;
        const opt = new Option(label, data.id, true, true);
        select.add(opt);
        select.value = String(data.id);
      }

      closeModal();
    } catch (err) {
      if (errorBox) {
        errorBox.textContent = (err && err.message) || "Error creating patient.";
        errorBox.style.display = "block";
      }
    } finally {
      saveBtn.disabled = false;
      saveBtn.innerHTML = '<i class="bi bi-save me-1"></i>Save Patient';
    }
  }

  if (saveBtn) saveBtn.addEventListener("click", submitQuickPatient);
});
