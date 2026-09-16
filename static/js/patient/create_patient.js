// static/js/patient/create_patient.js
"use strict";

document.addEventListener("DOMContentLoaded", function () {
  const scope = document.querySelector(".ptp");
  const form = document.getElementById("patient-form");
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
  // 1) "Today" button for date_of_birth (supports yyyy-mm-dd)
  // -----------------------------
  const dobField = document.getElementById("id_date_of_birth") || qs('[name="date_of_birth"]', form);
  const todayBtn = qs(".date-today-btn", form);

  if (dobField && todayBtn) {
    todayBtn.addEventListener("click", () => {
      const t = new Date();
      const y = t.getFullYear();
      const m = String(t.getMonth() + 1).padStart(2, "0");
      const d = String(t.getDate()).padStart(2, "0");
      dobField.value = `${y}-${m}-${d}`;
      dispatchInput(dobField);
      dobField.focus?.();
    });
  }

  // -----------------------------
  // 2) Prevent double submit + spinner (button keeps layout stable)
  // -----------------------------
  const submitBtn = document.getElementById("submit-btn") || qs('button[type="submit"]', form);
  let submitted = false;

  form.addEventListener("submit", (e) => {
    if (submitted) {
      e.preventDefault();
      return;
    }

    submitted = true;

    if (submitBtn) {
      // preserve original content if user navigates back (browser cache)
      if (!submitBtn.dataset.originalHtml) {
        submitBtn.dataset.originalHtml = submitBtn.innerHTML;
      }

      submitBtn.disabled = true;
      submitBtn.setAttribute("aria-busy", "true");
      submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> Saving...';
    }
  });

  // If browser restores page from bfcache, re-enable submit button
  window.addEventListener("pageshow", (evt) => {
    if (!evt.persisted) return;
    submitted = false;
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.removeAttribute("aria-busy");
      if (submitBtn.dataset.originalHtml) {
        submitBtn.innerHTML = submitBtn.dataset.originalHtml;
      }
    }
  });

  // -----------------------------
  // 3) Focus effect for fields (adds/removes .focused)
  //    - ignores hidden inputs
  //    - also updates on input/change to keep "filled" highlight
  // -----------------------------
  const controls = qsa("input, select, textarea", form).filter((el) => {
    if (el.type === "hidden") return false;
    if (el.disabled) return false;
    return true;
  });

  const syncGroupFocus = (el) => {
    const group = el.closest(".form-group");
    if (!group) return;

    const isActive = document.activeElement === el;
    const hasValue = (() => {
      if (el.tagName === "SELECT") return !!el.value;
      if (el.type === "checkbox" || el.type === "radio") return el.checked;
      return (el.value || "").trim().length > 0;
    })();

    if (isActive || hasValue) group.classList.add("focused");
    else group.classList.remove("focused");
  };

  controls.forEach((el) => {
    // initial state
    syncGroupFocus(el);

    el.addEventListener("focus", () => syncGroupFocus(el));
    el.addEventListener("blur", () => syncGroupFocus(el));
    el.addEventListener("input", () => syncGroupFocus(el));
    el.addEventListener("change", () => syncGroupFocus(el));
  });

  // If user clicks anywhere, update focus states (useful for select UI changes)
  document.addEventListener("click", () => {
    controls.forEach(syncGroupFocus);
  });

  // -----------------------------
  // 4) Optional: set dir helper (if your base doesn't set it)
  // -----------------------------
  if (scope) {
    // keep as-is if dir already set on html/body
    const rootDir = document.documentElement.getAttribute("dir") || document.body.getAttribute("dir");
    if (rootDir) scope.setAttribute("dir", rootDir);
  }
});
