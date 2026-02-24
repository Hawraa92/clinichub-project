// static/js/patient/patient_list.js
"use strict";

/**
 * Patient List Search (Server-side)
 * - Submits the search form using GET (?q=...)
 * - Debounced typing
 * - Clear button resets to the list URL
 *
 * Works with:
 * - <form class="search-bar" method="get" action="..." data-list-url="...">
 * - <input id="searchInput" name="q" ...>
 * - <button id="clearSearch" type="button" ...>
 *
 * Notes:
 * - If you also have inline JS in patient_list.html doing the same logic,
 *   REMOVE it to avoid duplicate listeners / double-submit.
 * - Backward compatible with old onkeyup="filterPatients()".
 */

(function () {
  let debounceTimer = null;
  let lastSubmittedValue = null;

  function $(sel, root = document) {
    return root.querySelector(sel);
  }

  function getEls() {
    const form = $("form.search-bar");
    const input = document.getElementById("searchInput");
    const clearBtn = document.getElementById("clearSearch");
    return { form, input, clearBtn };
  }

  function getBaseListUrl(form) {
    // Best: data-list-url (stable even if action changes or has query)
    const dataUrl = form ? (form.getAttribute("data-list-url") || "").trim() : "";
    if (dataUrl) return dataUrl;

    // Next: action attribute (could be absolute or relative)
    const action = form ? (form.getAttribute("action") || "").trim() : "";
    if (action && action !== "#") return action;

    // Fallback: current path without query
    return window.location.pathname;
  }

  function toggleClear(clearBtn, input) {
    if (!clearBtn || !input) return;
    const hasText = !!(input.value && input.value.trim());
    clearBtn.style.display = hasText ? "inline-flex" : "none";
  }

  function hardResetToList(form, input, clearBtn) {
    const url = getBaseListUrl(form);
    // Avoid unnecessary reload loops
    const current = window.location.pathname + window.location.search;
    if (url === current || window.location.search === "") {
      // If already on base, just clear UI
      if (input) input.value = "";
      toggleClear(clearBtn, input);
      if (input) input.focus();
      return;
    }
    window.location.href = url;
  }

  function submitForm(form, qValue) {
    if (!form) return;

    // Prevent rapid duplicate submits with same value
    if (qValue === lastSubmittedValue) return;
    lastSubmittedValue = qValue;

    try {
      form.submit();
    } catch (e) {
      // no-op
    }
  }

  function submitWithDebounce(form, qValue) {
    if (!form) return;

    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => submitForm(form, qValue), 350);
  }

  // ✅ Backward compatibility: old HTML might call filterPatients()
  window.filterPatients = function filterPatients() {
    const { form, input, clearBtn } = getEls();
    if (!input) return;

    toggleClear(clearBtn, input);

    const q = (input.value || "").trim();
    if (!q) {
      hardResetToList(form, input, clearBtn);
      return;
    }

    submitWithDebounce(form, q);
  };

  document.addEventListener("DOMContentLoaded", () => {
    const { form, input, clearBtn } = getEls();
    if (!input) return;

    // Ensure clear button initial state
    toggleClear(clearBtn, input);

    // Typing => debounced submit. If cleared => reset to list.
    input.addEventListener("input", () => {
      toggleClear(clearBtn, input);

      const q = (input.value || "").trim();

      // If cleared, reset to base list (no query)
      if (!q) {
        // also clear "lastSubmittedValue" so next typing submits
        lastSubmittedValue = null;
        hardResetToList(form, input, clearBtn);
        return;
      }

      submitWithDebounce(form, q);
    });

    // Enter => submit immediately (no debounce)
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        const q = (input.value || "").trim();
        if (!q) {
          lastSubmittedValue = null;
          hardResetToList(form, input, clearBtn);
          return;
        }
        // Clear debounce and submit now
        if (debounceTimer) clearTimeout(debounceTimer);
        submitForm(form, q);
      }
    });

    // Clear button => reset list URL
    if (clearBtn) {
      clearBtn.addEventListener("click", () => {
        lastSubmittedValue = null;
        hardResetToList(form, input, clearBtn);
      });
    }
  });
})();
