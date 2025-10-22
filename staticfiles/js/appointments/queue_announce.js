/* static/js/appointments/announce_queue.js
 * Pro-grade bilingual (Arabic & English) queue announcements + live signage.
 * - Uses real API data (APP_CONFIG.QUEUE_API or /appointments/api/queue/)
 * - Default AR→EN sequence (override via APP_CONFIG.ANNOUNCE_SEQUENCE)
 * - Proper Arabic voice auto-pick (reads Arabic names); UI voice override
 * - Eastern Arabic numerals (٧ بدل 7) for Arabic lines
 * - Chime before speech, safe queue, global/per-doctor cooldown
 * - Visible-tab only (saves CPU), robust against empty voices list
 * - Optional live signage rendering if you include a <div id="queue-list">
 * - Public helpers: queueSpeak(text, lang), queueSpeakAuto(text), queueAnnounceFor(obj)
 */
(function () {
    "use strict";
  
    // ===================== CONFIG =====================
    const CFG = {
      API_URL: (window.APP_CONFIG && APP_CONFIG.QUEUE_API) || "/appointments/api/queue/",
      POLL_MS: 6000,
      ANNOUNCE_SEQUENCE: (window.APP_CONFIG && APP_CONFIG.ANNOUNCE_SEQUENCE) || ["ar", "en"],
      GLOBAL_THROTTLE_MS: 2500,
      PER_DOCTOR_COOLDOWN_MS: 12000,
      CHIME_ENABLED: true,
      CHIME_TONE_MS: 240,
      CHIME_GAP_MS: 80,
      CHIME_TONES: [880, 1175], // A5 → D6
      DEFAULT_LANGS: { ar: "ar-SA", en: "en-US" },
      AR_EASTERN_NUMERALS: true,
      REQUIRE_VISIBLE_TAB: true,
      MAX_UTTER_CHARS: 280, // split very long text defensively
    };
  
    // =================== UI ELEMENTS ===================
    const btnToggle = document.getElementById("toggle-announce");
    const selVoice = document.getElementById("voice-select");         // global override
    const selVoiceEn = document.getElementById("voice-select-en");     // (optional) per-lang EN
    const selVoiceAr = document.getElementById("voice-select-ar");     // (optional) per-lang AR
    const rateEl = document.getElementById("rate");
    const volEl = document.getElementById("volume");
    const testBtn = document.getElementById("test-announce");
    const listEl = document.getElementById("queue-list");              // optional: live signage
  
    // =================== LOCAL STORAGE =================
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
  
    if (rateEl) rateEl.value = rate;
    if (volEl) volEl.value = volume;
  
    // ================== SPEECH PIPELINE =================
    const speechQueue = [];
    let speaking = false;
    let lastGlobalAt = 0;
  
    function queueUtter(text, lang) {
      if (!text || !("speechSynthesis" in window)) return;
      // Split big chunks to avoid occasional clipping on some browsers
      const chunks = String(text).match(new RegExp(`.{1,${CFG.MAX_UTTER_CHARS}}`, "g")) || [];
      chunks.forEach((c) => speechQueue.push({ text: c, lang }));
      pump();
    }
  
    function pump() {
      if (!enabled || speaking || !speechQueue.length || !("speechSynthesis" in window)) return;
  
      const now = Date.now();
      if (now - lastGlobalAt < CFG.GLOBAL_THROTTLE_MS) {
        setTimeout(pump, CFG.GLOBAL_THROTTLE_MS - (now - lastGlobalAt) + 10);
        return;
      }
  
      const { text, lang } = speechQueue.shift();
      speaking = true;
  
      const utter = new SpeechSynthesisUtterance(text);
      const v = pickVoice(lang);
      if (v) {
        utter.voice = v;
        // Trust the voice language if available
        if (v.lang) utter.lang = v.lang;
      } else {
        utter.lang = lang === "ar" ? CFG.DEFAULT_LANGS.ar : CFG.DEFAULT_LANGS.en;
      }
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
  
      speechSynthesis.speak(utter);
    }
  
    function flush() {
      if ("speechSynthesis" in window) speechSynthesis.cancel();
      speechQueue.length = 0;
      speaking = false;
    }
  
    // ====================== CHIME ======================
    function chime() {
      if (!CFG.CHIME_ENABLED || !window.AudioContext) return Promise.resolve();
      const ctx = new AudioContext();
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
  
      const total = CFG.CHIME_TONES.length * (CFG.CHIME_TONE_MS + CFG.CHIME_GAP_MS);
      return new Promise((r) => setTimeout(r, total + 30));
    }
  
    // ===================== VOICES ======================
    function loadVoicesIntoSelects() {
      voices = window.speechSynthesis ? speechSynthesis.getVoices() : [];
  
      // Fill global select
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
  
      // Optional per-language selects if present
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
          .filter((v) => /^ar(\b|-|_)/i.test(v.lang) || /arabic/i.test(v.name))
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
  
    // Stronger Arabic detection/pick to ensure Arabic names are read correctly
    function pickVoice(lang) {
      if (!("speechSynthesis" in window)) return null;
  
      // 1) Global override
      if (voiceOverride) {
        const v = vByName(voiceOverride);
        if (v) return v;
      }
  
      // 2) Per-language override (UI or localStorage)
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
  
      // 3) Auto-pick by language with better heuristics
      const prefer = (pred) => {
        const list = voices.filter(pred);
        // Prefer natural neural voices if present
        const neural = list.find((v) => /Natural|Online/i.test(v.name));
        return neural || list[0] || null;
      };
  
      if (lang === "ar") {
        // Common Arabic voice names across browsers:
        // "Microsoft Naayf - Arabic (Saudi Arabia)", "Google العربية", etc.
        return (
          prefer((v) => /^ar(\b|-|_)/i.test(v.lang)) ||
          prefer((v) => /arabic/i.test(v.name)) ||
          prefer((v) => /^en(\b|-|_)/i.test(v.lang)) || // fallback to EN if no AR voice
          voices[0] ||
          null
        );
      }
  
      // EN
      return (
        prefer((v) => /^en(\b|-|_)/i.test(v.lang)) ||
        prefer((v) => /English/i.test(v.name)) ||
        voices[0] ||
        null
      );
    }
  
    // =================== UTILITIES =====================
    function toEasternDigits(s) {
      if (!CFG.AR_EASTERN_NUMERALS) return String(s);
      const map = ["٠", "١", "٢", "٣", "٤", "٥", "٦", "٧", "٨", "٩"];
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
  
    // Runtime override support
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
      // Accepts either:
      // A) Rich format:
      //   {
      //     doctor_id, doctor_name,
      //     current_patient: { id, number: "P-007", patient_name, time },
      //     waiting_list: [{ id, number, patient_name, time }, ...]
      //   }
      // B) Basic format (no names):
      //   { doctor_id, doctor_name, next_queue, waiting }
      //      -> we will announce number only.
  
      const now = queue.current_patient || null;
      const next = queue.waiting_list && queue.waiting_list.length ? queue.waiting_list[0] : null;
  
      const num = now ? normalizeNumber(now.number || now.queue_number || "") : (queue.next_queue || "");
      const patientNow = now ? sanitizeName(now.patient_name) : "";
      const patientNext = next ? sanitizeName(next.patient_name) : "";
      const doctor = sanitizeName(queue.doctor_name || "");
  
      const enParts = [];
      const arParts = [];
  
      if (num) {
        enParts.push(TPL.en.now({ num, patient: patientNow || "—", doctor }));
        arParts.push(TPL.ar.now({ num, patient: patientNow || "—", doctor }));
      }
      if (patientNext) {
        enParts.push(TPL.en.next({ patient: patientNext }));
        arParts.push(TPL.ar.next({ patient: patientNext }));
      }
  
      return { enText: enParts.filter(Boolean).join(" "), arText: arParts.filter(Boolean).join(" ") };
    }
  
    async function announceQueue(queue) {
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
    const docState = {}; // { [doctorId]: { currentId, nextId, lastAt } }
  
    function shouldAnnounce(doctorId, currentId, nextId) {
      const now = Date.now();
      const prev = docState[doctorId] || { currentId: null, nextId: null, lastAt: 0 };
      const changed = prev.currentId !== currentId || prev.nextId !== nextId;
      const cooldownOk = now - prev.lastAt >= CFG.PER_DOCTOR_COOLDOWN_MS;
      if (changed) docState[doctorId] = { currentId, nextId, lastAt: now };
      return changed && cooldownOk;
    }
  
    // ====================== POLLING =====================
    let pollTimer = null;
  
    async function poll() {
      if (CFG.REQUIRE_VISIBLE_TAB && document.hidden) return;
      try {
        const res = await fetch(CFG.API_URL, { headers: { Accept: "application/json" }, cache: "no-store" });
        if (!res.ok) return;
        const data = await res.json();
        if (!data || (data.success === false)) return;
  
        // Normalize to array of queues
        const queues = Array.isArray(data.queues) ? data.queues.slice() : [];
        queues.sort((a, b) => (a.doctor_id || 0) - (b.doctor_id || 0));
  
        // Optional: render live signage if container exists
        if (listEl) renderLiveSignage(queues);
  
        for (const q of queues) {
          const curId = q.current_patient ? q.current_patient.id : null;
          const nxtId = q.waiting_list && q.waiting_list.length ? q.waiting_list[0].id : null;
          // If only basic format exists, try to change by number
          const keyByNum = q.current_patient?.number || q.next_queue || "";
          const changed = curId || nxtId ? shouldAnnounce(q.doctor_id, curId, nxtId) : shouldAnnounce(q.doctor_id, keyByNum, null);
          if (changed) {
            await announceQueue(q);
            await new Promise((r) => setTimeout(r, 400)); // spacing between doctors
          }
        }
      } catch {
        // Silent tolerance for transient failures
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
          const now = q.current_patient || null;
          const next = q.waiting_list && q.waiting_list.length ? q.waiting_list[0] : null;
          const curNum = now ? normalizeNumber(now.number || "") : (q.next_queue || "");
          const curName = now ? sanitizeName(now.patient_name) : "—";
          const nextName = next ? sanitizeName(next.patient_name) : "—";
          const waiting = Array.isArray(q.waiting_list) ? q.waiting_list.length - (now ? 1 : 0) : (q.waiting || 0);
  
          return `
            <div class="doctor-card" role="group" aria-label="Doctor queue">
              <div class="doc-head">
                <div class="doc-avatar" aria-hidden="true">👨‍⚕️</div>
                <div class="doc-meta">
                  <div class="doc-name">Dr. ${sanitizeName(q.doctor_name || "")}</div>
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
                  <div class="name" dir="${detectLang(curName)==='ar' ? 'rtl':'ltr'}">${curName || "—"}</div>
                </div>
              </div>
              <div class="next-up">
                <div class="label">Next</div>
                <div class="next-name" dir="${detectLang(nextName)==='ar' ? 'rtl':'ltr'}">${nextName || "—"}</div>
              </div>
              <button class="btn-call" type="button" data-doc="${q.doctor_id || ""}">🔔 Call Next</button>
            </div>
          `;
        })
        .join("");
  
      // Optional: wire a "Call Next" demo trigger (front-end only).
      // If your real "Call Next" is server-side, dispatch the same event after success.
      listEl.querySelectorAll(".btn-call").forEach((btn) => {
        btn.addEventListener("click", () => {
          // In your real flow, replace with fetch(.../call_next) then:
          // document.dispatchEvent(new CustomEvent('queue:callNext:success', { detail: { queue } }));
          queueSpeak("Calling next.", "en");
        });
      });
    }
  
    // ======================= UI HOOKS ===================
    function refreshToggle() {
      if (!btnToggle) return;
      btnToggle.classList.toggle("active", enabled);
      btnToggle.textContent = enabled ? "🔇 Disable Announcements" : "🔊 Enable Announcements";
    }
  
    if (btnToggle) {
      btnToggle.addEventListener("click", () => {
        enabled = !enabled;
        localStorage.setItem(LS.enabled, JSON.stringify(enabled));
        refreshToggle();
        if (enabled) {
          startPolling();
          queueSpeak("تم تفعيل الإعلانات الصوتية.", "ar");
        } else {
          stopPolling();
          flush();
        }
      });
    }
  
    if (selVoice) {
      selVoice.addEventListener("change", () => {
        voiceOverride = selVoice.value || "";
        localStorage.setItem(LS.voiceOverride, voiceOverride);
        if (enabled) queueSpeak("Voice changed.", "en");
      });
    }
    if (selVoiceEn) {
      selVoiceEn.addEventListener("change", () => {
        localStorage.setItem(LS.voiceEN, selVoiceEn.value || "");
        voiceEN = selVoiceEn.value || "";
        if (enabled) queueSpeak("English voice set.", "en");
      });
    }
    if (selVoiceAr) {
      selVoiceAr.addEventListener("change", () => {
        localStorage.setItem(LS.voiceAR, selVoiceAr.value || "");
        voiceAR = selVoiceAr.value || "";
        if (enabled) queueSpeak("تم اختيار صوت عربي.", "ar");
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
      // Some browsers fire onvoiceschanged multiple times—re-fill idempotently.
      window.speechSynthesis.onvoiceschanged = loadVoicesIntoSelects;
    } else {
      document.getElementById("announce-unsupported")?.removeAttribute("hidden");
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
        await announceQueue(sample);
      });
    }
  
    // =================== PUBLIC HELPERS =================
    window.queueSpeak = function (text, langHint) {
      if (!text || !("speechSynthesis" in window)) return;
      queueUtter(String(text), langHint === "ar" ? "ar" : "en");
    };
  
    window.queueSpeakAuto = function (text) {
      if (!text || !("speechSynthesis" in window)) return;
      const lang = detectLang(String(text));
      queueUtter(String(text), lang);
    };
  
    window.queueAnnounceFor = async function (queueObj) {
      if (!queueObj) return;
      await announceQueue(queueObj);
    };
  
    // Immediate announce after backend “Call Next” success
    document.addEventListener("queue:callNext:success", (ev) => {
      const q = ev?.detail?.queue;
      if (q) announceQueue(q);
    });
  
    // ====================== LIFECYCLE ===================
    refreshToggle();
    if (enabled) startPolling();
    document.addEventListener("visibilitychange", () => {
      if (!CFG.REQUIRE_VISIBLE_TAB) return;
      if (document.hidden) stopPolling();
      else if (enabled) startPolling();
    });
  })();
  