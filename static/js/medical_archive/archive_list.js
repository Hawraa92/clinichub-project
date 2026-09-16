// static/js/medical_archive/archive_list.js
(function () {
  "use strict";

  function isInteractiveTarget(el) {
    if (!el) return false;
    return !!el.closest(
      'a, button, input, select, textarea, label, [role="button"], [role="link"], [data-no-row-nav="1"]'
    );
  }

  function debounce(fn, wait) {
    let t = null;
    return function (...args) {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(this, args), wait);
    };
  }

  function submitWithQuerySync(form) {
    // keeps filters in URL naturally; avoids odd states
    try {
      form.requestSubmit ? form.requestSubmit() : form.submit();
    } catch (_) {
      form.submit();
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    // -----------------------------
    // Clickable rows + keyboard access
    // -----------------------------
    const rows = document.querySelectorAll("tr.archive-row");
    rows.forEach((row) => {
      const href = row.getAttribute("data-href");
      if (!href) return;

      // Make row focusable for keyboard users
      row.setAttribute("tabindex", "0");
      row.setAttribute("role", "link");
      row.setAttribute("aria-label", "Open archive details");

      row.addEventListener("click", (e) => {
        if (isInteractiveTarget(e.target)) return;
        window.location.href = href;
      });

      row.addEventListener("keydown", (e) => {
        // Enter/Space opens the row
        if (e.key === "Enter" || e.key === " ") {
          if (isInteractiveTarget(e.target)) return;
          e.preventDefault();
          window.location.href = href;
        }
      });
    });

    // -----------------------------
    // Auto-submit filters (debounced)
    // -----------------------------
    const form = document.getElementById("archiveFilterForm");
    if (!form) return;

    const autoFields = ["type", "doctor", "start_date", "end_date"];
    const debouncedSubmit = debounce(() => submitWithQuerySync(form), 200);

    autoFields.forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;

      el.addEventListener("change", () => {
        debouncedSubmit();
      });
    });

    // -----------------------------
    // Search field improvements
    // - Escape clears + submits to restore full list
    // - Typing doesn't auto-submit (keeps control in user hand)
    // -----------------------------
    const search = document.getElementById("search");
    if (search) {
      search.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          const hadValue = !!search.value;
          search.value = "";
          search.focus();

          // If it had a value, submit so results reset immediately
          if (hadValue) submitWithQuerySync(form);
        }
      });
    }
  });
})();
