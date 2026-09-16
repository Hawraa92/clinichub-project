// static/js/medical_archive/edit_archive.js
(function () {
  "use strict";

  class EditArchive {
    constructor() {
      this.form = document.getElementById("editArchiveForm");
      this.saveBtn = document.getElementById("saveBtn");
      this.textarea = document.getElementById("id_notes");
      this.charCounter = document.querySelector('.char-count[data-target="id_notes"]');
      this.isSubmitting = false;
      this.firstError = null;

      this.init();
    }

    init() {
      if (!this.form) return;

      this.setupAutoResize();
      this.setupCharCounter();
      this.setupFormSubmission();
      this.setupToggleAnimation();
      this.setupInputEnhancements();
      this.injectLocalStyles();
    }

    setupAutoResize() {
      if (!this.textarea) return;

      const resize = () => {
        this.textarea.style.height = "auto";
        this.textarea.style.height = this.textarea.scrollHeight + "px";
      };

      resize();
      this.textarea.addEventListener("input", resize);
      window.addEventListener("resize", resize);
    }

    setupCharCounter() {
      if (!this.textarea || !this.charCounter) return;

      const updateCounter = () => {
        const length = this.textarea.value.length;
        this.charCounter.textContent = `${length} character${length !== 1 ? "s" : ""}`;

        if (length > 2000) this.charCounter.style.color = "#ef4444";
        else if (length > 1000) this.charCounter.style.color = "#f59e0b";
        else this.charCounter.style.color = "#64748b";
      };

      updateCounter();
      this.textarea.addEventListener("input", updateCounter);
    }

    setupFormSubmission() {
      if (!this.form || !this.saveBtn) return;

      this.form.addEventListener("submit", (e) => {
        if (this.isSubmitting) {
          e.preventDefault();
          return;
        }

        // only clear client-side errors (do NOT remove Django-rendered .field-error)
        this.clearClientErrors();

        if (!this.validateForm()) {
          e.preventDefault();
          return;
        }

        this.isSubmitting = true;
        this.showLoadingState();
      });
    }

    validateForm() {
      const title = document.getElementById("id_title");
      const patient = document.getElementById("id_patient");
      const doctor = document.getElementById("id_doctor");

      let isValid = true;

      // Title required
      if (title && !String(title.value || "").trim()) {
        this.showClientError(title, "Title is required");
        isValid = false;
      }

      // Patient required only if editable SELECT exists
      if (patient && patient.tagName === "SELECT" && !patient.value) {
        this.showClientError(patient, "Patient selection is required");
        isValid = false;
      }

      // Doctor required only if editable SELECT exists
      if (doctor && doctor.tagName === "SELECT" && !doctor.value) {
        this.showClientError(doctor, "Doctor selection is required");
        isValid = false;
      }

      if (this.firstError) {
        this.firstError.focus();
      }

      return isValid;
    }

    showClientError(element, message) {
      const group = element.closest(".form-group") || element.parentElement;
      if (!group) return;

      const errorEl = document.createElement("div");
      errorEl.className = "field-error";
      errorEl.textContent = message;
      errorEl.dataset.clientError = "1"; // ✅ mark as client-created
      group.appendChild(errorEl);

      element.style.borderColor = "#ef4444";
      element.style.boxShadow = "0 0 0 3px rgba(239, 68, 68, 0.1)";

      if (!this.firstError) this.firstError = element;
    }

    clearClientErrors() {
      document.querySelectorAll('.field-error[data-client-error="1"]').forEach((el) => el.remove());

      // reset only inputs that were styled by us
      const els = this.form.querySelectorAll("input, select, textarea");
      els.forEach((el) => {
        el.style.borderColor = "";
        el.style.boxShadow = "";
      });

      this.firstError = null;
    }

    showLoadingState() {
      if (!this.saveBtn) return;

      this.saveBtn.disabled = true;
      this.saveBtn.innerHTML = `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="animate-spin" aria-hidden="true">
          <circle cx="12" cy="12" r="10" stroke-opacity="0.3"/>
          <path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round"/>
        </svg>
        Saving Changes...
      `;
    }

    setupToggleAnimation() {
      const toggle = document.querySelector(".toggle-switch input");
      if (!toggle) return;

      toggle.addEventListener("change", (e) => {
        const slider = e.target.nextElementSibling;
        if (!slider) return;
        slider.style.transform = "scale(0.96)";
        setTimeout(() => (slider.style.transform = ""), 140);
      });
    }

    setupInputEnhancements() {
      const inputs = this.form.querySelectorAll("input, select, textarea");

      inputs.forEach((el) => {
        // Focus class on wrapper
        el.addEventListener("focus", () => el.closest(".input-wrapper")?.classList.add("focused"));
        el.addEventListener("blur", () => el.closest(".input-wrapper")?.classList.remove("focused"));

        // ✅ Submit on Enter فقط لحقول النص (مو للـ select/checkbox)
        if (el.tagName === "INPUT") {
          const type = (el.getAttribute("type") || "").toLowerCase();
          const allow = ["text", "search", "email", "number", "date", "tel", "url", "password"].includes(type);

          if (allow) {
            el.addEventListener("keydown", (e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                this.form.requestSubmit();
              }
            });
          }
        }
      });
    }

    injectLocalStyles() {
      const style = document.createElement("style");
      style.textContent = `
        @keyframes spin { from {transform: rotate(0deg);} to {transform: rotate(360deg);} }
        .animate-spin { animation: spin 1s linear infinite; }
      `;
      document.head.appendChild(style);
    }
  }

  document.addEventListener("DOMContentLoaded", () => new EditArchive());
})();
