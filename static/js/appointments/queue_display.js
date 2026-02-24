// =======================
// ClinicHub – Digital Queue (Real Data)
// - SAFE AUTO MODE
// - AUTO ANNOUNCE ON CHANGE (works even if secretary calls next from another page)
// - Announces: current patient + doctor + (next patient) when available
// - Sound unlock overlay يظهر مرة واحدة فقط (يحفظ في LocalStorage/SessionStorage)
// File: static/js/appointments/queue_display.js
// =======================

(function () {
  "use strict";

  // ---------- Global config from Django ----------
  const CONFIG = window.APP_CONFIG || {};
  const IS_INTERNAL_USER = Boolean(CONFIG.IS_INTERNAL_USER);

  const PUBLIC_QUEUE_API =
    CONFIG.PUBLIC_QUEUE_API ||
    CONFIG.QUEUE_PUBLIC_API ||
    CONFIG.QUEUE_API_PUBLIC ||
    "/appointments/public/queue-number-api/";

  const INTERNAL_QUEUE_API =
    CONFIG.INTERNAL_QUEUE_API ||
    CONFIG.QUEUE_INTERNAL_API ||
    CONFIG.QUEUE_API_INTERNAL ||
    CONFIG.QUEUE_API ||
    "/appointments/queue-number-api/";

  // ✅ Choose correct queue endpoint
  const QUEUE_API = IS_INTERNAL_USER ? INTERNAL_QUEUE_API : PUBLIC_QUEUE_API;

  const CALL_NEXT_API_TEMPLATE =
    CONFIG.CALL_NEXT_API || "/appointments/secretary/queue/call-next/0/";

  const REFRESH_INTERVAL = Number(CONFIG.REFRESH_INTERVAL || 10000);

  const RAW_AUTO_CALL_INTERVAL = Number(CONFIG.NOW_SERVING_INTERVAL || 8000);
  const AUTO_CALL_INTERVAL = Math.max(6000, RAW_AUTO_CALL_INTERVAL || 8000);

  const CONFIG_CSRF = (CONFIG.CSRF_TOKEN || "").trim();

  // ---------- Voice / Beep Settings ----------
  const ENABLE_VOICE =
    CONFIG.ENABLE_VOICE === undefined ? true : Boolean(CONFIG.ENABLE_VOICE);

  const ENABLE_BEEP =
    CONFIG.ENABLE_BEEP === undefined ? true : Boolean(CONFIG.ENABLE_BEEP);

  const ANNOUNCE_WITH_PATIENT_NAME =
    CONFIG.ANNOUNCE_WITH_PATIENT_NAME === undefined
      ? true
      : Boolean(CONFIG.ANNOUNCE_WITH_PATIENT_NAME);

  // Public screen privacy: never announce patient name unless internal
  const CAN_SAY_PATIENT_NAME = IS_INTERNAL_USER && ANNOUNCE_WITH_PATIENT_NAME;

  const AUTO_ANNOUNCE_ON_CHANGE =
    CONFIG.AUTO_ANNOUNCE_ON_CHANGE === undefined
      ? true
      : Boolean(CONFIG.AUTO_ANNOUNCE_ON_CHANGE);

  const PER_DOCTOR_ANNOUNCE_COOLDOWN_MS = Number(
    CONFIG.PER_DOCTOR_ANNOUNCE_COOLDOWN_MS || 12000
  );

  const ANNOUNCE_SEQUENCE =
    Array.isArray(CONFIG.ANNOUNCE_SEQUENCE) && CONFIG.ANNOUNCE_SEQUENCE.length
      ? CONFIG.ANNOUNCE_SEQUENCE
      : ["ar", "en"];

  const SPEECH_LANG_AR = String(CONFIG.SPEECH_LANG_AR || "ar-IQ");
  const SPEECH_LANG_EN = String(CONFIG.SPEECH_LANG_EN || "en-US");

  // ✅ الافتراضي: ما نوقف الإعلان إذا التب مخفي، لأن شاشة TV ممكن تكون hidden ببعض البيئات
  const ANNOUNCE_REQUIRE_VISIBLE_TAB =
    CONFIG.ANNOUNCE_REQUIRE_VISIBLE_TAB === undefined
      ? false
      : Boolean(CONFIG.ANNOUNCE_REQUIRE_VISIBLE_TAB);

  const SHOW_SOUND_UNLOCK_OVERLAY =
    CONFIG.SHOW_SOUND_UNLOCK_OVERLAY === undefined
      ? true
      : Boolean(CONFIG.SHOW_SOUND_UNLOCK_OVERLAY);

  // ---------- Language & i18n ----------
  let currentLang = "en";

  const i18n = {
    en: {
      headerSubtitle: "Digital Queue Management – Powered by MisbahTech",
      headerMessage:
        "Please wait until your ticket and name appear on the screen.",
      filterLabel: "Filter by doctor",
      filterAll: "All doctors",
      panelNowServing: "Now Serving",
      panelDoctors: "Doctors & Rooms",
      panelQueue: "Queue Overview",
      btnAutoOn: "Start auto calling",
      btnAutoOff: "Stop auto calling",
      statusCalling: "Calling patient",
      labelTicket: "Ticket",
      labelCurrentTicket: "Current ticket:",
      labelNone: "No active ticket",
      labelWaitingForDoctor: "Waiting for this doctor",
      labelNoQueue: "No one waiting",
      labelNext: "Next:",
      emptyTicket: "Waiting for the next patient…",
      waitingWord: "waiting",
      roomPrefix: "Room",
      totalWord: "total",
      errUnauthorized:
        "Queue screen needs staff login to show private patient names.",
      errGeneric: "Cannot load queue from server.",
    },
    ar: {
      headerSubtitle: "نظام إدارة الطابور الرقمي – بدعم من MisbahTech",
      headerMessage: "يرجى الانتظار حتى يظهر رقمك واسمك على الشاشة.",
      filterLabel: "تصفية حسب الطبيب",
      filterAll: "جميع الأطباء",
      panelNowServing: "جاري خدمتكم الآن",
      panelDoctors: "الأطباء والغرف",
      panelQueue: "نظرة عامة على الطابور",
      btnAutoOn: "تشغيل النداء التلقائي",
      btnAutoOff: "إيقاف النداء التلقائي",
      statusCalling: "يتم نداء المريض",
      labelTicket: "رقم التذكرة",
      labelCurrentTicket: "التذكرة الحالية:",
      labelNone: "لا توجد تذكرة نشطة",
      labelWaitingForDoctor: "عدد المنتظرين لهذا الطبيب",
      labelNoQueue: "لا يوجد مرضى بانتظار الدور",
      labelNext: "التالي:",
      emptyTicket: "بانتظار المريض التالي…",
      waitingWord: "منتظر",
      roomPrefix: "غرفة",
      totalWord: "إجمالي",
      errUnauthorized: "هذه الشاشة تحتاج تسجيل دخول للموظف لعرض أسماء المرضى.",
      errGeneric: "تعذر تحميل الطابور من السيرفر.",
    },
  };

  function t(key) {
    return (i18n[currentLang] && i18n[currentLang][key]) || key;
  }

  // ---------- Safe HTML ----------
  function escapeHTML(value) {
    const s = String(value ?? "");
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // ---------- Dynamic ticker messages ----------
  const tickerMessages = {
    en: [
      "ClinicHub Digital Queue System – Powered by MisbahTech.",
      "Please keep your ticket ready and wait until your number and name appear on the screen.",
      "Please keep noise to a minimum and respect patient privacy inside the clinic.",
    ],
    ar: [
      "نظام إدارة الطابور ClinicHub – بدعم من MisbahTech.",
      "يرجى الاحتفاظ برقم الدور لحين ظهور رقمك واسمك على الشاشة.",
      "نرجو الحفاظ على الهدوء واحترام خصوصية المرضى داخل العيادة.",
    ],
  };

  let tickerIndex = 0;

  // ---------- Data / State ----------
  let doctors = [];
  let activeDoctorId = null;
  let autoCallTimer = null;
  let callInFlight = false;

  let loadInFlight = false;
  let loadQueued = false;

  let lastCallAt = 0;
  const MIN_CALL_GAP_MS = 2500;

  // ==============
  // CLOCK
  // ==============
  function updateClock() {
    const now = new Date();
    const dateEl = document.getElementById("q-date");
    const timeEl = document.getElementById("q-time");
    if (!dateEl || !timeEl) return;

    const dateOptions = {
      weekday: "short",
      year: "numeric",
      month: "short",
      day: "numeric",
    };
    dateEl.textContent = now.toLocaleDateString(undefined, dateOptions);
    timeEl.textContent = now.toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  // ==============
  // HELPERS
  // ==============
  function getCookie(name) {
    const cookies = document.cookie ? document.cookie.split(";") : [];
    for (let c of cookies) {
      c = c.trim();
      if (c.startsWith(name + "=")) return c.substring((name + "=").length);
    }
    return "";
  }

  function getCsrfToken() {
    return CONFIG_CSRF || getCookie("csrftoken") || "";
  }

  function buildCallNextUrl(doctorId) {
    const tpl = String(CALL_NEXT_API_TEMPLATE || "");
    if (!tpl) return null;

    if (tpl.includes("__DOCTOR_ID__"))
      return tpl.replace("__DOCTOR_ID__", String(doctorId));
    if (/\/0\/?$/.test(tpl)) return tpl.replace(/\/0\/?$/, `/${doctorId}/`);
    if (tpl.includes("/0/")) return tpl.replace("/0/", `/${doctorId}/`);
    return tpl;
  }

  function getDoctorById(id) {
    return doctors.find((d) => d.id === String(id)) || null;
  }

  function firstDoctorWithQueue() {
    return (
      doctors.find((d) => Array.isArray(d.queue) && d.queue.length > 0) || null
    );
  }

  function getActiveDoctorIndex() {
    if (!doctors.length) return 0;
    if (activeDoctorId) {
      const idx = doctors.findIndex((d) => d.id === String(activeDoctorId));
      if (idx >= 0) return idx;
    }
    return 0;
  }

  function doctorHasWaiting(doctorId) {
    const doc = getDoctorById(doctorId);
    if (!doc || !Array.isArray(doc.queue)) return false;
    return doc.queue.length > 1;
  }

  function ensureActiveDoctorForServing(filterValue) {
    if (filterValue && filterValue !== "all") {
      activeDoctorId = String(filterValue);
      return;
    }

    if (activeDoctorId) {
      const activeDoc = getDoctorById(activeDoctorId);
      if (
        activeDoc &&
        Array.isArray(activeDoc.queue) &&
        activeDoc.queue.length > 0
      )
        return;
    }

    const docWithQueue = firstDoctorWithQueue();
    activeDoctorId = docWithQueue
      ? docWithQueue.id
      : doctors[0]
      ? doctors[0].id
      : null;
  }

  // ==============
  // MAP API → DOCTORS
  // ==============
  function mapQueuesToDoctorsFromSnapshot(rawQueues) {
    const mapped = (rawQueues || []).map((q) => {
      const doctorId = q.doctor_id ?? q.id ?? q.doctorId ?? "";
      const doctorName = q.doctor_name ?? q.doctorName ?? "Doctor";

      const current = q.current_patient || q.current || null;
      const waitingList = q.waiting_list || q.waiting || [];

      const queueItems = [];

      if (current) {
        queueItems.push({
          ticket: current.number || current.ticket || q.next_queue || "",
          name: current.patient_name || current.patient || current.name || "",
        });
      } else if (q.next_queue && q.next_queue !== "No appointments") {
        queueItems.push({ ticket: q.next_queue, name: "" });
      }

      if (Array.isArray(waitingList)) {
        waitingList.forEach((w) => {
          queueItems.push({
            ticket: w.number || w.ticket || "",
            name: w.patient_name || w.patient || w.name || "",
          });
        });
      }

      return {
        id: String(doctorId),
        name: doctorName,
        specialty: q.specialty || "",
        room: q.room || q.room_label || "",
        queue: queueItems,
      };
    });

    doctors = mapped;
  }

  // ==============
  // AUTO ANNOUNCER (ON CHANGE)
  // ==============
  const announceState = {}; // docId -> { ticket, lastAt }
  let announceInFlight = false;

  let audioCtx = null;
  let audioUnlocked = false;

  function getAudioCtx() {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    if (!audioCtx) audioCtx = new AC();
    return audioCtx;
  }

  async function unlockAudio() {
    const ctx = getAudioCtx();
    try {
      if (ctx && ctx.state === "suspended") await ctx.resume();
    } catch (_) {}
    audioUnlocked = true;
  }

  // ✅ Overlay يظهر مرة واحدة: Enable Sound (localStorage) / Later (sessionStorage)
  function showSoundOverlayIfNeeded() {
    if (!SHOW_SOUND_UNLOCK_OVERLAY) return;
    if (!(ENABLE_VOICE || ENABLE_BEEP)) return;

    const overlay = document.getElementById("sound-unlock");
    const btn = document.getElementById("sound-unlock-btn");
    const close = document.getElementById("sound-unlock-close");
    if (!overlay || !btn || !close) return;

    const LS_KEY = "ch_sound_enabled_v1";
    const SS_KEY = "ch_sound_overlay_dismiss_v1";

    try {
      // إذا تم تفعيل الصوت سابقاً → لا تظهر
      if (localStorage.getItem(LS_KEY) === "1") return;
      // إذا ضغط Later في نفس التب → لا تظهر بالرفريش
      if (sessionStorage.getItem(SS_KEY) === "1") return;
    } catch (_) {
      // إذا التخزين ممنوع، نكمل بشكل طبيعي
    }

    overlay.hidden = false;

    close.addEventListener("click", () => {
      overlay.hidden = true;
      try {
        sessionStorage.setItem(SS_KEY, "1");
      } catch (_) {}
    });

    btn.addEventListener("click", async () => {
      await unlockAudio();
      overlay.hidden = true;
      try {
        localStorage.setItem(LS_KEY, "1");
        sessionStorage.setItem(SS_KEY, "1");
      } catch (_) {}
      try {
        await beep({ duration: 120, frequency: 880, volume: 0.06 });
      } catch (_) {}
    });
  }

  async function beep(opts = {}) {
    if (!ENABLE_BEEP) return;
    const ctx = getAudioCtx();
    if (!ctx) return;

    if (!audioUnlocked) await unlockAudio();

    const duration = Number(opts.duration || 160);
    const frequency = Number(opts.frequency || 880);
    const volume = Number(opts.volume || 0.08);

    try {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.type = "sine";
      osc.frequency.value = frequency;

      const now = ctx.currentTime;
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.exponentialRampToValueAtTime(
        Math.max(0.0001, volume),
        now + 0.02
      );
      gain.gain.exponentialRampToValueAtTime(0.0001, now + duration / 1000);

      osc.connect(gain);
      gain.connect(ctx.destination);

      osc.start(now);
      osc.stop(now + duration / 1000 + 0.02);
    } catch (_) {}
  }

  function hasSpeech() {
    return "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
  }

  function getLangTag(shortLang) {
    return shortLang === "ar" ? SPEECH_LANG_AR : SPEECH_LANG_EN;
  }

  function pickBestVoice(langTag) {
    try {
      const voices = window.speechSynthesis.getVoices() || [];
      if (!voices.length) return null;

      const low = String(langTag || "").toLowerCase();
      const exact = voices.find(
        (v) => String(v.lang || "").toLowerCase() === low
      );
      if (exact) return exact;

      const prefix = low.split("-")[0];
      const pref = voices.find((v) =>
        String(v.lang || "")
          .toLowerCase()
          .startsWith(prefix)
      );
      if (pref) return pref;

      return voices[0] || null;
    } catch (_) {
      return null;
    }
  }

  function speakOnce(text, shortLang) {
    return new Promise((resolve) => {
      if (!ENABLE_VOICE || !hasSpeech()) return resolve();

      const cleaned = String(text || "").trim();
      if (!cleaned) return resolve();

      if (ANNOUNCE_REQUIRE_VISIBLE_TAB && document.hidden) return resolve();

      try {
        const u = new SpeechSynthesisUtterance(cleaned);

        const langTag = getLangTag(shortLang);
        u.lang = langTag;

        const v = pickBestVoice(langTag);
        if (v) u.voice = v;

        u.rate = Number(CONFIG.SPEECH_RATE || 1.0);
        u.pitch = Number(CONFIG.SPEECH_PITCH || 1.0);
        u.volume = Number(CONFIG.SPEECH_VOLUME || 1.0);

        u.onend = () => resolve();
        u.onerror = () => resolve();

        window.speechSynthesis.speak(u);

        setTimeout(resolve, 9000);
      } catch (_) {
        resolve();
      }
    });
  }

  function stopSpeech() {
    try {
      if (hasSpeech()) window.speechSynthesis.cancel();
    } catch (_) {}
  }

  function toEasternDigits(s) {
    const map = ["٠", "١", "٢", "٣", "٤", "٥", "٦", "٧", "٨", "٩"];
    return String(s).replace(/\d/g, (d) => map[Number(d)]);
  }

  // ✅ Announces: current + doctor + (next) when available
  function buildAnnouncementText(payload, shortLang) {
    const number = String(payload.number || "").trim();
    const patient = String(payload.patient || "").trim();
    const doctor = String(payload.doctor || "").trim();

    const nextNumber = String(payload.next_number || "").trim();
    const nextPatient = String(payload.next_patient || "").trim();
    const hasNext = Boolean(nextNumber);

    if (shortLang === "ar") {
      const n = toEasternDigits(number);

      const nowPart =
        CAN_SAY_PATIENT_NAME && patient
          ? `المريض ${patient}. رقم ${n}. تفضل إلى عيادة الدكتور ${doctor}.`
          : `رقم ${n}. تفضل إلى عيادة الدكتور ${doctor}.`;

      if (!hasNext) return nowPart;

      const nn = toEasternDigits(nextNumber);
      const nextPart =
        CAN_SAY_PATIENT_NAME && nextPatient
          ? `التالي ${nextPatient}. رقم ${nn}.`
          : `الرقم التالي ${nn}.`;

      return `${nowPart} ${nextPart}`;
    }

    const nowPart =
      CAN_SAY_PATIENT_NAME && patient
        ? `Patient ${patient}. Ticket ${number}. Please proceed to Dr. ${doctor}.`
        : `Ticket ${number}. Please proceed to Dr. ${doctor}.`;

    if (!hasNext) return nowPart;

    const nextPart =
      CAN_SAY_PATIENT_NAME && nextPatient
        ? `Next is ${nextPatient}. Ticket ${nextNumber}.`
        : `Next ticket is ${nextNumber}.`;

    return `${nowPart} ${nextPart}`;
  }

  async function playQueueAnnouncement(payload) {
    if (!(ENABLE_BEEP || ENABLE_VOICE)) return;
    if (!payload || !payload.number || !payload.doctor) return;

    if (announceInFlight) return;
    announceInFlight = true;

    try {
      void unlockAudio();
      stopSpeech();

      await beep({ duration: 160, frequency: 880, volume: 0.08 });
      await beep({ duration: 120, frequency: 988, volume: 0.06 });

      for (const lang of ANNOUNCE_SEQUENCE) {
        if (lang !== "ar" && lang !== "en") continue;
        const text = buildAnnouncementText(payload, lang);
        await speakOnce(text, lang);
        await new Promise((r) => setTimeout(r, 220));
      }
    } finally {
      announceInFlight = false;
    }
  }

  // نخليها متاحة لأي كود ثاني إذا احتجتي
  window.playQueueAnnouncement = playQueueAnnouncement;

  async function announceChangesIfAny() {
    if (!AUTO_ANNOUNCE_ON_CHANGE) return;
    if (!(ENABLE_BEEP || ENABLE_VOICE)) return;
    if (ANNOUNCE_REQUIRE_VISIBLE_TAB && document.hidden) return;

    const now = Date.now();
    const toAnnounce = [];

    doctors.forEach((doc) => {
      const cur = doc.queue && doc.queue[0];
      const ticket = cur && String(cur.ticket || "").trim();
      if (!ticket) return;

      const docId = String(doc.id);
      const st = announceState[docId] || { ticket: null, lastAt: 0 };

      const changed = st.ticket !== ticket;

      // حدّث التذكرة دائماً حتى ما يكرر نفس الحالة
      st.ticket = ticket;
      announceState[docId] = st;

      if (!changed) return;

      const cooldownOk = now - st.lastAt >= PER_DOCTOR_ANNOUNCE_COOLDOWN_MS;
      if (!cooldownOk) return;

      st.lastAt = now;
      announceState[docId] = st;

      const next = doc.queue && doc.queue[1] ? doc.queue[1] : null;

      toAnnounce.push({
        number: ticket,
        patient: cur.name || "",
        doctor: doc.name || "",
        next_number: next ? String(next.ticket || "").trim() : "",
        next_patient: next ? String(next.name || "").trim() : "",
      });
    });

    for (const p of toAnnounce) {
      await playQueueAnnouncement(p);
      await new Promise((r) => setTimeout(r, 350));
    }
  }

  // ==============
  // LOAD QUEUE
  // ==============
  async function loadQueues() {
    if (loadInFlight) {
      loadQueued = true;
      return;
    }
    loadInFlight = true;

    const previousFilter = (() => {
      const sel = document.getElementById("doctor-filter");
      return sel ? sel.value : "all";
    })();

    try {
      const res = await fetch(QUEUE_API, {
        method: "GET",
        headers: { Accept: "application/json" },
        cache: "no-store",
        credentials: "same-origin",
      });

      if (res.status === 401 || res.status === 403) {
        if (window.onQueueFetchError)
          window.onQueueFetchError(t("errUnauthorized"));
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const payload = await res.json();

      if (payload && Array.isArray(payload.doctors)) {
        doctors = payload.doctors.map((d) => ({
          id: String(d.id),
          name: d.name || "Doctor",
          specialty: d.specialty || "",
          room: d.room || d.room_label || "",
          queue: (d.queue || []).map((p) => ({
            ticket: p.ticket || p.number || "",
            name: p.patient || p.name || p.patient_name || "",
          })),
        }));
      } else {
        const rawQueues = (payload && payload.queues) || [];
        mapQueuesToDoctorsFromSnapshot(rawQueues);
      }

      ensureActiveDoctorForServing(previousFilter);

      renderDoctorFilterOptions(previousFilter);
      renderAll();

      // ✅ إعلان تلقائي إذا تغيّر الدور (حتى لو السكرتيرة نادت من تب ثاني)
      void announceChangesIfAny();

      if (window.onQueueFetchError) window.onQueueFetchError("");
    } catch (err) {
      console.error("Queue load error:", err);
      if (window.onQueueFetchError) {
        window.onQueueFetchError((err && err.message) || t("errGeneric"));
      }
    } finally {
      loadInFlight = false;
      if (loadQueued) {
        loadQueued = false;
        void loadQueues();
      }
    }
  }

  // ==============
  // TICKER
  // ==============
  function updateTickerMessage() {
    const tickerEl = document.querySelector(".q-ticker");
    if (!tickerEl) return;

    const arr = tickerMessages[currentLang] || tickerMessages.en;
    if (!arr || !arr.length) return;

    tickerEl.textContent = arr[tickerIndex];
    tickerIndex = (tickerIndex + 1) % arr.length;
  }

  // ==============
  // TICKETS & CURRENT
  // ==============
  function getAllTickets() {
    const items = [];
    doctors.forEach((doc) => {
      (doc.queue || []).forEach((q, index) => {
        items.push({
          doctorId: doc.id,
          doctorName: doc.name,
          ticket: q.ticket,
          patient: q.name,
          position: index,
        });
      });
    });
    return items;
  }

  function getCurrentTicket() {
    const select = document.getElementById("doctor-filter");
    const filterValue = select ? select.value : "all";

    ensureActiveDoctorForServing(filterValue);

    if (!doctors.length) return null;

    let doc = null;
    if (filterValue && filterValue !== "all") {
      doc = getDoctorById(filterValue);
    } else {
      doc = activeDoctorId ? getDoctorById(activeDoctorId) : null;
      if (!doc || !doc.queue || doc.queue.length === 0) doc = firstDoctorWithQueue();
    }

    if (!doc || !doc.queue || doc.queue.length === 0) return null;

    return {
      doctorId: doc.id,
      doctorName: doc.name,
      room: doc.room || "",
      specialty: doc.specialty || "",
      ticket: doc.queue[0].ticket,
      patient: doc.queue[0].name,
      waitingCount: Math.max(doc.queue.length - 1, 0),
    };
  }

  // ==============
  // RENDER
  // ==============
  function renderNowServing() {
    const panel = document.getElementById("now-serving");
    if (!panel) return;

    panel.innerHTML = "";
    const current = getCurrentTicket();
    const div = document.createElement("div");

    if (!current) {
      div.innerHTML = `
        <div class="now-serving-label">${escapeHTML(t("labelNone"))}</div>
        <div class="now-serving-patient">${escapeHTML(t("emptyTicket"))}</div>
      `;
      panel.appendChild(div);
      return;
    }

    const roomLabel = current.room ? `${t("roomPrefix")} ${current.room}` : "";

    div.innerHTML = `
      <div class="now-serving-label">${escapeHTML(t("labelTicket"))}</div>
      <div class="now-serving-ticket">${escapeHTML(current.ticket || "")}</div>
      <div class="now-serving-patient">${escapeHTML(current.patient || "")}</div>

      <div class="now-serving-meta">
        <span class="chip"><i class="fa-solid fa-user-doctor"></i> ${escapeHTML(
          current.doctorName || ""
        )}</span>
        <span class="chip"><i class="fa-solid fa-door-open"></i> ${escapeHTML(
          roomLabel
        )}</span>
        <span class="chip">${escapeHTML(current.specialty || "")}</span>
      </div>

      <div class="now-serving-bottom">
        <span>${escapeHTML(
          t("labelWaitingForDoctor")
        )}: <strong>${escapeHTML(String(current.waitingCount))}</strong></span>
        <span class="status-pill">
          <i class="fa-solid fa-volume-high"></i> ${escapeHTML(t("statusCalling"))}
        </span>
      </div>
    `;

    panel.appendChild(div);
    panel.classList.remove("flash");
    panel.offsetWidth;
    panel.classList.add("flash");
  }

  function renderDoctorsGrid(filterDoctorId = "all") {
    const container = document.getElementById("doctors-grid");
    if (!container) return;

    container.innerHTML = "";
    const activeIdx = getActiveDoctorIndex();

    doctors.forEach((doc, index) => {
      if (filterDoctorId !== "all" && filterDoctorId !== doc.id) return;

      const card = document.createElement("article");
      card.className = "doctor-card";
      if (index === activeIdx) card.classList.add("active");

      const current = (doc.queue || [])[0];
      const waitingCount = Math.max((doc.queue || []).length - 1, 0);
      const nextPatients = (doc.queue || []).slice(1, 4);
      const roomLabel = doc.room ? `${t("roomPrefix")} ${doc.room}` : "";

      const nextListHTML =
        nextPatients.length > 0
          ? nextPatients
              .map(
                (p) =>
                  `<li><span>${escapeHTML(t("labelNext"))}</span><span>${escapeHTML(
                    (p.ticket || "") + " – " + (p.name || "")
                  )}</span></li>`
              )
              .join("")
          : `<li><span>${escapeHTML(t("labelNext"))}</span><span>${escapeHTML(
              t("labelNoQueue")
            )}</span></li>`;

      card.innerHTML = `
        <div class="doc-header">
          <div>
            <div class="doc-name">${escapeHTML(doc.name || "")}</div>
            <div class="doc-specialty">${escapeHTML(doc.specialty || "")}</div>
          </div>
          <div class="doc-room-pill">${escapeHTML(roomLabel)}</div>
        </div>

        <div class="doc-current">
          <span>${escapeHTML(t("labelCurrentTicket"))}</span>
          <span>${
            current
              ? escapeHTML((current.ticket || "") + " – " + (current.name || ""))
              : "—"
          }</span>
        </div>

        <ul class="doc-next-list">${nextListHTML}</ul>

        <div class="doc-footer">
          <span class="badge-waiting">${escapeHTML(String(waitingCount))} ${escapeHTML(
            t("waitingWord")
          )}</span>
          <span>${escapeHTML(String((doc.queue || []).length))} ${escapeHTML(
            t("totalWord")
          )}</span>
        </div>
      `;

      container.appendChild(card);
    });
  }

  function renderQueueOverview(filterDoctorId = "all") {
    const list = document.getElementById("queue-overview");
    if (!list) return;

    list.innerHTML = "";

    const tickets = getAllTickets().filter((item) =>
      filterDoctorId === "all" ? true : item.doctorId === filterDoctorId
    );

    tickets.forEach((item) => {
      const li = document.createElement("li");
      li.className = "queue-overview-item";
      li.innerHTML = `
        <div class="queue-ticket">${escapeHTML(item.ticket || "")}</div>
        <div class="queue-patient">${escapeHTML(item.patient || "")}</div>
        <div class="queue-doctor">${escapeHTML(item.doctorName || "")}</div>
      `;
      list.appendChild(li);
    });
  }

  function renderDoctorFilterOptions(preferredValue = "all") {
    const select = document.getElementById("doctor-filter");
    if (!select) return;

    const keep = preferredValue || select.value || "all";

    let allOpt = select.querySelector("option[value='all']");
    if (!allOpt) {
      allOpt = document.createElement("option");
      allOpt.value = "all";
      select.appendChild(allOpt);
    }
    allOpt.textContent = t("filterAll");

    while (select.options.length > 1) select.remove(1);

    doctors.forEach((doc) => {
      const opt = document.createElement("option");
      opt.value = doc.id;
      opt.textContent = doc.name;
      select.appendChild(opt);
    });

    const exists = Array.from(select.options).some((o) => o.value === keep);
    select.value = exists ? keep : "all";
  }

  function applyLanguageStaticTexts() {
    const subtitleEl = document.querySelector(".q-subtitle");
    const msgEl = document.querySelector(".q-message");
    const filterLabelEl = document.getElementById("filter-label-text");
    const titleNowEl = document.getElementById("title-now");
    const titleDocsEl = document.getElementById("title-docs");
    const titleQueueEl = document.getElementById("title-queue");
    const btn = document.getElementById("call-next-btn");

    if (subtitleEl) subtitleEl.textContent = t("headerSubtitle");
    if (msgEl) msgEl.textContent = t("headerMessage");
    if (filterLabelEl) filterLabelEl.textContent = t("filterLabel");
    if (titleNowEl) titleNowEl.textContent = t("panelNowServing");
    if (titleDocsEl) titleDocsEl.textContent = t("panelDoctors");
    if (titleQueueEl) titleQueueEl.textContent = t("panelQueue");

    if (btn) {
      if (!IS_INTERNAL_USER) {
        btn.style.display = "none";
      } else {
        btn.style.display = "";
        btn.textContent = autoCallTimer ? t("btnAutoOff") : t("btnAutoOn");
      }
    }

    tickerIndex = 0;
    updateTickerMessage();

    if (currentLang === "ar") {
      document.documentElement.classList.add("rtl");
      document.documentElement.setAttribute("lang", "ar");
    } else {
      document.documentElement.classList.remove("rtl");
      document.documentElement.setAttribute("lang", "en");
    }
  }

  function renderAll() {
    const select = document.getElementById("doctor-filter");
    const filterValue = select ? select.value : "all";

    ensureActiveDoctorForServing(filterValue);

    renderNowServing();
    renderDoctorsGrid(filterValue);
    renderQueueOverview(filterValue);
  }

  // ==============
  // CALL NEXT (INTERNAL BUTTON ON THIS SCREEN)
  // ==============
  async function callNextTicket() {
    if (!IS_INTERNAL_USER) return;
    if (!doctors.length) return;
    if (callInFlight) return;

    const now = Date.now();
    if (now - lastCallAt < MIN_CALL_GAP_MS) return;
    lastCallAt = now;

    // gesture يساعد unlock
    await unlockAudio();

    const select = document.getElementById("doctor-filter");
    const filterValue = select ? select.value : "all";
    ensureActiveDoctorForServing(filterValue);

    const targetDoctorId =
      filterValue !== "all"
        ? filterValue
        : activeDoctorId || (doctors[0] && doctors[0].id);

    if (!targetDoctorId) return;

    // ✅ لا تحرك الدور إذا ماكو منتظرين
    if (!doctorHasWaiting(targetDoctorId)) return;

    const url = buildCallNextUrl(targetDoctorId);
    if (!url) return;

    callInFlight = true;

    try {
      const res = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrfToken(),
          Accept: "application/json",
        },
        credentials: "same-origin",
        body: JSON.stringify({}),
      });

      if (!res.ok) return;

      activeDoctorId = String(targetDoctorId);

      // يعتمد على auto announce داخل loadQueues
      await loadQueues();
    } catch (err) {
      console.error("Error calling next ticket:", err);
    } finally {
      callInFlight = false;
    }
  }

  async function autoTick() {
    if (!autoCallTimer) return;
    if (!IS_INTERNAL_USER) return;

    const select = document.getElementById("doctor-filter");
    const filterValue = select ? select.value : "all";

    ensureActiveDoctorForServing(filterValue);

    const targetDoctorId =
      filterValue !== "all"
        ? filterValue
        : activeDoctorId || (doctors[0] && doctors[0].id);

    if (!targetDoctorId) return;

    // ✅ إذا ماكو منتظرين، أوقف الأوتو حتى ما يظل “يكنس”
    if (!doctorHasWaiting(targetDoctorId)) {
      stopAutoMode();
      return;
    }

    await callNextTicket();

    if (!doctorHasWaiting(targetDoctorId)) stopAutoMode();
  }

  async function startAutoMode() {
    if (autoCallTimer) return;
    if (!IS_INTERNAL_USER) return;

    await unlockAudio();
    await autoTick();

    autoCallTimer = setInterval(() => {
      void autoTick();
    }, AUTO_CALL_INTERVAL);

    applyLanguageStaticTexts();
  }

  function stopAutoMode() {
    if (!autoCallTimer) return;
    clearInterval(autoCallTimer);
    autoCallTimer = null;
    applyLanguageStaticTexts();
  }

  // ==============
  // INIT
  // ==============
  document.addEventListener("DOMContentLoaded", () => {
    updateClock();
    setInterval(updateClock, 1000);

    showSoundOverlayIfNeeded();

    // ✅ Unlock audio on first user interaction (helps auto announce)
    document.addEventListener(
      "pointerdown",
      () => {
        void unlockAudio();
      },
      { once: true, passive: true }
    );

    document.querySelectorAll(".lang-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const lang = btn.dataset.lang || "en";
        if (lang === currentLang) return;
        currentLang = lang;

        document
          .querySelectorAll(".lang-btn")
          .forEach((b) => b.classList.toggle("active", b === btn));

        applyLanguageStaticTexts();

        const sel = document.getElementById("doctor-filter");
        const keep = sel ? sel.value : "all";
        renderDoctorFilterOptions(keep);

        renderAll();
      });
    });

    const filterSelect = document.getElementById("doctor-filter");
    if (filterSelect) {
      filterSelect.addEventListener("change", () => {
        renderAll();
      });
    }

    const callNextBtn = document.getElementById("call-next-btn");
    if (callNextBtn) {
      if (!IS_INTERNAL_USER) {
        callNextBtn.style.display = "none";
      } else {
        callNextBtn.addEventListener("click", () => {
          if (!autoCallTimer) void startAutoMode();
          else stopAutoMode();
        });
      }
    }

    applyLanguageStaticTexts();

    void loadQueues();
    setInterval(() => void loadQueues(), REFRESH_INTERVAL);

    updateTickerMessage();
    setInterval(updateTickerMessage, 15000);

    window.__queueSystemInstance = {
      getServingPatients() {
        const cur = getCurrentTicket();
        if (!cur) return [];
        return [
          { number: cur.ticket, patient: cur.patient, doctor: cur.doctorName },
        ];
      },
    };
  });
})();
