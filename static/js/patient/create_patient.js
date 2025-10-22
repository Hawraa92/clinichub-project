// static/js/patient/create_patient.js
"use strict";

document.addEventListener("DOMContentLoaded", function () {
  const form = document.getElementById("patient-form");
  if (!form) return;

  // "Today" button for date_of_birth
  const dobField = document.getElementById("id_date_of_birth");
  const todayBtn = document.querySelector(".date-today-btn");
  if (dobField && todayBtn) {
    todayBtn.addEventListener("click", () => {
      const t = new Date();
      const y = t.getFullYear();
      const m = String(t.getMonth() + 1).padStart(2, "0");
      const d = String(t.getDate()).padStart(2, "0");
      dobField.value = `${y}-${m}-${d}`;
    });
  }

  // Prevent double submit, add spinner
  const submitBtn = document.getElementById("submit-btn");
  let submitted = false;
  form.addEventListener("submit", (e) => {
    if (submitted) {
      e.preventDefault();
      return;
    }
    submitted = true;
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';
    }
  });

  // Focus effect for fields (advanced, for UX polish)
  const inputs = form.querySelectorAll("input, select, textarea");
  inputs.forEach((input) => {
    const group = input.closest(".form-group");
    if (!group) return;
    const setFocusClass = () => {
      if (document.activeElement === input || input.value) {
        group.classList.add("focused");
      } else {
        group.classList.remove("focused");
      }
    };
    input.addEventListener("focus", setFocusClass);
    input.addEventListener("blur", setFocusClass);
    setFocusClass();
  });
});
