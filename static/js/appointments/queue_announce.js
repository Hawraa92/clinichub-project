/* static/js/appointments/queue_announce.js
 * Pro-grade bilingual (Arabic & English) queue announcements + optional live signage.
 * - Uses real API data (APP_CONFIG.ANNOUNCE_API or QUEUE_API or /appointments/queue-number-api/)
 * - Supports both shapes:
 *      1) { doctors: [ {id, name, specialty, room, queue:[{ticket, patient}]} ] }
 *      2) { queues:  [ {doctor_id, doctor_name, current_patient, waiting_list, ...} ] }
 * - Default AR→EN sequence (override via APP_CONFIG.ANNOUNCE_SEQUENCE)
 */

(function () {
  "use strict";

  // ===================== GLOBAL CONFIG =====================
  const GLOBAL_CFG = window.APP_CONFIG || {};

  const CFG = {
    API_URL:
      GLOBAL_CFG.ANNOUNCE_API ||
      GLOBAL_CFG.QUEUE_API ||
      "/appointments/queue-number-api/",

    POLL_MS: GLOBAL_CFG.ANNOUNCE_POLL_MS || 6000,
    ANNOUNCE_SEQUENCE: GLOBAL_CFG.ANNOUNCE_SEQUENCE || ["ar", "en"],

    GLOBAL_THROTTLE_MS: 2500,
    PER_DOCTOR_COOLDOWN_MS: 12000,

    CHIME_ENABLED: true,
    CHIME_TONE_MS: 240,
    CHIME_GAP_MS: 80,
    CHIME_TONES: [880, 1175], // A5 → D6

    DEFAULT_LANGS: { ar: "ar-SA", en: "en-GB" },
    AR_EASTERN_NUMERALS: true,
    REQUIRE_VISIBLE_TAB: true,
    MAX_UTTER_CHARS: 280,
  };

  // =================== UI ELEMENTS (optional) ===================
  const btnToggle = document.getElementById("toggle-announce");
  const selVoice = document.getElementById("voice-select");
  const selVoiceEn = document.getElementById("voice-select-en");
  const selVoiceAr = document.getElementById("voice-select-ar");
  const rateEl = document.getElementById("rate");
  const volEl = document.getElementById("volume");
  const testBtn = document.getElementById("test-announce");
  const listEl = document.getElementById("queue-list");
  const unsupportedBox = document.getElementById("announce-unsupported");

  // =================== LOCAL STORAGE KEYS ===================
  const LS = {
    enabled: "qa_enabled",
    voiceOverride: "qa_voice",
    voiceEN: "qa_voice_en",
    voiceAR: "qa_voice_ar",
    rate: "qa_rate",
    volume: "qa_volume",
  };

  let enabled = JSON.parse(localStorage.getItem(LS.enabled) || "false");
  let voices = [];

  let voiceOverride = localStorage.getItem(LS.voiceOverride) || "";
  let voiceEN = localStorage.getItem(LS.voiceEN) || "";
  let voiceAR = localStorage.getItem(LS.voiceAR) || "";

  let rate = parseFloat(localStorage.getItem(LS.rate) || "1") || 1;
  let volume = parseFloat(localStorage.getItem(LS.volume) || "1") || 1;

  if (rateEl) rateEl.value = String(rate);
  if (volEl) volEl.value = String(volume);

  // ================== SPEECH PIPELINE ==================
  const speechQueue = [];
  let speaking = false;
  let lastGlobalAt = 0;

  function queueUtter(text, lang) {
    if (!enabled) return; // ✅ منع التراكم إذا disabled
    if (!text || !("speechSynthesis" in window)) return;

    const chunks =
      String(text).match(new RegExp(`.{1,${CFG.MAX_UTTER_CHARS}}`, "g")) || [];

    chunks.forEach((c) => speechQueue.push({ text: c, lang }));
    pump();
  }

  function pump() {
    if (!enabled) return;
    if (speaking) return;
    if (!speechQueue.length) return;
    if (!("speechSynthesis" in window)) return;
    if (CFG.REQUIRE_VISIBLE_TAB && document.hidden) return;

    const now = Date.now();
    if (now - lastGlobalAt < CFG.GLOBAL_THROTTLE_MS) {
      setTimeout(pump, CFG.GLOBAL_THROTTLE_MS - (now - lastGlobalAt) + 10);
      return;
    }

    const { text, lang } = speechQueue.shift();
    speaking = true;

    const utter = new SpeechSynthesisUtterance(text);
    const v = pickVoice(lang);
    if (v) utter.voice = v;

    utter.lang = (lang === "ar") ? CFG.DEFAULT_LANGS.ar : CFG.DEFAULT_LANGS.en;
    utter.rate = rate;
    utter.pitch = 1;
    utter.volume = volume;

    utter.onend = () => {
      speaking = false;
      lastGlobalAt = Date.now();
      setTimeout(pump, 60);
    };

    utter.onerror = () => {
      speaking = false;
      setTimeout(pump, 60);
    };

    window.speechSynthesis.speak(utter);
  }

  function flush() {
    try {
      if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    } catch {}
    speechQueue.length = 0;
    speaking = false;
  }

  // Helper داخل الملف بدل queueSpeak (حتى ما يصير ReferenceError)
  function speak(text, lang) {
    queueUtter(String(text || ""), lang === "ar" ? "ar" : "en");
  }

  // ====================== CHIME ======================
  async function chime() {
    if (!enabled) return; // ✅ لا رنة إذا disabled
    if (!CFG.CHIME_ENABLED) return;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;

    let ctx = null;
    try {
      ctx = new AC();
      if (ctx.state === "suspended") {
        // قد يحتاج user gesture ببعض المتصفحات
        await ctx.resume().catch(() => {});
      }

      const t0 = ctx.currentTime;

      CFG.CHIME_TONES.forEach((freq, i) => {
        const osc = ctx.createOscillator();
        const g = ctx.createGain();
        osc.type = "sine";
        osc.frequency.value = freq;
        osc.connect(g);
        g.connect(ctx.destination);

        const start = t0 + (i * (CFG.CHIME_TONE_MS + CFG.CHIME_GAP_MS)) / 1000;
        const end = start + CFG.CHIME_TONE_MS / 1000;

        g.gain.setValueAtTime(0.0001, start);
        g.gain.exponentialRampToValueAtTime(0.6, start + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, end);

        osc.start(start);
        osc.stop(end + 0.01);
      });

      const total =
        CFG.CHIME_TONES.length * (CFG.CHIME_TONE_MS + CFG.CHIME_GAP_MS);

      await new Promise((r) => setTimeout(r, total + 30));
    } catch {
      // silent
    } finally {
      try {
        if (ctx) await ctx.close();
      } catch {}
    }
  }

  // ===================== VOICES ======================
  function loadVoicesIntoSelects() {
    voices = window.speechSynthesis ? window.speechSynthesis.getVoices() : [];

    if (selVoice) {
      const prev = voiceOverride;
      selVoice.innerHTML = '<option value="">Auto Voice</option>';
      voices.forEach((v) => {
        const opt = document.createElement("option");
        opt.value = v.name;
        opt.textContent = `${v.name} (${v.lang})`;
        if (v.name === prev) opt.selected = true;
        selVoice.appendChild(opt);
      });
    }

    if (selVoiceEn) {
      const prev = voiceEN;
      selVoiceEn.innerHTML = '<option value="">Auto EN</option>';
      voices
        .filter((v) => /^en(\b|-|_)/i.test(v.lang))
        .forEach((v) => {
          const opt = document.createElement("option");
          opt.value = v.name;
          opt.textContent = `${v.name} (${v.lang})`;
          if (v.name === prev) opt.selected = true;
          selVoiceEn.appendChild(opt);
        });
    }

    if (selVoiceAr) {
      const prev = voiceAR;
      selVoiceAr.innerHTML = '<option value="">صوت عربي تلقائي</option>';
      voices
        .filter((v) => /^ar(\b|-|_)/i.test(v.lang) || /arabic/i.test(v.name || ""))
        .forEach((v) => {
          const opt = document.createElement("option");
          opt.value = v.name;
          opt.textContent = `${v.name} (${v.lang})`;
          if (v.name === prev) opt.selected = true;
          selVoiceAr.appendChild(opt);
        });
    }
  }

  function vByName(name) {
    return voices.find((v) => v.name === name) || null;
  }

  function pickVoice(lang) {
    if (!("speechSynthesis" in window)) return null;

    if (voiceOverride) {
      const v = vByName(voiceOverride);
      if (v) return v;
    }

    if (lang === "en") {
      const per = (selVoiceEn && selVoiceEn.value) || voiceEN;
      if (per) {
        const vv = vByName(per);
        if (vv) return vv;
      }
    } else {
      const per = (selVoiceAr && selVoiceAr.value) || voiceAR;
      if (per) {
        const vv = vByName(per);
        if (vv) return vv;
      }
    }

    const prefer = (pred) => {
      const list = voices.filter(pred);
      const neural = list.find((v) => /Natural|Online/i.test(v.name || ""));
      return neural || list[0] || null;
    };

    if (lang === "ar") {
      return (
        prefer((v) => /^ar-SA$/i.test(v.lang)) ||
        prefer((v) => /^ar(\b|-|_)/i.test(v.lang)) ||
        prefer((v) => /arabic/i.test(v.name || "")) ||
        voices[0] ||
        null
      );
    }

    return (
      prefer((v) => /^en-GB$/i.test(v.lang)) ||
      prefer((v) => /^en(\b|-|_)/i.test(v.lang)) ||
      prefer((v) => /English/i.test(v.name || "")) ||
      voices[0] ||
      null
    );
  }

  // =================== UTILITIES =====================
  function toEasternDigits(s) {
    if (!CFG.AR_EASTERN_NUMERALS) return String(s);
    const map = ["٠","١","٢","٣","٤","٥","٦","٧","٨","٩"];
    return String(s).replace(/\d/g, (d) => map[Number(d)]);
  }

  function normalizeNumber(n) {
    if (n == null) return "";
    return String(n).replace(/^P-/, "").replace(/^0+/, "");
  }

  function sanitizeName(str) {
    if (!str) return "";
    return String(str).replace(/\s+/g, " ").trim();
  }

  function detectLang(text) {
    return /[\u0600-\u06FF]/.test(text) ? "ar" : "en";
  }

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // ========== CONVERT {doctors: [...] } → "queues" ==========
  function doctorsToQueues(doctorsPayload) {
    return (doctorsPayload || []).map((d) => {
      const qArr = Array.isArray(d.queue) ? d.queue : [];
      const currentRaw = qArr[0] || null;
      const waitingRaw = qArr.slice(1);

      const current = currentRaw
        ? {
            id: currentRaw.id || currentRaw.ticket || null,
            number: currentRaw.ticket || "",
            queue_number: currentRaw.ticket || "",
            patient_name: currentRaw.patient || currentRaw.name || "",
          }
        : null;

      const waiting_list = waitingRaw.map((w) => ({
        id: w.id || w.ticket || null,
        number: w.ticket || "",
        queue_number: w.ticket || "",
        patient_name: w.patient || w.name || "",
      }));

      return {
        doctor_id: d.id,
        doctor_name: d.name || d.doctor_name || "",
        current_patient: current,
        waiting_list,
        waiting: waiting_list.length,
        next_queue: current ? (current.number || current.queue_number) : "",
      };
    });
  }

  // =================== TEMPLATES =====================
  const TPL = {
    en: {
      now: ({ num, patient, doctor }) =>
        `Now serving patient number ${num}. ${patient}. Please proceed to Dr. ${doctor}.`,
      next: ({ patient }) => (patient ? `Next: ${patient}.` : ""),
    },
    ar: {
      now: ({ num, patient, doctor }) =>
        `يتم الآن خدمة المريض رقم ${toEasternDigits(num)}. ${patient}. يرجى التوجه إلى الدكتور ${doctor}.`,
      next: ({ patient }) => (patient ? `التالي: ${patient}.` : ""),
    },
  };

  window.queueAnnounceTemplate = {
    set(lang, key, fn) {
      if (TPL[lang] && typeof fn === "function" && key in TPL[lang]) {
        TPL[lang][key] = fn;
        return true;
      }
      return false;
    },
    get() {
      return JSON.parse(JSON.stringify(TPL));
    },
  };

  function buildTextsFromQueue(queue) {
    const now = queue.current_patient || queue.current || null;

    const waitingArr = Array.isArray(queue.waiting_list)
      ? queue.waiting_list
      : Array.isArray(queue.waiting)
      ? queue.waiting
      : [];

    const next = waitingArr.length ? waitingArr[0] : null;

    const num = now
      ? normalizeNumber(now.number || now.queue_number || "")
      : normalizeNumber(queue.next_queue || "");

    const patientNow = now ? sanitizeName(now.patient_name || "") : "";
    const patientNext = next ? sanitizeName(next.patient_name || "") : "";
    const doctor = sanitizeName(queue.doctor_name || "");

    const enParts = [];
    const arParts = [];

    if (num) {
      enParts.push(
        TPL.en.now({ num, patient: patientNow || "—", doctor })
      );
      arParts.push(
        TPL.ar.now({ num, patient: patientNow || "—", doctor })
      );
    }

    if (patientNext) {
      enParts.push(TPL.en.next({ patient: patientNext }));
      arParts.push(TPL.ar.next({ patient: patientNext }));
    }

    return {
      enText: enParts.filter(Boolean).join(" "),
      arText: arParts.filter(Boolean).join(" "),
    };
  }

  async function announceQueue(queue) {
    if (!enabled) return; // ✅ لا شيء إذا disabled
    if (CFG.REQUIRE_VISIBLE_TAB && document.hidden) return;

    const { enText, arText } = buildTextsFromQueue(queue);

    const seq = [];
    (CFG.ANNOUNCE_SEQUENCE || []).forEach((lang) => {
      if (lang === "ar" && arText) seq.push({ text: arText, lang: "ar" });
      if (lang === "en" && enText) seq.push({ text: enText, lang: "en" });
    });

    if (!seq.length) return;

    await chime();
    seq.forEach((p) => queueUtter(p.text, p.lang));
  }

  // ======== ANNOUNCE DECISION (per-doctor) ========
  const docState = {}; // { [doctorId]: { currentKey, nextKey, lastAnnouncedAt } }

  function shouldAnnounce(doctorId, currentKey, nextKey) {
    const now = Date.now();
    const prev = docState[doctorId] || {
      currentKey: null,
      nextKey: null,
      lastAnnouncedAt: 0,
    };

    const changed = prev.currentKey !== currentKey || prev.nextKey !== nextKey;

    // ✅ نحدّث المفاتيح دائماً حتى ما نكرر نفس الحالة
    if (changed) {
      prev.currentKey = currentKey;
      prev.nextKey = nextKey;
      docState[doctorId] = prev;
    } else {
      docState[doctorId] = prev;
      return false;
    }

    const cooldownOk = now - prev.lastAnnouncedAt >= CFG.PER_DOCTOR_COOLDOWN_MS;
    if (!cooldownOk) return false;

    prev.lastAnnouncedAt = now;
    docState[doctorId] = prev;
    return true;
  }

  // ====================== POLLING ======================
  let pollTimer = null;

  async function poll() {
    if (!enabled) return;
    if (CFG.REQUIRE_VISIBLE_TAB && document.hidden) return;

    try {
      const res = await fetch(CFG.API_URL, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!res.ok) return;

      const data = await res.json();
      if (!data || data.success === false) return;

      let queues = [];

      if (Array.isArray(data.queues)) {
        queues = data.queues.slice();
      } else if (Array.isArray(data.doctors)) {
        queues = doctorsToQueues(data.doctors);
      } else {
        return;
      }

      queues.sort((a, b) => (a.doctor_id || 0) - (b.doctor_id || 0));

      if (listEl) renderLiveSignage(queues);

      for (const q of queues) {
        const docId = String(q.doctor_id || 0);

        const nowObj = q.current_patient || q.current || null;

        const waitingArr = Array.isArray(q.waiting_list)
          ? q.waiting_list
          : Array.isArray(q.waiting)
          ? q.waiting
          : [];

        const nextObj = waitingArr.length > 0 ? waitingArr[0] : null;

        const curKey =
          (nowObj && (nowObj.id || normalizeNumber(nowObj.number || nowObj.queue_number || ""))) ||
          normalizeNumber(q.next_queue || "");

        const nxtKey =
          (nextObj && (nextObj.id || normalizeNumber(nextObj.number || nextObj.queue_number || ""))) ||
          null;

        if (!curKey && !nxtKey) continue;

        if (shouldAnnounce(docId, curKey, nxtKey)) {
          await announceQueue(q);
          await new Promise((r) => setTimeout(r, 400));
        }
      }
    } catch {
      // Silent on transient errors
    }
  }

  function startPolling() {
    stopPolling();
    poll();
    pollTimer = setInterval(poll, CFG.POLL_MS);
  }

  function stopPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
  }

  // =================== LIVE SIGNAGE (optional) ===================
  function renderLiveSignage(queues) {
    if (!listEl) return;

    listEl.innerHTML = queues
      .map((q) => {
        const nowObj = q.current_patient || q.current || null;

        const waitingArr = Array.isArray(q.waiting_list)
          ? q.waiting_list
          : Array.isArray(q.waiting)
          ? q.waiting
          : [];

        const nextObj = waitingArr.length > 0 ? waitingArr[0] : null;

        const curNum = nowObj ? normalizeNumber(nowObj.number || "") : normalizeNumber(q.next_queue || "");
        const curName = nowObj ? sanitizeName(nowObj.patient_name || "") : "—";
        const nextName = nextObj ? sanitizeName(nextObj.patient_name || "") : "—";

        const waiting =
          Array.isArray(q.waiting_list) || Array.isArray(q.waiting)
            ? waitingArr.length
            : q.waiting || 0;

        const safeDoctor = escapeHtml(sanitizeName(q.doctor_name || ""));
        const safeCurName = escapeHtml(curName);
        const safeNextName = escapeHtml(nextName);

        return `
          <div class="doctor-card" role="group" aria-label="Doctor queue">
            <div class="doc-head">
              <div class="doc-avatar" aria-hidden="true">👨‍⚕️</div>
              <div class="doc-meta">
                <div class="doc-name">Dr. ${safeDoctor}</div>
                <div class="doc-status">
                  <span class="badge online">Online</span>
                  <span class="badge waiting">Waiting: ${waiting < 0 ? 0 : waiting}</span>
                </div>
              </div>
            </div>
            <div class="now-serving">
              <div class="label">Now Serving</div>
              <div class="lcd">
                <div class="num">${curNum ? toEasternDigits(curNum) : "—"}</div>
                <div class="name" dir="${detectLang(curName) === "ar" ? "rtl" : "ltr"}">${safeCurName || "—"}</div>
              </div>
            </div>
            <div class="next-up">
              <div class="label">Next</div>
              <div class="next-name" dir="${detectLang(nextName) === "ar" ? "rtl" : "ltr"}">${safeNextName || "—"}</div>
            </div>
            <button class="btn-call" type="button" data-doc="${escapeHtml(String(q.doctor_id || ""))}">🔔 Call Next</button>
          </div>
        `;
      })
      .join("");

    listEl.querySelectorAll(".btn-call").forEach((btn) => {
      btn.addEventListener("click", () => {
        // ✅ كان يسبب ReferenceError
        speak("Calling next.", "en");
      });
    });
  }

  // ======================= UI HOOKS ===================
  function refreshToggle() {
    if (!btnToggle) return;
    btnToggle.classList.toggle("active", enabled);
    btnToggle.textContent = enabled
      ? "🔇 Disable Announcements"
      : "🔊 Enable Announcements";
  }

  if (btnToggle) {
    btnToggle.addEventListener("click", () => {
      enabled = !enabled;
      localStorage.setItem(LS.enabled, JSON.stringify(enabled));
      refreshToggle();

      flush(); // ✅ منع أي تراكم قديم

      if (enabled) {
        startPolling();
        speak("تم تفعيل الإعلانات الصوتية.", "ar");
      } else {
        stopPolling();
      }
    });
  }

  if (selVoice) {
    selVoice.addEventListener("change", () => {
      voiceOverride = selVoice.value || "";
      localStorage.setItem(LS.voiceOverride, voiceOverride);
      if (enabled) speak("Voice changed.", "en");
    });
  }

  if (selVoiceEn) {
    selVoiceEn.addEventListener("change", () => {
      voiceEN = selVoiceEn.value || "";
      localStorage.setItem(LS.voiceEN, voiceEN);
      if (enabled) speak("English voice set.", "en");
    });
  }

  if (selVoiceAr) {
    selVoiceAr.addEventListener("change", () => {
      voiceAR = selVoiceAr.value || "";
      localStorage.setItem(LS.voiceAR, voiceAR);
      if (enabled) speak("تم اختيار صوت عربي.", "ar");
    });
  }

  if (rateEl) {
    rateEl.addEventListener("input", () => {
      rate = parseFloat(rateEl.value) || 1;
      localStorage.setItem(LS.rate, String(rate));
    });
  }

  if (volEl) {
    volEl.addEventListener("input", () => {
      volume = parseFloat(volEl.value) || 1;
      localStorage.setItem(LS.volume, String(volume));
    });
  }

  if ("speechSynthesis" in window) {
    loadVoicesIntoSelects();
    window.speechSynthesis.onvoiceschanged = loadVoicesIntoSelects;
  } else {
    if (unsupportedBox) unsupportedBox.hidden = false;
    if (btnToggle) btnToggle.disabled = true;
    if (testBtn) testBtn.disabled = true;
  }

  if (testBtn) {
    testBtn.addEventListener("click", async () => {
      const sample = {
        doctor_id: 1,
        doctor_name: "عمر",
        current_patient: { id: 101, number: "P-007", patient_name: "زهراء محمد" },
        waiting_list: [{ id: 102, number: "P-008", patient_name: "Ali Kareem" }],
      };
      enabled = true; // ✅ حتى يسمّع الاختبار لو كان مطفي (اختياري)
      await announceQueue(sample);
    });
  }

  // =================== PUBLIC HELPERS =================
  window.queueSpeak = function (text, langHint) {
    if (!text || !("speechSynthesis" in window)) return;
    if (!enabled) return;
    queueUtter(String(text), langHint === "ar" ? "ar" : "en");
  };

  window.queueSpeakAuto = function (text) {
    if (!text || !("speechSynthesis" in window)) return;
    if (!enabled) return;
    const lang = detectLang(String(text));
    queueUtter(String(text), lang);
  };

  window.queueAnnounceFor = async function (queueObj) {
    if (!queueObj) return;
    if (!enabled) return;
    await announceQueue(queueObj);
  };

  // ✅ متوافقة مع queue_display.js
  window.playQueueAnnouncement = function (ticket) {
    if (!enabled) return; // ✅ لا رنة ولا نداء إذا مطفي
    if (!ticket) {
      if (
        window.__queueSystemInstance &&
        typeof window.__queueSystemInstance.getServingPatients === "function"
      ) {
        const list = window.__queueSystemInstance.getServingPatients();
        ticket = list && list[0];
      }
    }
    if (!ticket) return;

    const qObj = {
      doctor_id: 0,
      doctor_name: ticket.doctor || "",
      current_patient: {
        id: null,
        number: ticket.number || "",
        patient_name: ticket.patient || "",
        time: "",
      },
      waiting_list: [],
    };
    announceQueue(qObj);
  };

  document.addEventListener("queue:callNext:success", (ev) => {
    if (!enabled) return;
    const q = ev && ev.detail && ev.detail.queue;
    if (q) announceQueue(q);
  });

  // ====================== LIFECYCLE ===================
  refreshToggle();
  if (enabled) {
    flush();
    startPolling();
  }

  document.addEventListener("visibilitychange", () => {
    if (!CFG.REQUIRE_VISIBLE_TAB) return;
    if (document.hidden) stopPolling();
    else if (enabled) startPolling();
  });
})();
