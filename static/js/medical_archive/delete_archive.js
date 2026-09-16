// File: static/js/medical_archive/delete_archive.js
(() => {
  "use strict";

  class DeleteArchiveHandler {
    constructor() {
      this.form = document.getElementById("deleteForm");
      this.deleteBtn = document.getElementById("deleteBtn");
      this.btnText = document.querySelector("#deleteBtn .btn-text");
      this.btnLoader = document.querySelector("#deleteBtn .btn-loader");
      this.confirmCheckbox = document.getElementById("confirmCheckbox");

      this.isSubmitting = false;

      this.init();
    }

    init() {
      if (!this.form || !this.deleteBtn) return;

      this.bindConfirmCheckbox();
      this.bindSubmit();
      this.bindKeyboardShortcuts();
      this.restoreStateOnPageShow();
    }

    bindConfirmCheckbox() {
      // Default: disabled until user confirms
      const sync = () => {
        const ok = !!(this.confirmCheckbox && this.confirmCheckbox.checked);
        this.deleteBtn.disabled = !ok || this.isSubmitting;
      };

      if (this.confirmCheckbox) {
        this.confirmCheckbox.addEventListener("change", sync);
      }

      sync();
    }

    bindSubmit() {
      this.form.addEventListener("submit", (e) => {
        // Prevent double submit
        if (this.isSubmitting) {
          e.preventDefault();
          return;
        }

        // Require checkbox
        if (this.confirmCheckbox && !this.confirmCheckbox.checked) {
          e.preventDefault();
          this.confirmCheckbox.focus();
          return;
        }

        this.isSubmitting = true;
        this.showLoading();
      });
    }

    bindKeyboardShortcuts() {
      document.addEventListener("keydown", (e) => {
        // ESC => back to previous page
        if (e.key === "Escape") {
          e.preventDefault();
          window.history.back();
        }

        // Ctrl/Cmd + Enter => submit (if confirmed)
        if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
          e.preventDefault();
          if (this.confirmCheckbox && !this.confirmCheckbox.checked) {
            this.confirmCheckbox.focus();
            return;
          }
          this.form.requestSubmit();
        }
      });
    }

    restoreStateOnPageShow() {
      // If user navigates back to this page, ensure button state is correct
      window.addEventListener("pageshow", () => {
        this.isSubmitting = false;
        this.hideLoading();
        this.bindConfirmCheckbox();
      });
    }

    showLoading() {
      this.deleteBtn.disabled = true;
      this.form.setAttribute("aria-busy", "true");

      if (this.btnText) this.btnText.classList.add("hidden");
      if (this.btnLoader) this.btnLoader.classList.remove("hidden");

      this.deleteBtn.setAttribute("aria-label", "Moving archive to trash, please wait...");
    }

    hideLoading() {
      this.form.removeAttribute("aria-busy");

      if (this.btnText) this.btnText.classList.remove("hidden");
      if (this.btnLoader) this.btnLoader.classList.add("hidden");

      this.deleteBtn.setAttribute("aria-label", "Move archive to trash");
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    new DeleteArchiveHandler();
  });
})();
