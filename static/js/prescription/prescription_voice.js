// static/js/prescription/prescription_voice.js

document.addEventListener("DOMContentLoaded", () => {
  const form         = document.getElementById("prescriptionForm");
  const submitBtn    = document.getElementById("savePrescriptionBtn");
  const startBtn     = document.getElementById("startRecordBtn");
  const stopBtn      = document.getElementById("stopRecordBtn");
  const resetBtn     = document.getElementById("resetRecordBtn");
  const recordStatus = document.getElementById("recordStatus");
  const audioPlayer  = document.getElementById("audioPlayer");

  const voiceInput =
    document.getElementById("id_voice_note") ||
    document.querySelector('input[name="voice_note"]');

  let mediaRecorder = null;
  let audioChunks = [];
  let currentStream = null;
  let isFinalizingAudio = false;

  if (!form || !startBtn || !stopBtn || !resetBtn || !recordStatus || !audioPlayer) {
    console.warn("Prescription voice UI elements not found.");
    return;
  }

  if (!navigator.mediaDevices || typeof MediaRecorder === "undefined") {
    startBtn.disabled = true;
    recordStatus.textContent = "⚠️ التسجيل غير مدعوم في هذا المتصفح.";
    return;
  }

  function stopStream() {
    if (currentStream) {
      currentStream.getTracks().forEach((track) => track.stop());
      currentStream = null;
    }
  }

  function getSupportedMimeType() {
    const candidates = [
      "audio/webm",
      "audio/ogg",
      "audio/mp4",
      "audio/mpeg",
      "audio/wav",
    ];

    for (const type of candidates) {
      try {
        if (MediaRecorder.isTypeSupported(type)) {
          return type;
        }
      } catch (e) {
        console.warn("Mime type check failed:", e);
      }
    }

    return "";
  }

  function extensionFromMimeType(mimeType) {
    const type = String(mimeType || "").toLowerCase();

    if (type.includes("webm")) return "webm";
    if (type.includes("ogg"))  return "ogg";
    if (type.includes("mp4"))  return "m4a";
    if (type.includes("mpeg") || type.includes("mp3")) return "mp3";
    if (type.includes("wav"))  return "wav";

    return "webm";
  }

  function clearVoiceInput() {
    if (!voiceInput) return;
    try {
      voiceInput.value = "";
    } catch (e) {
      console.warn("Could not clear voice input:", e);
    }
  }

  function attachBlobToInput(blob, mimeType) {
    if (!voiceInput) {
      console.warn("voice_note input not found in DOM.");
      return false;
    }

    try {
      const ext = extensionFromMimeType(mimeType);
      const file = new File([blob], `voice_note.${ext}`, { type: mimeType || "audio/webm" });

      const dt = new DataTransfer();
      dt.items.add(file);
      voiceInput.files = dt.files;

      return true;
    } catch (e) {
      console.error("Failed attaching recorded blob to input:", e);
      return false;
    }
  }

  function resetPlayer() {
    audioPlayer.pause();
    audioPlayer.removeAttribute("src");
    audioPlayer.load();
    audioPlayer.classList.add("d-none");
  }

  function setSubmittingState(disabled) {
    if (submitBtn) {
      submitBtn.disabled = !!disabled;
    }
  }

  startBtn.addEventListener("click", async () => {
    try {
      resetPlayer();
      clearVoiceInput();
      audioChunks = [];
      isFinalizingAudio = false;

      currentStream = await navigator.mediaDevices.getUserMedia({ audio: true });

      const supportedMimeType = getSupportedMimeType();
      const options = supportedMimeType ? { mimeType: supportedMimeType } : {};

      mediaRecorder = new MediaRecorder(currentStream, options);

      mediaRecorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          audioChunks.push(event.data);
        }
      };

      mediaRecorder.onstop = () => {
        isFinalizingAudio = true;
        setSubmittingState(true);

        try {
          const blobType = mediaRecorder?.mimeType || supportedMimeType || "audio/webm";
          const blob = new Blob(audioChunks, { type: blobType });

          if (!blob || blob.size === 0) {
            recordStatus.textContent = "⚠️ لم يتم تسجيل صوت صالح.";
            resetBtn.disabled = true;
            return;
          }

          const url = URL.createObjectURL(blob);
          audioPlayer.src = url;
          audioPlayer.classList.remove("d-none");

          const attached = attachBlobToInput(blob, blobType);

          if (attached) {
            recordStatus.textContent = "✅ جاهز للإرسال.";
            resetBtn.disabled = false;
          } else {
            recordStatus.textContent = "⚠️ تم التسجيل لكن فشل ربطه بالفورم.";
            resetBtn.disabled = false;
          }
        } catch (err) {
          console.error("Error while finalizing audio:", err);
          recordStatus.textContent = "⚠️ حدث خطأ أثناء تجهيز التسجيل.";
        } finally {
          isFinalizingAudio = false;
          setSubmittingState(false);
          stopStream();
        }
      };

      mediaRecorder.start();

      recordStatus.textContent = "🎙️ جاري التسجيل…";
      startBtn.disabled = true;
      stopBtn.disabled = false;
      resetBtn.disabled = true;
      setSubmittingState(true);

    } catch (err) {
      alert("عنصر الميكروفون غير متاح أو تم رفض الإذن.");
      console.error(err);
      stopStream();
      setSubmittingState(false);
    }
  });

  stopBtn.addEventListener("click", () => {
    if (mediaRecorder && mediaRecorder.state === "recording") {
      recordStatus.textContent = "⏹️ يتم إنهاء التسجيل وتجهيزه...";
      stopBtn.disabled = true;

      try {
        mediaRecorder.stop();
      } catch (err) {
        console.error("Failed to stop recorder:", err);
        recordStatus.textContent = "⚠️ تعذر إيقاف التسجيل.";
        startBtn.disabled = false;
        stopBtn.disabled = true;
        setSubmittingState(false);
        stopStream();
      }

      startBtn.disabled = false;
    }
  });

  resetBtn.addEventListener("click", () => {
    audioChunks = [];
    isFinalizingAudio = false;

    resetPlayer();
    clearVoiceInput();

    recordStatus.textContent = "🔄 تم إعادة التعيين.";
    resetBtn.disabled = true;
    startBtn.disabled = false;
    stopBtn.disabled = true;

    setSubmittingState(false);
    stopStream();
  });

  form.addEventListener("submit", (event) => {
    if (mediaRecorder && mediaRecorder.state === "recording") {
      event.preventDefault();
      recordStatus.textContent = "⚠️ أوقفي التسجيل أولًا ثم احفظي الوصفة.";
      return;
    }

    if (isFinalizingAudio) {
      event.preventDefault();
      recordStatus.textContent = "⏳ انتظري لحظة، يتم تجهيز الصوت للإرسال...";
      return;
    }

    if (submitBtn) {
      submitBtn.disabled = true;
    }
  });
});