/* static/js/doctor/doctor_visit.js
   ✅ Tooltips (accessible: hover + focus) — auto-disables if CSS tooltips are active
   ✅ AI Assist via AJAX (POST JSON) using form[data-ai-url]
   ✅ CSRF safely (cookie OR hidden input fallback)
   ✅ Prevents full submit on AI button when endpoint exists
   ✅ Clears stale AI output when relevant inputs change (and aborts in-flight request)
   ✅ Renders multiple AI items from API: {items: [...]}
   ✅ Guards against race conditions / stale responses
   ✅ Timeout + abort on navigation
*/

(() => {
  "use strict";

  // Global request state (guard against race conditions)
  let aiAbortController = null;
  let currentReqId = 0;
  let statusHideTimer = null;

  document.addEventListener("DOMContentLoaded", () => {
    initTooltips();          // optional (auto-detects CSS tooltips)
    initAiAssist();
    initAutoClearOnInput();
    initAbortOnUnload();
  });

  // ------------------------------------------------------------
  // Tooltips (custom) — skip if CSS ::after tooltips are active
  // ------------------------------------------------------------
  function initTooltips() {
    const targets = document.querySelectorAll("[data-tooltip]");
    if (!targets.length) return;

    // If CSS tooltips exist ([data-tooltip]::after { content: attr(data-tooltip) }),
    // don't duplicate with JS tooltip.
    const first = targets[0];
    try {
      const after = window.getComputedStyle(first, "::after");
      const c = String(after && after.content ? after.content : "").trim();
      if (c && c !== "none" && c !== "normal" && c !== '""') return;
    } catch (_) {}

    let tip = null;
    const TIP_ID = "ch-tooltip";

    const ensure = () => {
      if (tip) return tip;
      tip = document.createElement("div");
      tip.id = TIP_ID;
      tip.className = "ch-tooltip";
      tip.setAttribute("role", "tooltip");
      tip.style.cssText = `
        position: fixed;
        background: rgba(0,0,0,0.85);
        color: #fff;
        padding: 6px 10px;
        border-radius: 10px;
        font-size: 12px;
        z-index: 9999;
        pointer-events: none;
        opacity: 0;
        transform: translateY(-4px);
        transition: opacity .12s ease, transform .12s ease;
        max-width: 320px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      `;
      document.body.appendChild(tip);
      return tip;
    };

    const position = (el) => {
      if (!tip) return;
      const rect = el.getBoundingClientRect();
      const margin = 10;

      const tw = tip.offsetWidth;
      const th = tip.offsetHeight;

      let top = rect.top - th - margin;
      let left = rect.left + rect.width / 2 - tw / 2;

      left = Math.max(8, Math.min(window.innerWidth - tw - 8, left));
      if (top < 8) top = rect.bottom + margin;

      tip.style.top = `${top}px`;
      tip.style.left = `${left}px`;
    };

    const show = (el) => {
      const text = (el.getAttribute("data-tooltip") || "").trim();
      if (!text) return;
      const t = ensure();
      t.textContent = text;

      // accessibility
      el.setAttribute("aria-describedby", TIP_ID);

      t.style.opacity = "1";
      t.style.transform = "translateY(0)";
      position(el);
    };

    const hide = () => {
      if (!tip) return;
      tip.style.opacity = "0";
      tip.style.transform = "translateY(-4px)";
      // remove aria-describedby from any element that had it
      document.querySelectorAll(`[aria-describedby="${TIP_ID}"]`).forEach((el) => {
        el.removeAttribute("aria-describedby");
      });
    };

    targets.forEach((el) => {
      el.addEventListener("mouseenter", () => show(el));
      el.addEventListener("mouseleave", hide);
      el.addEventListener("mousemove", () => position(el));
      el.addEventListener("focusin", () => show(el));
      el.addEventListener("focusout", hide);
    });

    window.addEventListener("scroll", hide, { passive: true });
    window.addEventListener("resize", hide);
  }

  // ------------------------------------------------------------
  // CSRF helpers
  // ------------------------------------------------------------
  function getCookie(name) {
    const m = document.cookie.match(new RegExp(`(^|;\\s*)${name}=([^;]*)`));
    return m ? decodeURIComponent(m[2]) : "";
  }

  function getCsrfToken(form) {
    const cookie = getCookie("csrftoken");
    if (cookie) return cookie;

    const input = form ? form.querySelector('input[name="csrfmiddlewaretoken"]') : null;
    return input ? String(input.value || "") : "";
  }

  // ------------------------------------------------------------
  // DOM helpers
  // ------------------------------------------------------------
  function getFieldEl(form, fieldName) {
    if (!form) return null;
    try {
      return form.querySelector(`[name="${CSS.escape(fieldName)}"]`);
    } catch (_) {
      return form.querySelector(`[name="${fieldName}"]`);
    }
  }

  function getFieldValue(form, fieldName) {
    const el = getFieldEl(form, fieldName);
    return el ? String(el.value || "").trim() : "";
  }

  function escapeHtml(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function escapeHtmlWithBreaks(str) {
    // Safe: first escape, then convert \n to <br>
    return escapeHtml(str).replace(/\n/g, "<br>");
  }

  function normalizeSeverity(sev) {
    const s = String(sev || "info").toLowerCase();
    if (s === "urgent") return "danger";
    if (s === "danger" || s === "warning" || s === "info") return s;
    return "info";
  }

  function severityLabel(sev) {
    const s = normalizeSeverity(sev);
    if (s === "danger") return "Danger";
    if (s === "warning") return "Warning";
    return "Info";
  }

  function clearStatusTimer() {
    if (statusHideTimer) {
      try { clearTimeout(statusHideTimer); } catch (_) {}
      statusHideTimer = null;
    }
  }

  // ------------------------------------------------------------
  // AI UI helpers
  // ------------------------------------------------------------
  function setAiLoading(isLoading, reqId) {
    // Guard: only affect UI for the latest request
    if (typeof reqId === "number" && reqId !== currentReqId) return;

    const btn = document.getElementById("aiAssistBtn");
    if (!btn) return;

    const loading = !!isLoading;
    btn.disabled = loading;

    btn.classList.toggle("loading", loading);
    btn.classList.toggle("is-loading", loading);

    if (loading) {
      if (!btn.dataset.originalHtml) btn.dataset.originalHtml = btn.innerHTML;
      btn.innerHTML = `<i class="bi bi-hourglass-split"></i> Loading...`;
    } else {
      if (btn.dataset.originalHtml) {
        btn.innerHTML = btn.dataset.originalHtml;
        delete btn.dataset.originalHtml;
      }
    }
  }

  function showAiStatus(text, opts = {}, reqId) {
    if (typeof reqId === "number" && reqId !== currentReqId) return;

    const el = document.getElementById("aiStatus");
    if (!el) return;

    const msg = String(text || "").trim();
    if (!msg) {
      el.style.display = "none";
      el.textContent = "";
      el.classList.remove("is-danger", "is-warning", "is-info", "is-ok");
      return;
    }

    const isError = !!opts.isError;
    const sev = normalizeSeverity(opts.severity || (isError ? "danger" : "info"));

    el.style.display = "block";
    el.textContent = msg;

    el.classList.remove("is-danger", "is-warning", "is-info", "is-ok");
    if (sev === "danger") el.classList.add("is-danger");
    else if (sev === "warning") el.classList.add("is-warning");
    else el.classList.add("is-info");
  }

  function setSuggested(text, reqId) {
    if (typeof reqId === "number" && reqId !== currentReqId) return;

    const box = document.getElementById("aiSuggestedBox");
    const span = document.getElementById("aiSuggestedText");
    if (!box || !span) return;

    const msg = String(text || "").trim();
    if (!msg) {
      box.style.display = "none";
      span.textContent = "";
      return;
    }

    span.textContent = msg;
    box.style.display = "block";
  }

  function clearAiOutputs(reqId) {
    if (typeof reqId === "number" && reqId !== currentReqId) return;

    setSuggested("", reqId);
    showAiStatus("", {}, reqId);

    const itemsBox = document.getElementById("aiItemsBox");
    const itemsList = document.getElementById("aiItemsList");
    const itemsCount = document.getElementById("aiItemsCount");
    const disclaimerLine = document.getElementById("aiDisclaimerLine");

    if (itemsList) itemsList.innerHTML = "";
    if (itemsCount) itemsCount.textContent = "";
    if (disclaimerLine) disclaimerLine.textContent = "";
    if (itemsBox) itemsBox.style.display = "none";
  }

  function renderAiItems(items, disclaimer, reqId) {
    if (typeof reqId === "number" && reqId !== currentReqId) return;

    const itemsBox = document.getElementById("aiItemsBox");
    const itemsList = document.getElementById("aiItemsList");
    const itemsCount = document.getElementById("aiItemsCount");
    const disclaimerLine = document.getElementById("aiDisclaimerLine");

    if (!itemsBox || !itemsList || !itemsCount || !disclaimerLine) return;

    const safeItems = Array.isArray(items) ? items : [];
    itemsList.innerHTML = "";

    if (!safeItems.length) {
      itemsBox.style.display = "none";
      itemsCount.textContent = "";
      disclaimerLine.textContent = "";
      return;
    }

    itemsBox.style.display = "block";
    itemsCount.textContent = `(${safeItems.length})`;
    disclaimerLine.textContent = String(disclaimer || "").trim();

    const form = document.getElementById("consultationForm");
    const prelimEl = form ? getFieldEl(form, "preliminary_diagnosis") : null;

    safeItems.forEach((it) => {
      const msg = (it && it.message) ? String(it.message) : "";
      const sev = normalizeSeverity(it && it.severity);
      const src = (it && it.source) ? String(it.source) : "none";
      const redFlag = !!(it && it.red_flag);

      const li = document.createElement("li");
      li.className = `ai-item ai-${sev}`;

      li.innerHTML = `
        <div class="ai-item-left">
          <span class="ai-pill ai-pill-${sev}">${escapeHtml(severityLabel(sev))}</span>
          ${redFlag ? `<span class="ai-pill ai-pill-danger">Red flag</span>` : ``}
        </div>
        <div class="ai-item-body">
          <div class="ai-item-msg" dir="auto">${escapeHtmlWithBreaks(msg)}</div>
          <div class="ai-item-src muted-mini">Source: ${escapeHtml(src)}</div>
        </div>
        <div class="ai-item-right">
          <button type="button" class="ai-use-btn">Use</button>
        </div>
      `;

      const applyToPrelim = () => {
        if (!prelimEl) return;
        prelimEl.value = msg;
        prelimEl.dataset.aiFilled = "1";
        prelimEl.focus();
      };

      const useBtn = li.querySelector(".ai-use-btn");
      if (useBtn) {
        useBtn.addEventListener("click", (e) => {
          e.preventDefault();
          e.stopPropagation();
          applyToPrelim();
        });
      }

      li.addEventListener("click", applyToPrelim);
      itemsList.appendChild(li);
    });
  }

  // ------------------------------------------------------------
  // AI Assist (AJAX)
  // ------------------------------------------------------------
  function initAiAssist() {
    const form = document.getElementById("consultationForm");
    const btn = document.getElementById("aiAssistBtn");
    if (!form || !btn) return;

    const endpoint = String(form.dataset.aiUrl || "").trim();

    if (!endpoint) {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        showAiStatus("AI endpoint is not configured (missing data-ai-url).", { isError: true }, currentReqId);
      });
      return;
    }

    // Intercept submit only for the AI action
    form.addEventListener("submit", (e) => {
      const submitter = e.submitter || document.activeElement;
      const isSuggest =
        submitter &&
        submitter.getAttribute &&
        submitter.getAttribute("name") === "action" &&
        submitter.getAttribute("value") === "suggest";

      if (!isSuggest) return;

      e.preventDefault();
      runAi(endpoint, form);
    });

    // Click support
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      runAi(endpoint, form);
    });

    // If doctor types manually, mark as not AI-filled
    const prelimEl = getFieldEl(form, "preliminary_diagnosis");
    if (prelimEl) {
      prelimEl.addEventListener("input", () => {
        prelimEl.dataset.aiFilled = "0";
      });
    }
  }

  async function runAi(endpoint, form) {
    // Network quick check
    if (typeof navigator !== "undefined" && navigator.onLine === false) {
      showAiStatus("No internet connection. Please check your network and try again.", { isError: true }, currentReqId);
      return;
    }

    const chief = getFieldValue(form, "chief_complaint");
    const symptoms = getFieldValue(form, "symptoms");
    const history = getFieldValue(form, "history");
    const examination = getFieldValue(form, "examination");

    if (!chief || !symptoms) {
      showAiStatus("Please enter Chief Complaint and Symptoms before using AI Assist.", {
        isError: true,
        severity: "warning",
      }, currentReqId);
      return;
    }

    // New request id
    currentReqId += 1;
    const reqId = currentReqId;

    // Cancel previous request if any
    try {
      if (aiAbortController) aiAbortController.abort();
    } catch (_) {}

    const controller = new AbortController();
    aiAbortController = controller;

    clearStatusTimer();
    setAiLoading(true, reqId);
    setSuggested("", reqId);
    showAiStatus("Analyzing…", { severity: "info" }, reqId);

    // Timeout safety (e.g. 20s)
    const timeoutMs = 20000;
    const timeoutHandle = setTimeout(() => {
      try { controller.abort(); } catch (_) {}
    }, timeoutMs);

    try {
      const csrf = getCsrfToken(form);
      const payload = { chief_complaint: chief, symptoms, history, examination };

      const res = await fetch(endpoint, {
        method: "POST",
        credentials: "same-origin",
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
          ...(csrf ? { "X-CSRFToken": csrf } : {}),
          "X-Requested-With": "XMLHttpRequest",
          "Accept": "application/json",
        },
        body: JSON.stringify(payload),
      });

      // If a newer request started, ignore this response
      if (reqId !== currentReqId) return;

      const ct = String(res.headers.get("content-type") || "").toLowerCase();
      const isJson = ct.includes("application/json");

      let data = null;

      if (isJson) {
        try { data = await res.json(); } catch (_) { data = null; }
      } else {
        // Non-JSON pages (CSRF/403, debug html, etc)
        const _txt = await res.text().catch(() => "");
        if (!res.ok) {
          if (res.status === 403) {
            throw new Error("CSRF verification failed (403). Please refresh the page and try again.");
          }
          throw new Error(`Server returned non-JSON error (${res.status}).`);
        }
      }

      if (!res.ok) {
        const msg = (data && data.error) ? data.error : `AI request failed (${res.status})`;
        if (res.status === 403) {
          throw new Error("CSRF verification failed (403). Please refresh the page and try again.");
        }
        throw new Error(msg);
      }

      if (!data || data.ok === false) {
        const msg = (data && data.error) ? data.error : "AI returned an invalid response.";
        throw new Error(msg);
      }

      const suggested = String(data.suggested || "").trim();
      const preliminary = String(data.preliminary || "").trim();
      const severity = normalizeSeverity(data.severity || "info");
      const disclaimer = String(data.disclaimer || data.ai_note || "").trim();

      setSuggested(suggested || "No suggestion returned.", reqId);

      const rawItems = Array.isArray(data.items) ? data.items : [];
      const items = rawItems.length ? rawItems : [{
        message: suggested || preliminary || "General assessment needed",
        severity: severity,
        source: String(data.source || "none"),
        red_flag: false
      }];

      renderAiItems(items, disclaimer, reqId);

      // Auto-fill preliminary only if empty OR previously AI-filled
      const prelimEl = getFieldEl(form, "preliminary_diagnosis");
      if (prelimEl && preliminary) {
        const canReplace = !String(prelimEl.value || "").trim() || prelimEl.dataset.aiFilled === "1";
        if (canReplace) {
          prelimEl.value = preliminary;
          prelimEl.dataset.aiFilled = "1";
        }
      }

      showAiStatus("AI suggestions ready.", { severity }, reqId);

      clearStatusTimer();
      statusHideTimer = setTimeout(() => {
        showAiStatus("", {}, reqId);
      }, 2000);

      // Scroll to results
      const itemsBox = document.getElementById("aiItemsBox");
      if (itemsBox && itemsBox.style.display !== "none") {
        try { itemsBox.scrollIntoView({ behavior: "smooth", block: "nearest" }); } catch (_) {}
      }

    } catch (err) {
      if (reqId !== currentReqId) return;

      const isAbort = err && err.name === "AbortError";
      const msg = isAbort ? "" : (err && err.message ? err.message : "AI Assist failed. Please try again.");

      if (msg) {
        clearAiOutputs(reqId);
        showAiStatus(msg, { isError: true, severity: "danger" }, reqId);
      }
    } finally {
      try { clearTimeout(timeoutHandle); } catch (_) {}

      if (reqId === currentReqId) {
        setAiLoading(false, reqId);
        // release controller only if it's still the current one
        if (aiAbortController === controller) {
          aiAbortController = null;
        }
      }
    }
  }

  // ------------------------------------------------------------
  // Auto-clear stale AI output when inputs change
  // (and aborts in-flight request to avoid stale responses)
  // ------------------------------------------------------------
  function initAutoClearOnInput() {
    const form = document.getElementById("consultationForm");
    if (!form) return;

    const chiefEl = getFieldEl(form, "chief_complaint");
    const symptomsEl = getFieldEl(form, "symptoms");
    const historyEl = getFieldEl(form, "history");
    const examEl = getFieldEl(form, "examination");

    const clearAi = () => {
      // abort current request (prevents stale AI output)
      try {
        if (aiAbortController) aiAbortController.abort();
      } catch (_) {}

      clearStatusTimer();
      clearAiOutputs(currentReqId);

      const prelimEl = getFieldEl(form, "preliminary_diagnosis");
      if (prelimEl && prelimEl.dataset.aiFilled === "1") {
        prelimEl.dataset.aiFilled = "0";
      }

      // ensure button back to normal
      setAiLoading(false, currentReqId);
    };

    if (chiefEl) chiefEl.addEventListener("input", clearAi);
    if (symptomsEl) symptomsEl.addEventListener("input", clearAi);
    if (historyEl) historyEl.addEventListener("input", clearAi);
    if (examEl) examEl.addEventListener("input", clearAi);
  }

  // ------------------------------------------------------------
  // Abort request when leaving the page
  // ------------------------------------------------------------
  function initAbortOnUnload() {
    window.addEventListener("beforeunload", () => {
      try {
        if (aiAbortController) aiAbortController.abort();
      } catch (_) {}
    });
  }

})();
