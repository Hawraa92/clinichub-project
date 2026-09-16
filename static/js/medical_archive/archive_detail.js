// File: static/js/medical_archive/archive_detail.js
(() => {
  "use strict";

  class MedicalRecordDetail {
    constructor() {
      this.container = document.querySelector(".medical-record-container");
      this.recordId = this.container?.dataset?.recordId || this._extractRecordId() || null;
      this.listUrl = this.container?.dataset?.listUrl || "/";

      this.currentTab = "overview";

      // loader-kill runtime
      this._killTimers = [];
      this._lbWatchTimer = null;
      this._lbObserver = null;

      this.init();
    }

    init() {
      this.setupLightboxOptions();
      this.setupTabs();
      this.restoreTabState();

      this.setupHeaderActions();
      this.setupAudioPolicy();
      this.setupMessages();
      this.setupShareExport();

      // ✅ Fix: stop "global page loader" from getting stuck when opening Lightbox
      this.installLightboxSafeClick();

      this.bindEscapeForLightbox();
      this.injectToastStyles();
    }

    // -------------------------
    // Basic helpers
    // -------------------------
    _extractRecordId() {
      try {
        const el = document.querySelector(".record-id");
        const txt = (el?.textContent || "").trim();
        const m = txt.match(/#\s*(\d+)/);
        return m ? m[1] : null;
      } catch (_) {
        return null;
      }
    }

    _isModifiedClick(e) {
      return !!(e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.button === 1);
    }

    _getTabTargetId(btn) {
      const aria = btn?.getAttribute?.("aria-controls");
      if (aria) return aria;
      const tabName = btn?.dataset?.tab;
      return tabName ? `${tabName}-tab` : null;
    }

    _openLightboxForLink(a) {
      if (!a || !window.lightbox) return false;

      try {
        if (typeof window.lightbox.start === "function") {
          if (window.jQuery) {
            window.lightbox.start(window.jQuery(a));
            return true;
          }
          if (window.$ && typeof window.$ === "function") {
            window.lightbox.start(window.$(a));
            return true;
          }
          window.lightbox.start(a);
          return true;
        }

        if (typeof window.lightbox.showImage === "function") {
          window.lightbox.showImage(a);
          return true;
        }
      } catch (_) {
        return false;
      }

      return false;
    }

    _getExportUrl() {
      // ✅ BEST: read real href OR explicit dataset
      const btn = document.getElementById("exportBtn");
      const href = btn?.getAttribute?.("href");
      if (href) return href;

      const fromBtn = btn?.dataset?.exportUrl;
      if (fromBtn) return fromBtn;

      const fromContainer = this.container?.dataset?.exportUrl;
      if (fromContainer) return fromContainer;

      const path = window.location.pathname || "";
      if (this.recordId && /\/archive\/\d+\/?$/.test(path)) {
        const base = path.endsWith("/") ? path : `${path}/`;
        return `${base}export/pdf/`;
      }

      return this.recordId ? `/archive/archive/${this.recordId}/export/pdf/` : null;
    }

    // -------------------------
    // Lightbox
    // -------------------------
    setupLightboxOptions() {
      if (window.lightbox?.option) {
        window.lightbox.option({
          albumLabel: "Image %1 of %2",
          fadeDuration: 200,
          resizeDuration: 200,
          wrapAround: true,
          disableScrolling: true,
        });
      }
    }

    bindEscapeForLightbox() {
      document.addEventListener("keydown", (e) => {
        if (e.key !== "Escape") return;

        try {
          if (window.lightbox?.end) window.lightbox.end();
          else if (window.lightbox?.close) window.lightbox.close();
        } catch (_) {}

        this.kickLoaderKiller();
      });
    }

    installLightboxSafeClick() {
      const isLightboxLink = (target) =>
        target?.closest?.('a[data-lightbox], a[rel^="lightbox"], a[rel*="lightbox"]') || null;

      document.addEventListener(
        "click",
        (e) => {
          const a = isLightboxLink(e.target);
          if (!a) return;
          if (this._isModifiedClick(e)) return;
          if (!window.lightbox) return;

          e.preventDefault();
          e.stopImmediatePropagation();

          const opened = this._openLightboxForLink(a);

          if (!opened) {
            try {
              window.open(a.href, "_blank", "noopener");
            } catch (_) {
              window.location.href = a.href;
            }
          }

          this.kickLoaderKiller({ watchLightbox: true });
        },
        true
      );

      if (!this._lbObserver) {
        this._lbObserver = new MutationObserver(() => {
          const overlay = document.querySelector(".lightboxOverlay");
          if (overlay) this.kickLoaderKiller({ watchLightbox: true });
        });
        this._lbObserver.observe(document.body, { childList: true, subtree: true });
      }
    }

    // -------------------------
    // Tabs
    // -------------------------
    setupTabs() {
      this.tabBtns = Array.from(document.querySelectorAll(".tab-btn"));
      this.tabPanes = Array.from(document.querySelectorAll(".tab-pane"));
      if (!this.tabBtns.length || !this.tabPanes.length) return;

      this.tabBtns.forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.preventDefault();
          const tabName = btn.dataset.tab;
          if (!tabName) return;
          this.activateTab(tabName, btn, true);
        });

        btn.addEventListener("keydown", (e) => {
          if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
          e.preventDefault();
          const idx = this.tabBtns.indexOf(btn);
          const next = e.key === "ArrowRight" ? idx + 1 : idx - 1;
          const target = this.tabBtns[(next + this.tabBtns.length) % this.tabBtns.length];
          target?.focus();
          target?.click();
        });
      });
    }

    activateTab(tabName, btnRef = null, save = false) {
      const btn = btnRef || document.querySelector(`.tab-btn[data-tab="${tabName}"]`);
      const paneId = this._getTabTargetId(btn);
      if (!paneId) return;

      const pane = document.getElementById(paneId);
      if (!pane) {
        console.warn("Tab pane not found:", paneId);
        return;
      }

      this.tabBtns.forEach((b) => {
        const active = b === btn;
        b.classList.toggle("active", active);
        b.setAttribute("aria-selected", active ? "true" : "false");
        b.tabIndex = active ? 0 : -1;
      });

      this.tabPanes.forEach((p) => {
        const active = p.id === paneId;
        p.classList.toggle("active", active);
        p.hidden = !active;
      });

      this.currentTab = tabName;
      if (save) this.saveTabState();
    }

    saveTabState() {
      if (!this.recordId) return;
      try {
        localStorage.setItem(`medicalRecord:lastTab:${this.recordId}`, this.currentTab);
      } catch (_) {}
    }

    restoreTabState() {
      if (!this.tabBtns?.length) return;

      if (!this.recordId) {
        const activeBtn = this.tabBtns.find((b) => b.classList.contains("active")) || this.tabBtns[0];
        const activeName = activeBtn?.dataset?.tab || "overview";
        this.activateTab(activeName, activeBtn, false);
        return;
      }

      try {
        const saved = localStorage.getItem(`medicalRecord:lastTab:${this.recordId}`);
        if (saved) {
          const btn = document.querySelector(`.tab-btn[data-tab="${saved}"]`);
          if (btn) {
            btn.click();
            return;
          }
        }
      } catch (_) {}

      const activeBtn = this.tabBtns.find((b) => b.classList.contains("active")) || this.tabBtns[0];
      const activeName = activeBtn?.dataset?.tab || "overview";
      this.activateTab(activeName, activeBtn, false);
    }

    // -------------------------
    // Header actions
    // -------------------------
    setupHeaderActions() {
      document.getElementById("backBtn")?.addEventListener("click", (e) => {
        e.preventDefault();
        if (window.history.length > 1) window.history.back();
        else window.location.href = this.listUrl;
      });

      const printBtn = document.getElementById("printBtn") || document.querySelector(".print-btn");
      printBtn?.addEventListener("click", (e) => {
        e.preventDefault();
        this.printRecord();
      });

      document.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && (e.key === "p" || e.key === "P")) {
          e.preventDefault();
          this.printRecord();
        }
      });
    }

    printRecord() {
      const panes = document.querySelectorAll(".tab-pane");
      panes.forEach((p) => {
        p.hidden = false;
        p.style.display = "block";
      });

      window.print();

      setTimeout(() => {
        panes.forEach((p) => (p.style.display = ""));
        this.activateTab(this.currentTab, null, false);
      }, 150);
    }

    // -------------------------
    // Audio policy: only one plays
    // -------------------------
    setupAudioPolicy() {
      const audios = Array.from(document.querySelectorAll("audio"));
      audios.forEach((audio) => {
        audio.addEventListener("play", () => {
          audios.forEach((other) => {
            if (other !== audio) other.pause();
          });
        });
      });
    }

    // -------------------------
    // Messages (toasts)
    // -------------------------
    setupMessages() {
      const modal = document.querySelector(".messages-modal");
      if (!modal) return;

      modal.querySelectorAll(".message-alert").forEach((alert, idx) => {
        const close = alert.querySelector(".close-message");
        close?.addEventListener("click", () => this.dismissAlert(alert));
        setTimeout(() => this.dismissAlert(alert), 4500 + idx * 700);
      });
    }

    dismissAlert(alert) {
      if (!alert || alert.dataset.dismissing === "1") return;
      alert.dataset.dismissing = "1";
      alert.style.transition = "all .25s ease";
      alert.style.opacity = "0";
      alert.style.transform = "translateX(12px)";
      setTimeout(() => alert.remove(), 260);
    }

    // -------------------------
    // Share / Export
    // -------------------------
    setupShareExport() {
      document.getElementById("shareBtn")?.addEventListener("click", () => this.shareRecord());

      const exportBtn = document.getElementById("exportBtn");
      exportBtn?.addEventListener("click", (e) => {
        // ✅ FIX: prevent double navigation
        e.preventDefault();
        e.stopPropagation();
        this.exportRecord();
      });

      window.shareRecord = () => this.shareRecord();
      window.exportRecord = () => this.exportRecord();
    }

    async shareRecord() {
      const url = window.location.href;

      if (navigator.share) {
        try {
          await navigator.share({ title: "Medical Record", text: "Medical record details", url });
          return;
        } catch (_) {}
      }

      try {
        await navigator.clipboard.writeText(url);
        this.showToast("Link copied", "success");
      } catch (_) {
        this.showToast("Cannot copy link", "info");
      }
    }

    exportRecord() {
      const url = this._getExportUrl();
      if (!url) {
        this.showToast("Export URL not found", "info");
        return;
      }
      window.location.href = url;
    }

    // -------------------------
    // Loader killer (unchanged)
    // -------------------------
    kickLoaderKiller(opts = {}) {
      const { watchLightbox = false } = opts;

      this._clearKillTimers();

      [0, 30, 120, 260, 520, 900, 1400].forEach((ms) => {
        this._killTimers.push(setTimeout(() => this.killGlobalLoader(), ms));
      });

      if (watchLightbox) {
        if (this._lbWatchTimer) clearInterval(this._lbWatchTimer);

        const startedAt = Date.now();
        this._lbWatchTimer = setInterval(() => {
          const overlay = document.querySelector(".lightboxOverlay");
          const lbOpen = !!overlay && this._isVisible(overlay);

          if (lbOpen) this.killGlobalLoader();

          if (!lbOpen || Date.now() - startedAt > 6000) {
            clearInterval(this._lbWatchTimer);
            this._lbWatchTimer = null;
            this.killGlobalLoader();
          }
        }, 200);
      }
    }

    _clearKillTimers() {
      this._killTimers.forEach((t) => clearTimeout(t));
      this._killTimers = [];
    }

    _isVisible(el) {
      try {
        const st = window.getComputedStyle(el);
        return st.display !== "none" && st.visibility !== "hidden" && st.opacity !== "0";
      } catch (_) {
        return false;
      }
    }

    killGlobalLoader() {
      try {
        const body = document.body;
        const html = document.documentElement;

        [
          "loading",
          "page-loading",
          "is-loading",
          "busy",
          "nprogress-busy",
          "pace-running",
          "preloading",
          "app-loading",
        ].forEach((c) => {
          body.classList.remove(c);
          html.classList.remove(c);
        });

        body.removeAttribute("aria-busy");

        body.style.overflow = "";
        body.style.paddingRight = "";
        html.style.overflow = "";

        const hideEl = (el) => {
          if (!el || el.getAttribute("data-loader-killed") === "1") return;
          el.style.display = "none";
          el.style.opacity = "0";
          el.style.pointerEvents = "none";
          el.setAttribute("data-loader-killed", "1");
        };

        const selectors = [
          "#pageLoader",
          "#page-loader",
          "#globalLoader",
          "#global-loader",
          "#loader",
          "#preloader",
          "#pre-loader",
          "#loading-screen",
          "#loadingScreen",
          "#appLoader",
          ".page-loader",
          ".global-loader",
          ".loading-overlay",
          ".loader-overlay",
          ".overlay-loader",
          ".app-loader",
          ".preloader",
          ".preloader-wrapper",
          ".loader-wrapper",
          ".site-loader",
          ".splash-screen",
          ".splash",
          ".loading-screen",
          ".spinner-overlay",
          ".loading-backdrop",
          ".loading-mask",
        ];
        selectors.forEach((sel) => document.querySelectorAll(sel).forEach(hideEl));
      } catch (_) {}
    }

    // -------------------------
    // Toast
    // -------------------------
    showToast(message, type = "info") {
      const toast = document.createElement("div");
      toast.className = `toast toast-${type}`;
      toast.innerHTML = `
        <i class="fas ${type === "success" ? "fa-check-circle" : "fa-info-circle"}" aria-hidden="true"></i>
        <span>${this.escapeHtml(message)}</span>
      `;
      document.body.appendChild(toast);

      requestAnimationFrame(() => toast.classList.add("show"));
      setTimeout(() => {
        toast.classList.remove("show");
        setTimeout(() => toast.remove(), 260);
      }, 2400);
    }

    escapeHtml(text) {
      const div = document.createElement("div");
      div.textContent = String(text);
      return div.innerHTML;
    }

    injectToastStyles() {
      const style = document.createElement("style");
      style.textContent = `
        .toast{
          position:fixed;left:50%;bottom:96px;
          transform:translateX(-50%) translateY(12px);
          background:var(--surface);
          color:var(--text-primary);
          padding:10px 14px;
          border-radius:var(--radius-md);
          display:flex;align-items:center;gap:10px;
          box-shadow:var(--shadow-lg);
          opacity:0;transition:all .25s ease;
          z-index:9999;border:1px solid var(--border);
          min-width:220px;justify-content:center;
        }
        .toast.show{ opacity:1; transform:translateX(-50%) translateY(0); }
        .toast-success{ border-left:4px solid var(--success); }
        .toast-info{ border-left:4px solid var(--primary); }
      `;
      document.head.appendChild(style);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    new MedicalRecordDetail();
  });
})();
