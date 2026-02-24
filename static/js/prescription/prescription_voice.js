// static/js/prescription_voice.js

document.addEventListener('DOMContentLoaded', () => {
  const startBtn     = document.getElementById('startRecordBtn');
  const stopBtn      = document.getElementById('stopRecordBtn');
  const resetBtn     = document.getElementById('resetRecordBtn');
  const recordStatus = document.getElementById('recordStatus');
  const audioPlayer  = document.getElementById('audioPlayer');

  // ✅ التصحيح المهم
  const voiceInput =
    document.getElementById('id_voice_note') ||
    document.querySelector('input[name="voice_note"]');

  let mediaRecorder = null;
  let audioChunks = [];
  let currentStream = null;

  // حماية إذا عناصر الصفحة ناقصة
  if (!startBtn || !stopBtn || !resetBtn || !recordStatus || !audioPlayer) {
    console.warn("Voice UI elements not found.");
    return;
  }

  // تأكد من دعم MediaRecorder
  if (!navigator.mediaDevices || typeof MediaRecorder === 'undefined') {
    startBtn.disabled = true;
    recordStatus.textContent = '⚠️ التسجيل غير مدعوم في هذا المتصفح.';
    return;
  }

  function stopStream() {
    if (currentStream) {
      currentStream.getTracks().forEach(t => t.stop());
      currentStream = null;
    }
  }

  // ابدأ التسجيل
  startBtn.addEventListener('click', async () => {
    try {
      currentStream = await navigator.mediaDevices.getUserMedia({ audio: true });

      const options = {};
      if (MediaRecorder.isTypeSupported('audio/webm')) {
        options.mimeType = 'audio/webm';
      }

      mediaRecorder = new MediaRecorder(currentStream, options);
      audioChunks = [];

      mediaRecorder.ondataavailable = e => {
        if (e.data && e.data.size > 0) audioChunks.push(e.data);
      };

      mediaRecorder.onstop = () => {
        try {
          const blobType = mediaRecorder.mimeType || 'audio/webm';
          const blob = new Blob(audioChunks, { type: blobType });
          const url  = URL.createObjectURL(blob);

          // عرض الصوت على الواجهة
          audioPlayer.src = url;
          audioPlayer.classList.remove('d-none');

          // ✅ ربط الملف بحقل الفورم حتى ينحفظ في DB
          if (voiceInput) {
            const ext = blobType.includes('webm') ? 'webm' : 'audio';
            const file = new File([blob], `voice_note.${ext}`, { type: blobType });

            const dt = new DataTransfer();
            dt.items.add(file);
            voiceInput.files = dt.files;
          } else {
            console.warn("voice_note input not found in DOM.");
          }

          resetBtn.disabled = false;
          recordStatus.textContent = '✅ جاهز للإرسال.';
        } finally {
          stopStream();
        }
      };

      mediaRecorder.start();

      recordStatus.textContent = '🎙️ جاري التسجيل…';
      startBtn.disabled = true;
      stopBtn.disabled  = false;
      resetBtn.disabled = true;

    } catch (err) {
      alert('عنصر الميكروفون غير متاح أو تم رفض الإذن.');
      console.error(err);
      stopStream();
    }
  });

  // إيقاف التسجيل
  stopBtn.addEventListener('click', () => {
    if (mediaRecorder && mediaRecorder.state === 'recording') {
      mediaRecorder.stop();
      recordStatus.textContent = '⏹️ توقف التسجيل.';
      startBtn.disabled = false;
      stopBtn.disabled  = true;
    }
  });

  // إعادة التعيين
  resetBtn.addEventListener('click', () => {
    audioChunks = [];

    audioPlayer.pause();
    audioPlayer.src = '';
    audioPlayer.classList.add('d-none');

    if (voiceInput) {
      voiceInput.value = '';
    }

    recordStatus.textContent = '🔄 تم إعادة التعيين.';
    resetBtn.disabled = true;

    startBtn.disabled = false;
    stopBtn.disabled  = true;

    stopStream();
  });

});
