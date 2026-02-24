// static/js/patient/edit_patient.js
"use strict";

document.addEventListener("DOMContentLoaded", function () {
  const form = document.getElementById("edit-patient-form");
  if (!form) return;

  // -----------------------------
  // Helpers
  // -----------------------------
  const qs = (sel, root = document) => root.querySelector(sel);
  const qsa = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const dispatchInput = (el) => {
    if (!el) return;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  };

  // -----------------------------
  // 1) "Today" button for date_of_birth (yyyy-mm-dd)
  // -----------------------------
  const dob = document.getElementById("id_date_of_birth") || qs('[name="date_of_birth"]', form);
  const todayBtn = qs(".date-today-btn", form);

  if (dob && todayBtn) {
    todayBtn.addEventListener("click", function () {
      const t = new Date();
      const y = t.getFullYear();
      const m = String(t.getMonth() + 1).padStart(2, "0");
      const d = String(t.getDate()).padStart(2, "0");
      dob.value = `${y}-${m}-${d}`;
      dispatchInput(dob);
      dob.focus?.();
    });
  }

  // -----------------------------
  // 2) Prevent double submit + spinner
  // -----------------------------
  const saveBtn = document.getElementById("btn-save") || qs('button[type="submit"]', form);
  let submitted = false;

  form.addEventListener("submit", function (e) {
    if (submitted) {
      e.preventDefault();
      return;
    }
    submitted = true;

    if (saveBtn) {
      if (!saveBtn.dataset.originalHtml) {
        saveBtn.dataset.originalHtml = saveBtn.innerHTML;
      }
      saveBtn.disabled = true;
      saveBtn.setAttribute("aria-busy", "true");
      saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> Saving...';
    }
  });

  // Restore state if page comes from bfcache (Back/Forward cache)
  window.addEventListener("pageshow", function (evt) {
    if (!evt.persisted) return;
    submitted = false;
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.removeAttribute("aria-busy");
      if (saveBtn.dataset.originalHtml) {
        saveBtn.innerHTML = saveBtn.dataset.originalHtml;
      }
    }
  });

  // -----------------------------
  // 3) Focus UX (adds/removes .focused on .form-group)
  // -----------------------------
  const controls = qsa("input, select, textarea", form).filter((el) => {
    if (el.type === "hidden") return false;
    if (el.disabled) return false;
    return true;
  });

  const sync = (el) => {
    const group = el.closest(".form-group");
    if (!group) return;

    const active = document.activeElement === el;
    const hasValue =
      el.tagName === "SELECT"
        ? !!el.value
        : el.type === "checkbox" || el.type === "radio"
          ? el.checked
          : ((el.value || "").trim().length > 0);

    if (active || hasValue) group.classList.add("focused");
    else group.classList.remove("focused");
  };

  controls.forEach((el) => {
    sync(el);
    el.addEventListener("focus", () => sync(el));
    el.addEventListener("blur", () => sync(el));
    el.addEventListener("input", () => sync(el));
    el.addEventListener("change", () => sync(el));
  });

  document.addEventListener("click", () => controls.forEach(sync));
});
