// static/js/patient/patient_detail.js
"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const copyEls = Array.from(document.querySelectorAll("[data-copy]"));
  if (!copyEls.length) return;

  const showToast = (msg, duration = 1200) => {
    let t = document.querySelector(".pd-toast");
    if (!t) {
      t = document.createElement("div");
      t.className = "pd-toast";
      document.body.appendChild(t);
    }
    t.textContent = msg;
    t.classList.add("show");
    setTimeout(() => t.classList.remove("show"), duration);
  };

  if (!document.getElementById("pd-toast-style")) {
    const style = document.createElement("style");
    style.id = "pd-toast-style";
    style.textContent = `
      .pd-toast{
        position: fixed;
        left: 50%;
        bottom: 22px;
        transform: translateX(-50%) translateY(10px);
        background: rgba(15,23,42,0.92);
        color: #fff;
        padding: 10px 14px;
        border-radius: 12px;
        font-weight: 800;
        font-size: 13px;
        opacity: 0;
        transition: opacity .18s ease, transform .18s ease;
        z-index: 9999;
        pointer-events: none;
      }
      .pd-toast.show{
        opacity: 1;
        transform: translateX(-50%) translateY(0);
      }
    `;
    document.head.appendChild(style);
  }

  const copyText = async (val) => {
    try {
      await navigator.clipboard.writeText(val);
      showToast("Copied ✅");
    } catch {
      const ta = document.createElement("textarea");
      ta.value = val;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
      showToast("Copied ✅");
    }
  };

  copyEls.forEach((el) => {
    el.addEventListener("click", () => {
      const val = el.getAttribute("data-copy") || "";
      if (!val) return;
      copyText(val);
    });
  });
});
