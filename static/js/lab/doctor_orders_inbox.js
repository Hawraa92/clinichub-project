/* =========================================================
   File: static/js/lab/doctor_orders_inbox.js
   Ready badge polling + toast (simple + reliable)
========================================================= */

(function () {
  const badge = document.getElementById("labReadyBadge");
  const endpoint = document.querySelector('meta[name="lab-ready-endpoint"]')?.content;

  function setBadge(n) {
    if (!badge) return;
    if (n > 0) {
      badge.textContent = n;
      badge.style.display = "inline-flex";
    } else {
      badge.textContent = "";
      badge.style.display = "none";
    }
  }

  function toast(msg) {
    let t = document.getElementById("labToast");
    if (!t) {
      t = document.createElement("div");
      t.id = "labToast";
      t.className = "doi-toast";
      document.body.appendChild(t);
    }
    t.textContent = msg;
    t.classList.add("is-show");
    clearTimeout(window.__labToastTimer);
    window.__labToastTimer = setTimeout(() => {
      t.classList.remove("is-show");
    }, 3500);
  }

  // initial
  const init = Number(badge?.dataset?.init || 0);
  let prev = Number(localStorage.getItem("labReadyCount") || init);
  setBadge(prev);

  async function poll() {
    if (!endpoint) return;

    try {
      const r = await fetch(endpoint, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
        cache: "no-store",
      });

      // إذا الدور/الجلسة غلط أو صار خطأ: لا نخلي الرقم القديم يضل
      if (!r.ok) {
        setBadge(0);
        localStorage.setItem("labReadyCount", "0");
        prev = 0;
        return;
      }

      const data = await r.json();
      const n = Number(data.count || 0);

      // Toast only when unseen READY count increases
      if (n > prev) {
        toast("🔴 New lab result ready (" + n + ")");
      }

      prev = n;
      localStorage.setItem("labReadyCount", String(n));
      setBadge(n);
    } catch (e) {
      // silent fail
    }
  }

  poll();
  setInterval(poll, 20000);
})();
